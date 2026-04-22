"""User session management - per-user conversation history + settings."""

from dataclasses import dataclass, field

MAX_HISTORY = 40


@dataclass
class UserSession:
    chat_id: int
    user_id: int
    model: str = ""
    deepsearch: str = ""   # "" | "default" | "deeper"
    reasoning_effort: str = ""  # "" | "none".."xhigh"
    show_thinking: bool = True
    messages: list[dict] = field(default_factory=list)

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_HISTORY:
            if self.messages and self.messages[0]["role"] == "system":
                self.messages = [self.messages[0]] + self.messages[-(MAX_HISTORY - 1):]
            else:
                self.messages = self.messages[-MAX_HISTORY:]

    def clear_history(self):
        self.messages.clear()

    def get_messages(self) -> list[dict]:
        return list(self.messages)


# Global session store: (chat_id, user_id) -> UserSession
_sessions: dict[tuple[int, int], UserSession] = {}


def get_session(chat_id: int, user_id: int, default_model: str = "") -> UserSession:
    key = (chat_id, user_id)
    if key not in _sessions:
        _sessions[key] = UserSession(chat_id=chat_id, user_id=user_id, model=default_model)
    return _sessions[key]
