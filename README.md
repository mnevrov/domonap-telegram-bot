# Domonap Telegram Bot

Telegram bot for controlling Domonap intercom. Works standalone — no Home Assistant required.

For backup/restore, storage-key rotation, deployment checks and dependency maintenance, see [OPERATIONS.md](OPERATIONS.md).

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
| `/start` | allowed | Open the main menu |
| `/open` | allowed | Open a door; a single door auto-opens, multiple doors show a selection keyboard |
| `/doors` | allowed | Show available doors with direct open actions |
| `/status` | allowed | Show Domonap connection status; the phone number is masked |
| `/help` | allowed | Show user commands and, for admins, contextual maintenance commands |
| `/auth` | admin | Start SMS authorization and request the code with Telegram ForceReply |
| `/logout` | admin | Clear the saved Domonap session |
| `/code <code>` | admin | Hidden compatibility fallback for submitting an SMS code |
| `/cancel` | admin | Cancel a pending SMS authorization reply flow |

The Telegram private-chat command menu intentionally exposes only `/start`, `/open`, `/doors`, `/status`, and `/help`. Admin maintenance commands stay out of the public command menu.

## Navigation

The main UI uses inline keyboards. SMS authorization is the only temporary stateful interaction: while waiting for a code, the bot uses Telegram ForceReply and a short-lived FSM state.

### Main menu (`/start`)

- **🔓 Открыть дверь** → paginated door list with direct open actions
- **📞 Звонки** → call log with `Все / Пропущенные` filters
- **⚙️ Управление** → admin panel (admins only)

The home screen is rendered from local auth/admin state and does not call Domonap merely to build the menu.

### Doors

- The door list is paginated when necessary.
- Tapping **🔓 <door>** opens that door directly; no intermediate confirmation/detail screen is required.
- If a validated camera URL is available, a **📹** button is shown next to the door.
- After an open attempt, navigation returns to the previous door page rather than losing list position.
- `/open` uses the fast command flow: one configured door is opened immediately; multiple doors show a selection keyboard.

### Calls

- The call list is paginated and supports explicit **Все / Пропущенные** filters.
- Opening a call and returning to the list preserves the current page and filter.
- Historical call details show the door, time and answered/missed status.
- Completed/historical calls do **not** expose `Ответить`/`Сбросить`; only relevant actions such as **🔓 Открыть дверь** and **📹 Камера** are available.

Live incoming-call notifications are interactive cards. Depending on available data they can include **🔓 Открыть**, **📞 Ответить**, **Сбросить**, and **📹 Камера**. Successful actions update the existing Telegram card instead of replacing it with a context-free message; failed actions preserve retryable controls.

### Admin panel

- **👥 Пользователи** → user management
  - create a one-time invite link instead of entering Telegram IDs manually;
  - open a user detail screen;
  - promote an allowed user to administrator;
  - revoke administrator rights with explicit confirmation;
  - remove a user with explicit confirmation;
  - the last active administrator cannot be removed or demoted.
- **🔑 Подключить Domonap** → start the same SMS reply flow as `/auth`.
- **Выйти из Domonap** → clear the persisted Domonap session.

Invite links are bearer credentials: they are one-time, expire after 15 minutes, and are stored only as a SHA-256-derived value plus metadata. An invite is consumed by opening its Telegram `/start invite_<token>` deep link; ordinary `/start` remains fail-closed for unknown users.

## Domonap SMS authorization

Authorization uses a reply-based flow; users no longer need to type `/code <code>` manually:

1. Set `DOMONAP_PHONE` and an allowed admin ID in `.env`.
2. Send `/auth` or use **Управление → Подключить Domonap**.
3. The bot requests an SMS and replies with a ForceReply prompt. The phone number shown in Telegram and logs is masked.
4. Reply to that prompt with the numeric SMS code.
5. The message containing the code is deleted when Telegram permits it. Invalid-format codes keep the reply flow active and prompt again; rejected/expired authorization clears the state and requires a fresh `/auth`.
6. Use `/status` to verify the connection.

`/code <code>` remains supported as a hidden compatibility fallback, and `/cancel` exits a pending reply flow.

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
- **Open**, **Answer**, and **Reject** actions when applicable;
- **Video** button when a safe stream URL is available.

How it works:

1. A real SignalR WebSocket connection to the Domonap Notification Hub is the primary source.
2. If the SignalR session fails or ends, the watcher temporarily falls back to call-log polling and then reconnects.
3. Call IDs are deduplicated using a bounded ordered cache.
4. Door metadata is refreshed periodically and immediately when an unknown `doorId` appears.
5. Incoming Telegram cards preserve their context while successful actions transition individual controls to terminal states.

Disable with `CALL_WATCHER_ENABLED=false` in `.env`.
