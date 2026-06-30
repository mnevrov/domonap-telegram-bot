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
| `ALLOWED_TELEGRAM_USER_IDS` | Comma-separated Telegram user IDs who can open doors (leave empty for open access) |
| `ADMIN_TELEGRAM_USER_IDS` | Comma-separated Telegram user IDs who can manage authorization |
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

| Command | Access | Description |
|---|---|---|
| `/start` | allowed | Welcome message with available commands |
| `/status` | allowed | Authentication status (safe info only) |
| `/doors` | allowed | List available doors |
| `/open` | allowed | Select and open a door (interactive) |
| `/auth` | admin | Request SMS code from Domonap |
| `/code <code>` | admin | Confirm SMS code and save tokens |
| `/logout` | admin | Clear saved tokens |

## Authorization

Authorization uses Domonap's SMS-based flow:

1. Set `DOMONAP_PHONE` and `ADMIN_TELEGRAM_USER_IDS` in `.env`.
2. Send `/auth` to the bot. An SMS code is sent to your phone (number is masked in the response).
3. Send `/code <sms_code>` with the code from SMS. The message containing the code is automatically deleted for security.
4. Use `/status` to verify the connection.

Tokens are stored in the SQLite database (`data/storage.db` by default) and refreshed automatically when needed. Use `/logout` to clear tokens at any time.

> ⚠️ SMS codes and tokens are never written to logs. If you enable `LOG_LEVEL=DEBUG`, be aware that aiogram logs raw message text at this level.
