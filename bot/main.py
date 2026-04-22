"""Grok Telegram Bot entry point - aiogram 3.x Bot Token mode."""

import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, Update
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest

from bot.config import config
from bot.services.grok_api import stream_chat, generate_image, list_models
from bot.services.renderer import (
    render_full_response,
    split_long_message,
    extract_image_urls,
)
from bot.services.session import get_session, PROMPT_PRESETS

# Unicode constants
EMOJI_THINKING = "\U0001f9e0"
EMOJI_HOURGLASS = "\u23f3"
EMOJI_TRASH = "\U0001f5d1"
EMOJI_ART = "\U0001f3a8"
EMOJI_CROSS = "\u274c"
EMOJI_CHECK = "\u2705"
EMOJI_WARN = "\u26a0"
EMOJI_SEARCH = "\U0001f50d"
EMOJI_ROBOT = "\U0001f916"
EMOJI_PROMPT = "\U0001f4ac"

# Chinese text constants
TEXT_THINKING = "思考中..."
TEXT_PROCESSING = "\u26a0 上一个请求还在处理中，请稍等..."
TEXT_CLEARED = "\U0001f5d1 对话已清除，开始新对话"
TEXT_IMG_USAGE = "用法: /img <描述>"
TEXT_IMG_GEN = "\U0001f3a8 生成图片中..."
TEXT_IMG_FAIL = "\u274c 未生成图片"
TEXT_MODELS_FAIL = "\u274c 获取模型列表失败"
TEXT_SETMODEL_USAGE = "用法: /setmodel <model_id>"
TEXT_REASON_INVALID = (
    "\u274c 无效等级。可选: none, minimal, low, medium, high, xhigh\n"
    "用 /reason 重置为自动"
)
TEXT_SEARCH_OFF = "关闭"
TEXT_SEARCH_STD = "标准"
TEXT_SEARCH_DEEP = "深度"
TEXT_THINK_ON = "开启"
TEXT_THINK_OFF = "关闭"
TEXT_REASON_AUTO = "自动"
TEXT_MODELS_LABEL = "可用模型:"
TEXT_CURRENT_SETTINGS = "当前设置"
TEXT_MODEL = "模型"
TEXT_DEEPSEARCH = "深度搜索"
TEXT_REASON_INTENSITY = "推理强度"
TEXT_THINK_DISPLAY = "思考过程显示"
TEXT_PROMPT_LABEL = "提示词"
TEXT_ADMIN_ONLY = "\u26a0 此命令仅管理员可用"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("grok-tg-bot")

# Per-user lock to prevent concurrent requests
_user_locks: dict = {}


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _is_admin(user_id: int) -> bool:
    return user_id in config.TG_ADMIN_IDS


# ============================================================
# Bot & Dispatcher
# ============================================================

bot = Bot(
    token=config.TG_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()


# ============================================================
# Core chat handler (shared logic)
# ============================================================

async def _handle_chat(message: Message, question: str):
    """Core streaming chat logic shared between private and group handlers."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    lock = _get_lock(user_id)

    if lock.locked():
        await message.reply(TEXT_PROCESSING)
        return

    async with lock:
        session = get_session(chat_id, user_id, config.GROK_MODEL)
        session.add_message("user", question)

        bot_msg = await message.reply(f"{EMOJI_HOURGLASS} {TEXT_THINKING}")

        full_content = ""
        full_reasoning = ""
        all_annotations = []
        all_search_sources = []
        finish_reason = None
        model_used = ""

        last_update_time = time.monotonic()
        chunk_buffer = ""

        try:
            async for chunk in stream_chat(
                messages=session.get_messages(),
                model=session.model or None,
                deepsearch=session.deepsearch or None,
                reasoning_effort=session.reasoning_effort or None,
            ):
                if chunk.content:
                    full_content += chunk.content
                    chunk_buffer += chunk.content

                if chunk.reasoning_content:
                    full_reasoning += chunk.reasoning_content

                if chunk.annotations:
                    all_annotations = chunk.annotations

                if chunk.search_sources:
                    all_search_sources = chunk.search_sources

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

                if chunk.model:
                    model_used = chunk.model

                # Throttled message editing
                now = time.monotonic()
                if (
                    now - last_update_time >= config.STREAM_UPDATE_INTERVAL
                    and len(chunk_buffer) >= config.STREAM_MIN_CHUNKS
                ):
                    try:
                        rendered = render_full_response(
                            content=full_content,
                            reasoning=full_reasoning if config.ENABLE_THINKING_DISPLAY else "",
                            annotations=all_annotations,
                            search_sources=all_search_sources,
                            show_thinking=session.show_thinking,
                        )
                        display = split_long_message(rendered)[0]
                        await bot_msg.edit_text(display)
                    except TelegramBadRequest:
                        pass
                    except Exception:
                        pass

                    last_update_time = now
                    chunk_buffer = ""

            # ---- Final render ----
            if full_content:
                session.add_message("assistant", full_content)

                cleaned_content, image_urls = extract_image_urls(full_content)

                rendered = render_full_response(
                    content=cleaned_content,
                    reasoning=full_reasoning if config.ENABLE_THINKING_DISPLAY else "",
                    annotations=all_annotations,
                    search_sources=all_search_sources,
                    show_thinking=session.show_thinking,
                )

                # Send images separately
                if image_urls:
                    for url in image_urls[:4]:
                        try:
                            await bot.send_photo(chat_id, url)
                        except Exception as e:
                            logger.warning(f"Failed to send image {url}: {e}")

                # Send text in chunks
                chunks = split_long_message(rendered)
                if chunks:
                    try:
                        await bot_msg.edit_text(chunks[0])
                    except TelegramBadRequest:
                        pass
                    except Exception:
                        await bot_msg.delete()
                        await message.reply(chunks[0])

                    for chunk_text in chunks[1:]:
                        await bot.send_message(chat_id, chunk_text)
                        await asyncio.sleep(0.3)
            else:
                try:
                    await bot_msg.edit_text(EMOJI_CHECK)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            error_text = f"{EMOJI_CROSS} 请求失败: {str(e)[:500]}"
            try:
                await bot_msg.edit_text(error_text)
            except Exception:
                await message.reply(error_text)
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()


# ============================================================
# Command Handlers
# ============================================================

@router.message(Command("new"))
async def cmd_new(message: Message):
    """Clear conversation history: /new"""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.clear_history()
    await message.reply(TEXT_CLEARED)


@router.message(Command("img"))
async def cmd_image(message: Message, command: CommandObject):
    """Generate image: /img <prompt>"""
    if not config.ENABLE_IMAGE_GENERATION:
        await message.reply(f"{EMOJI_CROSS} 图片生成功能已禁用")
        return

    prompt = command.args
    if not prompt:
        await message.reply(TEXT_IMG_USAGE)
        return

    wait_msg = await message.reply(TEXT_IMG_GEN)

    try:
        result = await generate_image(prompt)
        images = result.get("data", [])
        if not images:
            await wait_msg.edit_text(TEXT_IMG_FAIL)
            return

        for img in images:
            url = img.get("url", "")
            if url:
                caption = f"{EMOJI_ART} {prompt[:100]}"
                await bot.send_photo(message.chat.id, url, caption=caption)

        await wait_msg.delete()
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await wait_msg.edit_text(f"{EMOJI_CROSS} 图片生成失败: {e}")


@router.message(Command("models"))
async def cmd_models(message: Message):
    """List available models."""
    try:
        models = await list_models()
        lines = [f"<b>{TEXT_MODELS_LABEL}</b>"]
        for m in models[:30]:
            mid = m.get("id", "?")
            lines.append(f"\u2022 <code>{mid}</code>")
        await message.reply("\n".join(lines))
    except Exception as e:
        await message.reply(f"{TEXT_MODELS_FAIL}: {e}")


@router.message(Command("setmodel"))
async def cmd_set_model(message: Message, command: CommandObject):
    """Set model (admin only): /setmodel grok-4.20-0309"""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.reply(TEXT_ADMIN_ONLY)
        return

    model = command.args
    if not model:
        await message.reply(TEXT_SETMODEL_USAGE)
        return

    model = model.strip()
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.model = model
    await message.reply(f"{EMOJI_CHECK} 模型已切换为: <code>{model}</code>")


@router.message(Command("model"))
async def cmd_model_info(message: Message):
    """Show current model settings."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    ds_label = session.deepsearch or TEXT_SEARCH_OFF
    ri_label = session.reasoning_effort or TEXT_REASON_AUTO
    think_label = TEXT_THINK_ON if session.show_thinking else TEXT_THINK_OFF
    prompt_display = session.get_prompt()
    if len(prompt_display) > 60:
        prompt_display = prompt_display[:60] + "..."
    info = (
        f"<b>{TEXT_CURRENT_SETTINGS}</b>\n"
        f"\u2022 {TEXT_MODEL}: <code>{session.model or config.GROK_MODEL}</code>\n"
        f"\u2022 {TEXT_DEEPSEARCH}: <code>{ds_label}</code>\n"
        f"\u2022 {TEXT_REASON_INTENSITY}: <code>{ri_label}</code>\n"
        f"\u2022 {TEXT_THINK_DISPLAY}: {think_label}\n"
        f"\u2022 {TEXT_PROMPT_LABEL}: <code>{prompt_display}</code>"
    )
    await message.reply(info)


@router.message(Command("search"))
async def cmd_search_toggle(message: Message):
    """Toggle deep search: off -> default -> deeper -> off"""
    if not config.ENABLE_DEEP_SEARCH:
        await message.reply(f"{EMOJI_CROSS} 深度搜索功能已禁用")
        return

    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    cycle = {"": "default", "default": "deeper", "deeper": ""}
    next_val = cycle.get(session.deepsearch, "")
    session.deepsearch = next_val
    label_map = {"": TEXT_SEARCH_OFF, "default": TEXT_SEARCH_STD, "deeper": TEXT_SEARCH_DEEP}
    label = label_map.get(next_val, next_val)
    await message.reply(f"{EMOJI_SEARCH} {TEXT_DEEPSEARCH}: <b>{label}</b>")


@router.message(Command("reason"))
async def cmd_reason(message: Message, command: CommandObject):
    """Set reasoning effort: /reason high"""
    effort = (command.args or "").strip().lower()
    valid = {"none", "minimal", "low", "medium", "high", "xhigh", ""}
    if effort not in valid:
        await message.reply(TEXT_REASON_INVALID)
        return

    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.reasoning_effort = effort
    label = effort or TEXT_REASON_AUTO
    await message.reply(f"{EMOJI_THINKING} {TEXT_REASON_INTENSITY}: <b>{label}</b>")


@router.message(Command("thinking"))
async def cmd_thinking_toggle(message: Message):
    """Toggle thinking process display."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.show_thinking = not session.show_thinking
    state = TEXT_THINK_ON if session.show_thinking else TEXT_THINK_OFF
    await message.reply(f"{EMOJI_THINKING} {TEXT_THINK_DISPLAY}: <b>{state}</b>")


# ============================================================
# Prompt system
# ============================================================

@router.message(Command("prompt"))
async def cmd_prompt(message: Message, command: CommandObject):
    """Prompt system: /prompt, /prompt reset, /prompt list, /prompt set <name>, /prompt <text>"""
    user_id = message.from_user.id if message.from_user else 0

    # Admin check for setting prompts
    if not _is_admin(user_id):
        await message.reply(TEXT_ADMIN_ONLY)
        return

    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    args = (command.args or "").strip()

    # /prompt (no args) — show current prompt
    if not args:
        current = session.get_prompt()
        await message.reply(
            f"{EMOJI_PROMPT} <b>当前提示词:</b>\n<code>{current}</code>"
        )
        return

    # /prompt reset — reset to default
    if args.lower() == "reset":
        session.reset_prompt()
        default = session.get_prompt()
        await message.reply(
            f"{EMOJI_CHECK} 提示词已重置为默认:\n<code>{default}</code>"
        )
        return

    # /prompt list — list presets
    if args.lower() == "list":
        lines = [f"{EMOJI_PROMPT} <b>内置预设提示词:</b>"]
        for name, text in PROMPT_PRESETS.items():
            display = text if len(text) <= 50 else text[:50] + "..."
            lines.append(f"\u2022 <b>{name}</b>: {display}")
        lines.append("\n使用 /prompt set <预设名> 来选择预设")
        await message.reply("\n".join(lines))
        return

    # /prompt set <name> — use preset
    if args.lower().startswith("set "):
        preset_name = args[4:].strip().lower()
        if preset_name not in PROMPT_PRESETS:
            available = ", ".join(PROMPT_PRESETS.keys())
            await message.reply(
                f"{EMOJI_CROSS} 未找到预设: <code>{preset_name}</code>\n"
                f"可用预设: {available}"
            )
            return
        session.set_prompt(PROMPT_PRESETS[preset_name])
        await message.reply(
            f"{EMOJI_CHECK} 提示词已设为预设 <b>{preset_name}</b>:\n"
            f"<code>{PROMPT_PRESETS[preset_name]}</code>"
        )
        return

    # /prompt <text> — set custom prompt
    session.set_prompt(args)
    await message.reply(
        f"{EMOJI_CHECK} 提示词已设置:\n<code>{args}</code>"
    )


# ============================================================
# Help
# ============================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Show help message."""
    help_text = (
        f"<b>{EMOJI_ROBOT} Grok Bot 帮助</b>\n\n"
        f"<b>基本对话</b>\n"
        f"\u2022 私聊直接发消息即可\n"
        f"\u2022 群组: /Grok <问题> 或 @bot\n"
        f"\u2022 /new \u2014 清除对话历史\n\n"
        f"<b>提示词系统</b>\n"
        f"\u2022 /prompt \u2014 查看当前提示词\n"
        f"\u2022 /prompt <提示词> \u2014 设置自定义提示词\n"
        f"\u2022 /prompt reset \u2014 重置为默认提示词\n"
        f"\u2022 /prompt list \u2014 列出内置预设\n"
        f"\u2022 /prompt set <预设名> \u2014 使用内置预设\n\n"
        f"<b>模型设置</b>\n"
        f"\u2022 /models \u2014 查看可用模型\n"
        f"\u2022 /setmodel <id> \u2014 切换模型 (管理员)\n"
        f"\u2022 /model \u2014 查看当前设置\n\n"
        f"<b>功能开关</b>\n"
        f"\u2022 /search \u2014 切换深度搜索 (关闭/标准/深度)\n"
        f"\u2022 /reason <level> \u2014 设置推理强度\n"
        f"  可选: none, minimal, low, medium, high, xhigh\n"
        f"\u2022 /thinking \u2014 开/关思考过程显示\n\n"
        f"<b>图片生成</b>\n"
        f"\u2022 /img <描述> \u2014 生成图片"
    )
    await message.reply(help_text)


# ============================================================
# Group chat: /Grok command
# ============================================================

@router.message(Command("grok"))
async def cmd_grok_group(message: Message, command: CommandObject):
    """Group trigger: /Grok <question>"""
    question = command.args
    if not question:
        await message.reply("用法: /Grok <问题>\n例: /Grok 解释一下量子计算")
        return
    await _handle_chat(message, question.strip())


# ============================================================
# Private chat: all text messages are direct chat
# ============================================================

@router.message(F.text, F.chat.type == "private")
async def handle_private_message(message: Message):
    """In private chat, all text messages go directly to AI."""
    await _handle_chat(message, message.text)


# ============================================================
# Group chat: @bot_username mention
# ============================================================

@router.message(F.text, F.chat.type.in_({"group", "supergroup"}))
async def handle_group_mention(message: Message):
    """In groups, respond when bot is mentioned via @bot_username."""
    if not message.text:
        return

    # Check if bot is mentioned in the text
    me = await bot.get_me()
    username = me.username
    mention = f"@{username}"

    if mention in message.text:
        # Remove the mention from the text
        question = message.text.replace(mention, "").strip()
        if not question:
            await message.reply("你好！有什么可以帮你的？")
            return
        await _handle_chat(message, question)
    # Otherwise ignore non-command messages in groups


# ============================================================
# Startup
# ============================================================

async def main():
    if not config.TG_BOT_TOKEN:
        logger.error("TG_BOT_TOKEN must be set in .env!")
        sys.exit(1)

    logger.info("Starting Grok Telegram Bot (aiogram 3.x)...")
    logger.info(f"API: {config.GROK_API_BASE}")
    logger.info(f"Model: {config.GROK_MODEL}")
    logger.info(f"Admins: {config.TG_ADMIN_IDS}")

    # Register router
    dp.include_router(router)

    # Start polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
