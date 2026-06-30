# Domonap Telegram Bot

Telegram bot for controlling Domonap intercom. Works standalone — no Home Assistant required.

## Quick start

1. Clone and enter the directory:

   ```bash
   git clone <repo-url> domonap-telegram-bot
   cd domonap-telegram-bot
   ```

2. Create `.env` from example:

   ```bash
   cp .env.example .env
   ```

3. Fill in `.env`:

   | Variable | Description |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
   | `ALLOWED_TELEGRAM_USER_IDS` | Comma-separated Telegram user IDs (leave empty for open access) |
   | `DOMONAP_PHONE` | Your Domonap account phone number |
   | `STORAGE_PATH` | Path to SQLite database file (default: `data/storage.db`) |
   | `LOG_LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO) |

4. Run with Docker:

   ```bash
   docker compose up --build
   ```

   Or without Docker:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m domonap_bot.main
   ```

## Commands

- `/start` — welcome message with available commands
- `/status` — authentication status
- `/doors` — list available doors
- `/open` — select and open a door (interactive)
