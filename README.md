# Domonap Telegram Bot

Telegram bot for controlling Domonap intercom. Works standalone — no Home Assistant required.

## Quick start

1. Clone and enter the directory:

   ```bash
   git clone <repo-url> domonap-telegram-bot
   cd domonap-telegram-bot
   ```

2. Create `.env` from the example:

   ```bash
   cp .env.example .env
   ```

3. Fill in `.env`:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | **Required.** Bot token from @BotFather |
| `ALLOWED_TELEGRAM_USER_IDS` | **Required.** Comma-separated Telegram user IDs allowed to use the bot |
| `ADMIN_TELEGRAM_USER_IDS` | Comma-separated admin Telegram user IDs; every admin must also be allowed |
| `DOMONAP_PHONE` | Your Domonap account phone number |
| `DOMONAP_REGISTER_DEVICE_TOKEN` | Call `UpdateDeviceToken` after SMS authorization. Default: `false` to preserve official-app push routing |
| `STORAGE_PATH` | Path to SQLite database file (default: `data/storage.db`) |
| `STORAGE_ENCRYPTION_KEY` | **Required.** Fernet key used to encrypt the persisted Domonap session |
| `LOG_LEVEL` | Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO) |
| `CALL_WATCHER_ENABLED` | Enable incoming call notifications (default: true) |

Generate the storage key once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store that value in `STORAGE_ENCRYPTION_KEY`. Keep the key outside the repository and separately from database backups. Losing the key makes an encrypted saved Domonap session unreadable; using a different key causes startup to fail closed rather than silently discarding the session.

> ⚠️ **Fail-closed access:** `ALLOWED_TELEGRAM_USER_IDS` must contain at least one
> Telegram user ID. If it is empty, the application refuses to start; an empty list
> never enables public/open access.

> **ACL precedence:** IDs from `ALLOWED_TELEGRAM_USER_IDS` are a bootstrap floor and are
> unioned with users persisted in SQLite. Likewise, configured admins are re-applied on every
> restart after the admin-subset validation. Removing an env-configured user/admin through the
> running admin UI affects the current process/storage, but that identity returns after restart.
> To revoke it permanently, remove it from `.env` as well. Users that exist only in SQLite stay
> persisted until explicitly removed through the admin UI.

> **Admin invariant:** each ID in `ADMIN_TELEGRAM_USER_IDS` must also be present in
> the effective allowed-user set. Runtime user/admin changes made through the admin UI
> are persisted in SQLite.

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
| `/status` | allowed | Authentication status; phone number is masked |
| `/doors` | allowed | List available doors |
| `/open` | allowed | Open a door; a single door auto-opens, multiple doors show a selection keyboard |
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

- **Door list** — tap a door to see details
- **Door detail** — shows door info:
  - **🔓 Open** — opens the door (cooldown-limited)
  - **📹 Video** — opens video stream URL (if available)

### Calls

- **Call list** — server-aware paginated call log with All/Missed filter
- **Call detail** — shows caller info, photo and video when available
  - **📞 Answer** — answer the call
  - **🔴 Reject** — end call
  - **🔓 Open door** — open the linked door
  - **📹 Video** — open video stream URL

### Admin panel

- **👥 Users** → user management
  - add a regular user
  - grant admin rights to an existing allowed user
  - remove a user with double confirmation
  - the last active administrator cannot be removed
- **🔑 /auth** — request SMS code from Domonap
- **🚪 /logout** — clear the Domonap session

Authorization uses Domonap's SMS-based flow:

1. Set `DOMONAP_PHONE` and an allowed admin ID in `.env`.
2. Send `/auth` to the bot. An SMS code is sent to your phone; the number is masked in responses and logs.
3. Send `/code <sms_code>`. The message containing the code is automatically deleted when possible.
4. Use `/status` to verify the connection.

Domonap session values are stored in SQLite (`data/storage.db` by default) and encrypted with authenticated Fernet encryption using `STORAGE_ENCRYPTION_KEY`. Existing plaintext session fields from older versions are transparently encrypted on the first successful startup with a configured key. ACL records are not secrets and remain ordinary SQLite values. Use `/logout` to clear the persisted Domonap session.

> ⚠️ SMS codes and tokens are not intentionally written by the bot to application logs.
> `LOG_LEVEL=DEBUG` enables debug output for application code, while sensitive third-party
> namespaces (`aiosqlite`, Telegram and HTTP clients) stay at INFO or higher so SQL parameters
> and transport internals are not exposed through dependency-level DEBUG logging.

## Incoming Call Notifications

When `CALL_WATCHER_ENABLED=true` (default), the bot monitors incoming calls and sends notifications to the current runtime allow-list:

- door name/address when available;
- call time;
- photo/preview when available;
- **Open** button;
- **Video** button when a stream URL is available.

How it works:

1. A real SignalR WebSocket connection to the Domonap Notification Hub is the primary source.
2. If the SignalR session fails or ends, the watcher temporarily falls back to call-log polling and then reconnects.
3. Call IDs are deduplicated using a bounded ordered cache.
4. Door metadata is refreshed periodically and immediately when an unknown `doorId` appears.

Disable with `CALL_WATCHER_ENABLED=false` in `.env`.
