# Bot Interactivity Enhancement Design

## Overview

Add rich interactive menus, FSM-based admin flows, call history browser, and door management UI to the Domonap Telegram bot using aiogram 3.x capabilities.

## Architecture

### Navigation

Single-message "dashboard" pattern: all sections edit the same message (`edit_text`/`edit_reply_markup`) instead of sending new ones. `/start` creates/updates the main menu.

### Callback Data Format

| Prefix | Pattern | Description |
|---|---|---|
| `m:main` | fixed | Main menu |
| `d:p:{page}` | paginated | Door list page |
| `d:det:{id}` | by id | Door detail |
| `d:open:{id}` | by id | Open door |
| `c:p:{page}` | paginated | Call list page |
| `c:f:{filter}` | filter | Filter: all/missed |
| `c:det:{id}` | by id | Call detail |
| `a:panel` | fixed | Admin panel |
| `a:users` | fixed | User management |
| `a:add` | fixed | Trigger add-user FSM |
| `a:rm:{uid}` | by uid | Remove user button |
| `nav:back` | fixed | Navigate back |

### File Structure

```
src/domonap_bot/telegram/
  bot.py            — register new routers
  menu.py           — (NEW) main menu, navigation dispatch
  doors.py          — (NEW) door list, detail, open
  calls.py          — (NEW) call log browser, filters
  admin.py          — (NEW) admin panel, user management
  fsm.py            — (NEW) FSM state definitions
  handlers.py       — strip: keep only /auth, /code, /logout
  keyboards.py      — add builders for all new keyboards
  access.py         — unchanged
  call_watcher.py   — unchanged
```

### Storage

User access rights stored in SQLite alongside existing token data. New key-value rows:
- `access:allowed:{telegram_id}` = `1`
- `access:admin:{telegram_id}` = `1`

New storage methods on `SqliteStorage`: `set_user_allowed`, `is_user_allowed`, `set_user_admin`, `is_user_admin`, `list_allowed_users`, `remove_user`.

### FSM Scenarios

1. **Add user**: admin clicks ➕ → state: waiting for TG user ID → validates → saves → back to user list
2. **Remove user**: admin clicks ❌ on user → confirmation → removes → back to user list

## Component Details

### Dashboard Message Tracking

Each user's "dashboard" message is tracked via a dict: `user_dashboard: dict[int, int]` mapping `user_id → message_id`. All menu/callbacks call `_render(message_or_callback, text, kb)` which:
- If message_or_callback has `message_id` → `edit_text()` + `edit_reply_markup()`
- If callback → `callback.message.edit_text()` + `callback.answer()`
- Updates the tracked message_id on first creation

### CooldownManager

Extract `CooldownManager` from `handlers.py` into its own module or pass as shared instance. All door open and call answer/reject callbacks use the same instance.

### Main Menu (`menu.py`)

Handler `cmd_start` creates/edits dashboard message with:
- Status line (auth ✅/❌, door count, recent call count)
- Buttons: 🚪 Doors, 📞 Calls, ⚙️ Admin, ℹ️ Status

Callback `m:main` from any screen returns here.

### Doors (`doors.py`)

**List** (callback `d:p:0`):
- Calls `get_doors()`, renders paginated list (10 per page)
- Edit message with text + inline keyboard rows per door

**Detail** (callback `d:det:{id}`):
- Shows door name, PIN (masked), video availability
- Actions: 🔓 Open, 📹 Video (URL), ◀️ Back

**Open** (callback `d:open:{id}`):
- Stateless, uses existing `client.open_door()` and `CooldownManager`
- Shows result, back button

### Calls (`calls.py`)

**List** (callback `c:p:0`):
- Calls `get_call_logs(per_page=20, missed_calls=bool)`
- Filter toggle: `c:f:all` → `missed_calls=False`, `c:f:missed` → `missed_calls=True`
- Stateful filter per user via dict `user_call_filter: dict[int, bool]` default `False`
- Each entry: door name, time, status icon (✅/❌)

**Detail** (callback `c:det:{call_id}`):
- Shows door, time, status, photo (send_photo if available)
- Actions: 📞 Answer, 🔴 Reject (stateless callbacks from existing handlers)
- Actions: 🔓 Open door from call, 📹 Video

### Admin (`admin.py`)

**Panel** (callback `a:panel`):
- Auth status, user count
- Buttons: 👥 Users, 🔑 /auth, 🚪 Logout, ◀️ Back

**User list** (callback `a:users`):
- List of allowed users with ❌ remove button each
- ➕ Add user button

**FSM add user**:
1. Admin clicks ➕ → `AdminStates.waiting_user_id`
2. Bot asks: "Send user Telegram ID"
3. Admin sends number → bot validates (positive int) → saves to storage → success message
4. Returns to user list

## Migration

- Existing `AccessControl` reads from settings (env vars) at startup
- New storage methods will be checked first (runtime), env vars as fallback
- Admin panel uses storage for mutations: any user in `allowed_telegram_user_ids` or in storage is allowed
- No schema migration needed — storage is key-value

## Future (out of scope)

- Door rename/notes
- Per-user notification preferences
- Call summary digests
- Multi-language support
