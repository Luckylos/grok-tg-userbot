"""User session management - per-user conversation history + settings + prompt system."""

from dataclasses import dataclass, field
from bot.config import config

MAX_HISTORY = config.MAX_HISTORY

# Built-in prompt presets
PROMPT_PRESETS: dict[str, str] = {
    "default": "你是一个有用的AI助手。",
    "translator": "你是一个专业翻译，将用户输入翻译为目标语言。用户说'翻译为XX'时，后续内容翻译为XX语言。",
    "coder": "你是一个资深程序员，擅长代码审查和编程。回答时优先给出可运行的代码示例。",
    "writer": "你是一个创意写作助手，帮助用户进行文案、故事、诗歌等创作。",
    "analyst": "你是一个数据分析专家，擅长解读数据和提供洞察。",
}


@dataclass
class UserSession:
    chat_id: int
    user_id: int
    model: str = ""
    deepsearch: str = ""  # "" | "default" | "deeper"
    reasoning_effort: str = ""  # "" | "none".."xhigh"
    show_thinking: bool = True
    system_prompt: str = ""
    messages: list[dict] = field(default_factory=list)

    def _ensure_system_prompt(self):
        """Ensure system prompt is at the head of messages list."""
        prompt = self.system_prompt or config.DEFAULT_SYSTEM_PROMPT
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = prompt
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_HISTORY:
            # Always keep the system prompt at index 0
            if self.messages and self.messages[0]["role"] == "system":
                self.messages = [self.messages[0]] + self.messages[-(MAX_HISTORY - 1):]
            else:
                self.messages = self.messages[-MAX_HISTORY:]

    def clear_history(self):
        """Clear conversation history but preserve system prompt."""
        self.messages.clear()

    def get_messages(self) -> list[dict]:
        """Get messages with system prompt ensured at the head."""
        self._ensure_system_prompt()
        return list(self.messages)

    def set_prompt(self, prompt: str):
        """Set custom system prompt."""
        self.system_prompt = prompt
        self._ensure_system_prompt()

    def reset_prompt(self):
        """Reset to default system prompt."""
        self.system_prompt = ""
        self._ensure_system_prompt()

    def get_prompt(self) -> str:
        """Get current effective system prompt."""
        return self.system_prompt or config.DEFAULT_SYSTEM_PROMPT


# Global session store: (chat_id, user_id) -> UserSession
_sessions: dict[tuple[int, int], UserSession] = {}


def get_session(chat_id: int, user_id: int, default_model: str = "") -> UserSession:
    key = (chat_id, user_id)
    if key not in _sessions:
        _sessions[key] = UserSession(chat_id=chat_id, user_id=user_id, model=default_model)
    return _sessions[key]
