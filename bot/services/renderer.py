"""Markdown -> Telegram HTML renderer with Grok-specific content support."""

import re
from html import escape

MSG_LENGTH_LIMIT = 4096
SAFE_CHUNK_LIMIT = 4000

BULLET = "•"
THINKING_EMOJI = "🧠"
SEARCH_EMOJI = "🔍"
LINK_EMOJI = "🔗"


def _escape_html(text: str) -> str:
    return escape(text, quote=True)


def render_markdown_to_html(raw_text: str) -> str:
    """Full pipeline: Markdown -> TG HTML."""
    # Protect code blocks
    code_blocks = []
    counter = [0]

    def _protect_code(m):
        lang = _escape_html(m.group(1).strip())
        code = _escape_html(m.group(2))
        idx = counter[0]
        counter[0] += 1
        if lang:
            code_blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        else:
            code_blocks.append(f"<pre><code>{code}</code></pre>")
        return f"\x00CODEBLOCK{idx}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", _protect_code, raw_text, flags=re.DOTALL)

    # Protect inline code
    inline_codes = []
    ic_counter = [0]

    def _protect_inline(m):
        idx = ic_counter[0]
        ic_counter[0] += 1
        code_text = _escape_html(m.group(1))
        inline_codes.append(f"<code>{code_text}</code>")
        return f"\x00INLINE{idx}\x00"

    text = re.sub(r"`([^`]+)`", _protect_inline, text)

    # Escape remaining HTML
    text = _escape_html(text)

    # Markdown conversions
    text = re.sub(r"^(#{1,3})\s+(.+)$", lambda m: f"<b>{m.group(2).strip()}</b>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Links - extract url safely
    def _link_replacer(m):
        link_url = _escape_html(m.group(2))
        link_text = _escape_html(m.group(1))
        return f'<a href="{link_url}">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_replacer, text)
    text = re.sub(r"^[-*]\s+", f"{BULLET} ", text, flags=re.MULTILINE)

    # Restore protected blocks
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{idx}\x00", block)
    for idx, block in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{idx}\x00", block)
    text = re.sub(r"\x00\w+\d+\x00", "", text)
    return text


def render_thinking(thinking_text: str) -> str:
    escaped = _escape_html(thinking_text.strip())
    if not escaped:
        return ""
    if len(escaped) > 1500:
        escaped = escaped[:1500] + "..."
    return f"<blockquote><i>{THINKING_EMOJI} \u601d\u8003\u8fc7\u7a0b:\n{escaped}</i></blockquote>\n\n"


def render_search_sources(sources: list) -> str:
    if not sources:
        return ""
    lines = [f"{SEARCH_EMOJI} <b>\u641c\u7d22\u5f15\u7528:</b>"]
    for src in sources[:10]:
        title = _escape_html(str(src.get("title", "")))
        url = _escape_html(str(src.get("url", "")))
        if title and url:
            lines.append(f'{BULLET} <a href="{url}">{title}</a>')
        elif url:
            short_url = url[:60]
            lines.append(f'{BULLET} <a href="{url}">{short_url}</a>')
    return "\n".join(lines) + "\n\n"


def render_annotations(annotations: list) -> str:
    if not annotations:
        return ""
    lines = [f"{LINK_EMOJI} <b>\u53c2\u8003\u94fe\u63a5:</b>"]
    for ann in annotations[:10]:
        if ann.get("type") == "url_citation":
            url = _escape_html(str(ann.get("url", "")))
            title = _escape_html(str(ann.get("title", "")))
            if title and url:
                lines.append(f'{BULLET} <a href="{url}">{title}</a>')
            elif url:
                short_url = url[:60]
                lines.append(f'{BULLET} <a href="{url}">{short_url}</a>')
    return "\n".join(lines) + "\n\n"


def render_full_response(
    content: str,
    reasoning: str = "",
    annotations: list | None = None,
    search_sources: list | None = None,
    show_thinking: bool = True,
) -> str:
    parts = []
    if show_thinking and reasoning:
        parts.append(render_thinking(reasoning))
    if search_sources:
        parts.append(render_search_sources(search_sources))
    if annotations:
        parts.append(render_annotations(annotations))
    if content.strip():
        parts.append(render_markdown_to_html(content))
    result = "".join(parts)
    if not result.strip():
        result = "\u2705"
    return result


def split_long_message(text: str, max_len: int = SAFE_CHUNK_LIMIT) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    for para in paragraphs:
        if len(para) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for line in para.split("\n"):
                if len(current) + len(line) + 1 > max_len:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current = current + "\n" + line if current else line
        elif len(current) + len(para) + 2 > max_len:
            chunks.append(current)
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        chunks.append(current)
    final = []
    for chunk in chunks:
        while len(chunk) > max_len:
            cut = chunk.rfind(" ", 0, max_len)
            if cut <= 0:
                cut = max_len
            final.append(chunk[:cut])
            chunk = chunk[cut:].lstrip()
        if chunk:
            final.append(chunk)
    return final if final else [text[:max_len]]


def extract_image_urls(text: str) -> tuple:
    urls = []
    def _extract_img(m):
        urls.append(m.group(2))
        return ""
    cleaned = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _extract_img, text)
    for m in re.finditer(r"(https?://\S+/\S+\.(?:png|jpg|jpeg|webp|gif)(?:\?\S*)?)", text):
        urls.append(m.group(1))
    return cleaned.strip(), urls
