# Grok TG UserBot

Grok AI UserBot for Telegram groups — trigger with `/Grok` in any group.

## Features

- **Group Trigger**: `/Grok <question>` in any group chat
- **Streaming Response**: Real-time streaming with edit-in-place updates
- **Multi-turn Conversation**: Per-user per-chat session with history
- **Image Generation**: `/img <prompt>` to generate images
- **Deep Search**: Toggle with `/search` (off/standard/deep)
- **Reasoning Control**: `/reason <level>` (none~xhigh)
- **Thinking Display**: `/thinking` toggle reasoning visibility
- **Model Switching**: `/models` list, `/setmodel <id>` switch
- **Admin DM**: Admins can also use in private messages

## Architecture

Uses **Pyrogram** (MTProto User API) instead of Bot API, because:
- No need for Bot Token — uses your own Telegram account
- Can listen to all messages in groups (no @mention required)
- `/Grok` command works naturally in any group

## Setup

### 1. Get Telegram API credentials

Go to https://my.telegram.org/apps and create an app to get:
- `api_id` (integer)
- `api_hash` (string)

### 2. Generate session string

```bash
pip install pyrogram tgcrypto
python -c "
from pyrogram import Client
app = Client('gen_session', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH')
app.run()
# Login with phone + 2FA, then:
print(app.export_session_string())
"
```

### 3. Configure `.env`

```env
TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1234567890
TG_SESSION_STRING=your_session_string_here
TG_ADMIN_IDS=your_telegram_user_id

GROK_API_BASE=http://grok2api:8000/v1
GROK_API_KEY=
GROK_MODEL=grok-4.20-0309
```

### 4. Deploy with Docker Compose

```bash
docker compose up -d --build
```

## Commands (in group chats)

| Command | Description |
|---------|-------------|
| `/Grok <question>` | Ask Grok a question |
| `/new` | Clear conversation history |
| `/img <prompt>` | Generate image |
| `/models` | List available models |
| `/setmodel <id>` | Switch model |
| `/model` | Show current settings |
| `/search` | Toggle deep search |
| `/reason <level>` | Set reasoning effort |
| `/thinking` | Toggle thinking display |
| `/help` | Show help |

## How It Works

1. User sends `/Grok what is quantum computing?` in a group
2. UserBot detects the command via MTProto listener
3. Forwards the question to grok2api (OpenAI-compatible API)
4. Streams the response back, editing the reply message in real-time
5. Each user has their own conversation session per chat

## Requirements

- Python 3.12+
- Telegram account (for MTProto session)
- Running grok2api instance
