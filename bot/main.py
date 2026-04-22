"""Grok UserBot entry point - Pyrogram MTProto client for group /Grok trigger."""

import asyncio
import logging
import sys
import time

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified, FloodWait

from bot.config import config
from bot.services.grok_api import stream_chat, generate_image, list_models
from bot.services.renderer import (
    render_full_response,
    split_long_message,
    extract_image_urls,
)
from bot.services.session import get_session

# Unicode constants
EMOJI_THINKING = "🧠"
EMOJI_HOURGLASS = "⏳"
EMOJI_TRASH = "🗑"
EMOJI_ART = "🎨"
EMOJI_CROSS = "❌"
EMOJI_CHECK = "✅"
EMOJI_WARN = "⚠"
EMOJI_SEARCH = "🔍"
EMOJI_ROBOT = "🤖"

# Chinese text constants
TEXT_THINKING = "思考中..."
TEXT_PROCESSING = "⚠ 上一个请求还在处理中，请稍等..."
TEXT_USAGE = "用法: /Grok <问题>\n例: /Grok 解释一下量子计算"
TEXT_CLEARED = "🗑 对话已清除，开始新对话"
TEXT_IMG_USAGE = "用法: /img <描述>"
TEXT_IMG_GEN = "🎨 生成图片中..."
TEXT_IMG_FAIL = "❌ 未生成图片"
TEXT_MODELS_FAIL = "❌ 获取模型列表失败"
TEXT_SETMODEL_USAGE = "用法: /setmodel <model_id>"
TEXT_REASON_INVALID = "❌ 无效等级。可选: none, minimal, low, medium, high, xhigh\n用 /reason 重置为自动"
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("grok-userbot")

# Per-user lock to prevent concurrent requests
_user_locks: dict = {}


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


# Initialize Pyrogram Client (MTProto User API)
app = Client(
    "grok_userbot",
    api_id=config.TG_API_ID,
    api_hash=config.TG_API_HASH,
    session_string=config.TG_SESSION_STRING or None,
    workdir="/app/session",
)


def _is_admin(user_id: int) -> bool:
    return user_id in config.TG_ADMIN_IDS


# ============================================================
#  Command Handlers
# ============================================================

@app.on_message(filters.command("Grok") & filters.group)
async def cmd_grok(client: Client, message: Message):
    """Main trigger: /Grok <question> in group chats."""
    # Extract the question after /Grok
    prompt = message.text or ""
    parts = prompt.split(None, 1)
    question = parts[1].strip() if len(parts) > 1 else ""

    if not question:
        await message.reply_text(TEXT_USAGE)
        return

    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    lock = _get_lock(user_id)

    if lock.locked():
        await message.reply_text(TEXT_PROCESSING)
        return

    async with lock:
        session = get_session(chat_id, user_id, config.GROK_MODEL)
        session.add_message("user", question)

        bot_msg = await message.reply_text(f"{EMOJI_HOURGLASS} {TEXT_THINKING}")

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
                    except MessageNotModified:
                        pass
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
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
                        await client.send_photo(chat_id, url)
                    except Exception as e:
                        logger.warning(f"Failed to send image {url}: {e}")

            # Send text in chunks
            chunks = split_long_message(rendered)
            if chunks:
                try:
                    await bot_msg.edit_text(chunks[0])
                except MessageNotModified:
                    pass
                except Exception:
                    await bot_msg.delete()
                    await message.reply_text(chunks[0])

                for chunk_text in chunks[1:]:
                    await client.send_message(chat_id, chunk_text)
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
                await message.reply_text(error_text)
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()


@app.on_message(filters.command("new") & filters.group)
async def cmd_new(client: Client, message: Message):
    """Clear conversation history: /new"""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.clear_history()
    await message.reply_text(TEXT_CLEARED)


@app.on_message(filters.command("img") & filters.group)
async def cmd_image(client: Client, message: Message):
    """Generate image: /img <prompt>"""
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2:
        await message.reply_text(TEXT_IMG_USAGE)
        return
    prompt = parts[1].strip()

    wait_msg = await message.reply_text(TEXT_IMG_GEN)

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
                await client.send_photo(message.chat.id, url, caption=caption)

        await wait_msg.delete()
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await wait_msg.edit_text(f"{EMOJI_CROSS} 图片生成失败: {e}")


@app.on_message(filters.command("models") & filters.group)
async def cmd_models(client: Client, message: Message):
    """List available models."""
    try:
        models = await list_models()
        lines = [f"<b>{TEXT_MODELS_LABEL}</b>"]
        for m in models[:30]:
            mid = m.get("id", "?")
            lines.append(f"\u2022 <code>{mid}</code>")
        await message.reply_text("\n".join(lines))
    except Exception as e:
        await message.reply_text(f"{TEXT_MODELS_FAIL}: {e}")


@app.on_message(filters.command("setmodel") & filters.group)
async def cmd_set_model(client: Client, message: Message):
    """Set model: /setmodel grok-4.20-0309"""
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2:
        await message.reply_text(TEXT_SETMODEL_USAGE)
        return
    model = parts[1].strip()
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.model = model
    await message.reply_text(f"{EMOJI_CHECK} 模型已切换为: <code>{model}</code>")


@app.on_message(filters.command("model") & filters.group)
async def cmd_model_info(client: Client, message: Message):
    """Show current model settings."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    ds_label = session.deepsearch or TEXT_SEARCH_OFF
    ri_label = session.reasoning_effort or TEXT_REASON_AUTO
    think_label = TEXT_THINK_ON if session.show_thinking else TEXT_THINK_OFF
    info = (
        f"<b>{TEXT_CURRENT_SETTINGS}</b>\n"
        f"\u2022 {TEXT_MODEL}: <code>{session.model or config.GROK_MODEL}</code>\n"
        f"\u2022 {TEXT_DEEPSEARCH}: <code>{ds_label}</code>\n"
        f"\u2022 {TEXT_REASON_INTENSITY}: <code>{ri_label}</code>\n"
        f"\u2022 {TEXT_THINK_DISPLAY}: {think_label}"
    )
    await message.reply_text(info)


@app.on_message(filters.command("search") & filters.group)
async def cmd_search_toggle(client: Client, message: Message):
    """Toggle deep search: off -> default -> deeper -> off"""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    cycle = {"": "default", "default": "deeper", "deeper": ""}
    next_val = cycle.get(session.deepsearch, "")
    session.deepsearch = next_val
    label_map = {"": TEXT_SEARCH_OFF, "default": TEXT_SEARCH_STD, "deeper": TEXT_SEARCH_DEEP}
    label = label_map.get(next_val, next_val)
    await message.reply_text(f"{EMOJI_SEARCH} {TEXT_DEEPSEARCH}: <b>{label}</b>")


@app.on_message(filters.command("reason") & filters.group)
async def cmd_reason(client: Client, message: Message):
    """Set reasoning effort: /reason high"""
    parts = (message.text or "").split(None, 1)
    effort = parts[1].strip().lower() if len(parts) > 1 else ""
    valid = {"none", "minimal", "low", "medium", "high", "xhigh", ""}
    if effort not in valid:
        await message.reply_text(TEXT_REASON_INVALID)
        return
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.reasoning_effort = effort
    label = effort or TEXT_REASON_AUTO
    await message.reply_text(f"{EMOJI_THINKING} {TEXT_REASON_INTENSITY}: <b>{label}</b>")


@app.on_message(filters.command("thinking") & filters.group)
async def cmd_thinking_toggle(client: Client, message: Message):
    """Toggle thinking process display."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    session = get_session(chat_id, user_id, config.GROK_MODEL)
    session.show_thinking = not session.show_thinking
    state = TEXT_THINK_ON if session.show_thinking else TEXT_THINK_OFF
    await message.reply_text(f"{EMOJI_THINKING} {TEXT_THINK_DISPLAY}: <b>{state}</b>")


@app.on_message(filters.command("help") & filters.group)
async def cmd_help(client: Client, message: Message):
    """Show help message."""
    help_text = (
        f"<b>{EMOJI_ROBOT} Grok UserBot 帮助</b>\n\n"
        f"<b>基本对话</b>\n"
        f"\u2022 /Grok <问题> \u2014 在群组中提问\n"
        f"\u2022 /new \u2014 清除对话历史\n\n"
        f"<b>模型设置</b>\n"
        f"\u2022 /models \u2014 查看可用模型\n"
        f"\u2022 /setmodel <id> \u2014 切换模型\n"
        f"\u2022 /model \u2014 查看当前设置\n\n"
        f"<b>功能开关</b>\n"
        f"\u2022 /search \u2014 切换深度搜索 (关闭/标准/深度)\n"
        f"\u2022 /reason <level> \u2014 设置推理强度\n"
        f"  可选: none, minimal, low, medium, high, xhigh\n"
        f"\u2022 /thinking \u2014 开/关思考过程显示\n\n"
        f"<b>图片生成</b>\n"
        f"\u2022 /img <描述> \u2014 生成图片\n"
    )
    await message.reply_text(help_text)


# ============================================================
#  Private message support for admins
# ============================================================

@app.on_message(filters.command("Grok") & filters.private)
async def cmd_grok_private(client: Client, message: Message):
    """DM trigger for admins: /Grok <question>"""
    if not _is_admin(message.from_user.id):
        return
    await cmd_grok(client, message)


@app.on_message(filters.private & filters.command("help"))
async def cmd_help_private(client: Client, message: Message):
    if _is_admin(message.from_user.id):
        await cmd_help(client, message)


# ============================================================
#  Startup
# ============================================================

def main():
    if not config.TG_API_ID or not config.TG_API_HASH:
        logger.error("TG_API_ID and TG_API_HASH must be set in .env!")
        sys.exit(1)

    logger.info("Starting Grok UserBot (Pyrogram MTProto)...")
    logger.info(f"API: {config.GROK_API_BASE}")
    logger.info(f"Model: {config.GROK_MODEL}")
    logger.info(f"Trigger: {config.TRIGGER_COMMAND}")
    logger.info(f"Admins: {config.TG_ADMIN_IDS}")

    app.run()


if __name__ == "__main__":
    main()
