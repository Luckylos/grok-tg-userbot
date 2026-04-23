import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram Bot API
    TG_BOT_TOKEN: str = os.getenv("TG_BOT_TOKEN", "")
    TG_ADMIN_IDS: list[int] = [
        int(x.strip())
        for x in os.getenv("TG_ADMIN_IDS", "").split(",")
        if x.strip().isdigit()
    ]

    # Grok API
    GROK_API_BASE: str = os.getenv("GROK_API_BASE", "http://grok2api:8000/v1")
    GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
    GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-4.20-0309")

    # Behavior
    STREAM_UPDATE_INTERVAL: float = float(os.getenv("STREAM_UPDATE_INTERVAL", "0.8"))
    STREAM_MIN_CHUNKS: int = int(os.getenv("STREAM_MIN_CHUNKS", "5"))
    ENABLE_THINKING_DISPLAY: bool = os.getenv("ENABLE_THINKING_DISPLAY", "true").lower() == "true"
    ENABLE_IMAGE_GENERATION: bool = os.getenv("ENABLE_IMAGE_GENERATION", "true").lower() == "true"
    ENABLE_DEEP_SEARCH: bool = os.getenv("ENABLE_DEEP_SEARCH", "false").lower() == "true"
    MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "40"))

    # Default system prompt
    DEFAULT_SYSTEM_PROMPT: str = "你是一个有用的AI助手。"


config = Config()
