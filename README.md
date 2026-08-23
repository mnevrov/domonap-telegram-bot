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
| `DOMONAP_REGISTER_DEVICE_TOKEN` | Call `UpdateDeviceToken` after SMS authorization. Default: `false` to preserve official-app push routing |
| `STORAGE_PATH` | Path to SQLite database file (default: `data/storage.db`) |
| `LOG_LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO) |
| `CALL_WATCHER_ENABLED` | Enable incoming call notifications (default: true) |

> ⚠️ **`ALLOWED_TELEGRAM_USER_IDS` is required.** The bot refuses to start
> if empty. Set at least one Telegram user ID before deploying,
> especially before exposing the bot token.

> **Official app coexistence:** keep `DOMONAP_REGISTER_DEVICE_TOKEN=false` unless
> you explicitly want this bot authorization to register its device token for push delivery.
> The token is still sent as part of `ConfirmAuthorization`; only the separate
> `UpdateDeviceToken` call is skipped. Incoming-call notifications can use SignalR without
> replacing the official mobile app's push route.

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
| `/start` | allowed | Welcome menu with inline keyboard: Doors, Calls, Admin (if admin) |
| `/status` | allowed | Authentication status: safe info only) |
| `/doors` | allowed | List available doors |
| `/open` | allowed | Open a door (single door auto-opens; multiple doors show selection keyboard |
| `/auth` | admin | Request SMS code from Domonap |
| `/code <code>` | admin | Confirm SMS code and save tokens |
| `/logout` | admin | Clear saved tokens |

## Navigation

The bot uses inline keyboards for all interactions (no complex menu states).

### Main menu (`/start`)

- **🚪 Doors** → paginated door list
- **📞 Calls** → call log with filters (All/Missed)
- **⚙️ Admin** → admin panel (admins only)

### Doors

- **Door list** — tap a door to see details (- **Door detail** — shows door info:
  - **🔓 Open** — opens the door (cooldown-limited)
  - **📹 Video** — opens video stream URL (if available)

### Calls

- **Call list** — paginated call log (All/Missed filter toggle)
- **Call detail** — shows caller info, photo, video
  - **📞 Answer** — answer the call
  - **🔴 Reject** — end call
  - **🔓 Open door** — open door (if linked)
  - **📹 Video** — open video stream URL (if available)

### Admin panel (admins only)

- **👥 Users** → user management
  - **👤 {id}** — user row (admin badge 👑 if if admin)
  - **❌**** — remove user (tap twice to confirm)
  - **➕ Add user** — add Telegram user ID as regular (non-admin) user
  - **⬆ Grant admin** — promote existing user to admin (only shown for non-admins)
- **🔑 /auth** — request SMS code from Domonap
- **🚪 /logout** — clear stored tokens

Authorization uses Domonap's SMS-based flow:

1. Set `DOMONAP_PHONE` and `ADMIN_TELEGRAM_USER_IDS` in `.env`.
2. Send `/auth` to the bot. An SMS code is sent to your phone (number is masked in the response).
3. Send `/code <sms_code>` with the code from SMS. The message containing the code is automatically deleted for security.
4. Use `/status` to verify the connection.

Tokens are stored in the SQLite database (`data/storage.db` by default) and refreshed automatically when needed. Use `/logout` to clear tokens at any time.

> ⚠️ SMS codes and tokens are never written to logs. If you enable `LOG_LEVEL=DEBUG`, be aware that aiogram logs raw message text at this level.

## Incoming Call Notifications

When `CALL_WATCHER_ENABLED=true` (default), the bot monitors incoming calls and sends notifications to all `ALLOWED_TELEGRAM_USER_IDS`:

- Door name/address (if available)
- Call time
- Photo/preview (if available via API)
- **"Открыть" button** — opens the door with one tap
- **"Видео" button** — opens video stream URL (if available)

**How it works:**
1. The bot first tries a real-time connection via SignalR Notification Hub.
2. If SignalR is unavailable, it falls back to polling the call log every 5 seconds.
3. Duplicate call IDs are ignored to prevent repeated notifications.

Disable with `CALL_WATCHER_ENABLED=false` in `.env`.

No sensitive data (tokens, SIP credentials, internal headers) is ever included in notifications.
