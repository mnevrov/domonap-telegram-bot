# Bot Interactivity Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rich interactive menus (dashboard pattern), FSM-based admin flows, call history browser, and paginated door management to the Domonap Telegram bot.

**Architecture:** Multi-file modules under `telegram/` (menu, doors, calls, admin, fsm) with a shared dashboard message-per-user tracking dict. Single `CooldownManager` instance passed to all handlers. User rights stored in SQLite via key-value rows beside existing token data.

**Tech Stack:** Python 3.12, aiogram 3.x, aiosqlite, pytest + pytest-asyncio (unittest.mock / MagicMock / AsyncMock for handler tests)

## Global Constraints

- Line length: 100 (existing ruff config)
- Type hints required (strict mypy mode in pyproject.toml)
- Use `register_handlers(router, client, ...)` pattern (see `handlers.py`)
- No new dependencies beyond existing project requirements
- All storage keys prefixed with `access:allowed:` and `access:admin:`
- Callback data format: short prefixes with colons (`d:p:0`, `c:det:{id}`)
- Dashboard helper `_render` edits message in place; falls back to send if no prior message

---

### Task 1: Storage — user access management

**Files:**
- Modify: `src/domonap_bot/storage/base.py`
- Modify: `src/domonap_bot/storage/sqlite.py`
- Create: `tests/test_user_storage.py`

**Interfaces:**
- Consumes: existing `Storage` abstract base (`set`, `get`, `delete` key-value)
- Produces:
  ```python
  class Storage(ABC):
      async def set_user_allowed(self, telegram_id: int) -> None: ...
      async def is_user_allowed(self, telegram_id: int) -> bool: ...
      async def set_user_admin(self, telegram_id: int) -> None: ...
      async def is_user_admin(self, telegram_id: int) -> bool: ...
      async def list_allowed_users(self) -> list[int]: ...
      async def remove_user(self, telegram_id: int) -> None: ...
  ```
  Concrete `SqliteStorage` implements each via `kv_store` with keys:
  - `access:allowed:{telegram_id}` → `"1"`
  - `access:admin:{telegram_id}` → `"1"`

- [ ] **Step 1: Add abstract methods to Storage base**

```python
# src/domonap_bot/storage/base.py
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def set_user_allowed(self, telegram_id: int) -> None: ...

    @abstractmethod
    async def is_user_allowed(self, telegram_id: int) -> bool: ...

    @abstractmethod
    async def set_user_admin(self, telegram_id: int) -> None: ...

    @abstractmethod
    async def is_user_admin(self, telegram_id: int) -> bool: ...

    @abstractmethod
    async def list_allowed_users(self) -> list[int]: ...

    @abstractmethod
    async def remove_user(self, telegram_id: int) -> None: ...
```

- [ ] **Step 2: Implement in SqliteStorage**

```python
# src/domonap_bot/storage/sqlite.py — add methods

async def set_user_allowed(self, telegram_id: int) -> None:
    await self.set(f"access:allowed:{telegram_id}", "1")

async def is_user_allowed(self, telegram_id: int) -> bool:
    val = await self.get(f"access:allowed:{telegram_id}")
    return val == "1"

async def set_user_admin(self, telegram_id: int) -> None:
    await self.set(f"access:admin:{telegram_id}", "1")

async def is_user_admin(self, telegram_id: int) -> bool:
    val = await self.get(f"access:admin:{telegram_id}")
    return val == "1"

async def list_allowed_users(self) -> list[int]:
    assert self._conn is not None
    cursor = await self._conn.execute(
        "SELECT key FROM kv_store WHERE key LIKE 'access:allowed:%'"
    )
    rows = await cursor.fetchall()
    result: list[int] = []
    for (key,) in rows:
        parts = key.split(":")
        if len(parts) == 3:
            try:
                result.append(int(parts[2]))
            except ValueError:
                continue
    return result

async def remove_user(self, telegram_id: int) -> None:
    await self.delete(f"access:allowed:{telegram_id}")
    await self.delete(f"access:admin:{telegram_id}")
```

- [ ] **Step 3: Write tests for user storage**

```python
# tests/test_user_storage.py
from pathlib import Path

import pytest

from domonap_bot.storage.sqlite import SqliteStorage


@pytest.fixture
async def storage(tmp_path: Path) -> SqliteStorage:
    s = SqliteStorage(tmp_path / "test_users.db")
    await s.initialize()
    return s


async def test_set_and_is_user_allowed(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    assert await storage.is_user_allowed(42) is True


async def test_not_allowed_by_default(storage: SqliteStorage) -> None:
    assert await storage.is_user_allowed(99) is False


async def test_set_user_admin(storage: SqliteStorage) -> None:
    await storage.set_user_admin(42)
    assert await storage.is_user_admin(42) is True
    assert await storage.is_user_admin(99) is False


async def test_list_allowed_users(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(1)
    await storage.set_user_allowed(2)
    assert sorted(await storage.list_allowed_users()) == [1, 2]


async def test_list_allowed_users_empty(storage: SqliteStorage) -> None:
    assert await storage.list_allowed_users() == []


async def test_remove_user(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    await storage.set_user_admin(42)
    await storage.remove_user(42)
    assert await storage.is_user_allowed(42) is False
    assert await storage.is_user_admin(42) is False


async def test_remove_user_does_not_affect_other_users(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    await storage.set_user_allowed(7)
    await storage.remove_user(42)
    assert await storage.is_user_allowed(7) is True
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_user_storage.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_user_storage.py src/domonap_bot/storage/base.py src/domonap_bot/storage/sqlite.py
git commit -m "feat: add user access management to storage layer"
```

---

### Task 2: Extract CooldownManager to shared module

**Files:**
- Create: `src/domonap_bot/telegram/cooldown.py`
- Modify: `src/domonap_bot/telegram/handlers.py` (remove class, import from cooldown)
- Modify: `tests/test_handlers.py` (update import)

**Interfaces:**
- Consumes: `CooldownManager` (moved, same API)
- Produces: `CooldownManager` exported from `domonap_bot.telegram.cooldown`

- [ ] **Step 1: Create cooldown.py with extracted CooldownManager**

```python
# src/domonap_bot/telegram/cooldown.py
from time import monotonic


class CooldownManager:
    def __init__(self, timeout: float = 5.0) -> None:
        self._cooldowns: dict[tuple[int, str], float] = {}
        self._timeout = timeout

    def is_ready(self, user_id: int, action_id: str) -> bool:
        last = self._cooldowns.get((user_id, action_id))
        if last is None:
            return True
        return monotonic() - last >= self._timeout

    def set(self, user_id: int, action_id: str) -> None:
        self._cooldowns[(user_id, action_id)] = monotonic()

    def remaining(self, user_id: int, action_id: str) -> float:
        last = self._cooldowns.get((user_id, action_id))
        if last is None:
            return 0.0
        return max(0.0, self._timeout - (monotonic() - last))

    def clear_expired(self) -> int:
        now = monotonic()
        expired = [k for k, t in self._cooldowns.items() if now - t >= self._timeout]
        for k in expired:
            del self._cooldowns[k]
        return len(expired)
```

- [ ] **Step 2: Update handlers.py to import from cooldown**

Remove the entire `CooldownManager` class from `handlers.py`.

Change `register_handlers` signature to accept `cooldown: CooldownManager` parameter instead of creating it internally:

```python
# src/domonap_bot/telegram/handlers.py — change register_handlers
from domonap_bot.telegram.cooldown import CooldownManager

def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    # Remove: cooldown = CooldownManager()
    # Rest of function unchanged
```

- [ ] **Step 3: Update bot.py to create and pass CooldownManager**

```python
# src/domonap_bot/telegram/bot.py
from domonap_bot.telegram.cooldown import CooldownManager

def build_bot(
    settings: Settings,
    client: DomonapClient,
) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    router = Router()

    access = AccessControl(settings.allowed_telegram_user_ids)
    admin_access = AccessControl(
        settings.admin_telegram_user_ids,
        default_allow=False,
    )
    cooldown = CooldownManager()
    register_handlers(router, client, access, admin_access, cooldown)

    dp.include_router(router)
    return bot, dp
```

- [ ] **Step 4: Update tests — fix import and register_handlers call**

```python
# tests/test_handlers.py — update import
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.handlers import (
    _describe_error,
    _mask_phone,
    register_handlers,
)

# Update _build_callback_handlers
def _build_callback_handlers(client: MagicMock) -> dict[str, object]:
    router = Router()
    access = AccessControl([1])
    admin_access = AccessControl([1], default_allow=False)
    cooldown = CooldownManager()
    register_handlers(router, client, access, admin_access, cooldown)
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_handlers.py -v
```

Expected: all existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/domonap_bot/telegram/cooldown.py src/domonap_bot/telegram/handlers.py src/domonap_bot/telegram/bot.py tests/test_handlers.py
git commit -m "refactor: extract CooldownManager to shared module"
```

---

### Task 3: Keyboard builders

**Files:**
- Modify: `src/domonap_bot/telegram/keyboards.py`

**Interfaces:**
- Consumes: `DoorKey` model, `CallLogEntry` model
- Produces:
  ```python
  def main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup: ...
  def door_list_keyboard(doors: list[DoorKey], page: int, total_pages: int) -> InlineKeyboardMarkup: ...
  def door_detail_keyboard(door: DoorKey) -> InlineKeyboardMarkup: ...
  def call_list_keyboard(entries: list[CallLogEntry], page: int, total_pages: int, filter_all: bool) -> InlineKeyboardMarkup: ...
  def call_detail_keyboard(call_id: str, door_id: str | None, video_url: str | None) -> InlineKeyboardMarkup: ...
  def admin_panel_keyboard() -> InlineKeyboardMarkup: ...
  def user_list_keyboard(users: list[int]) -> InlineKeyboardMarkup: ...
  def back_keyboard(dest: str = "m:main") -> InlineKeyboardMarkup: ...
  ```

- [ ] **Step 1: Write keyboard builders**

```python
# src/domonap_bot/telegram/keyboards.py — replace existing content

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import CallLogEntry, DoorKey


def door_selection_keyboard(doors: list[DoorKey]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d.name, callback_data=f"open:{d.id}")]
        for d in doors
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🚪 Doors", callback_data="d:p:0"),
            InlineKeyboardButton(text="📞 Calls", callback_data="c:p:0"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="⚙️ Admin", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def door_list_keyboard(doors: list[DoorKey], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"🚪 {d.name}", callback_data=f"d:det:{d.id}")]
        for d in doors
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"d:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"d:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Back", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def door_detail_keyboard(door: DoorKey) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔓 Open", callback_data=f"d:open:{door.id}")],
    ]
    if door.http_video_url or door.webrtc_video_url:
        url = door.http_video_url or door.webrtc_video_url
        if url:
            rows.append([InlineKeyboardButton(text="📹 Video", url=url)])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="d:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_list_keyboard(entries: list[CallLogEntry], page: int, total_pages: int, filter_all: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=f"{'📍' if e.door_id else '📞'} {e.caller or e.call_id[:8]} – {e.call_time.strftime('%H:%M') if e.call_time else '??'} {'❌' if not e.answered else '✅'}",
            callback_data=f"c:det:{e.call_id}",
        )]
        for e in entries
    ]
    filter_label = "📋 All" if not filter_all else "📋 Missed"
    filter_data = "c:f:missed" if filter_all else "c:f:all"
    nav: list[InlineKeyboardButton] = [InlineKeyboardButton(text=filter_label, callback_data=filter_data)]
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"c:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"c:p:{page + 1}"))
    if len(nav) > 1:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Back", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_detail_keyboard(call_id: str, door_id: str | None, video_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📞 Answer", callback_data=f"answer:{call_id}"),
            InlineKeyboardButton(text="🔴 Reject", callback_data=f"reject:{call_id}"),
        ],
    ]
    if door_id:
        rows.append([InlineKeyboardButton(text="🔓 Open door", callback_data=f"open:{door_id}")])
    if video_url:
        rows.append([InlineKeyboardButton(text="📹 Video", url=video_url)])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="c:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Users", callback_data="a:users")],
        [InlineKeyboardButton(text="🔑 /auth", callback_data="a:auth")],
        [InlineKeyboardButton(text="🚪 /logout", callback_data="a:logout")],
        [InlineKeyboardButton(text="🏠 Back", callback_data="m:main")],
    ])


def user_list_keyboard(users: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"👤 {uid}  ❌", callback_data=f"a:rm:{uid}")]
        for uid in users
    ]
    rows.append([InlineKeyboardButton(text="➕ Add user", callback_data="a:add")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard(dest: str = "m:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back", callback_data=dest)],
    ])
```

- [ ] **Step 5: Commit**

```bash
git add src/domonap_bot/telegram/keyboards.py
git commit -m "feat: add all keyboard builders for interactive menus"
```

---

### Task 4: FSM states + Admin panel

**Files:**
- Create: `src/domonap_bot/telegram/fsm.py`
- Create: `src/domonap_bot/telegram/admin.py`
- Modify: `src/domonap_bot/telegram/bot.py` (register admin router)
- Create: `tests/test_admin.py`

**Interfaces:**
- Consumes: `SqliteStorage` (for user access mutations), `DomonapClient` (for auth/logout), `AccessControl`, `CooldownManager`
- Produces:
  - `AdminStates` — FSM state group
  - `register_admin_handlers(router, client, storage, admin_access, cooldown)` — registers all admin callbacks + FSM handlers

- [ ] **Step 1: Create fsm.py**

```python
# src/domonap_bot/telegram/fsm.py
from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_user_id = State()
```

- [ ] **Step 2: Create admin.py**

```python
# src/domonap_bot/telegram/admin.py
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.fsm import AdminStates
from domonap_bot.telegram.keyboards import admin_panel_keyboard, user_list_keyboard, back_keyboard

logger = logging.getLogger(__name__)


def register_admin_handlers(
    router: Router,
    client: DomonapClient,
    storage: SqliteStorage,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    async def _admin_panel(event: Message | CallbackQuery) -> None:
        has_token = client.access_token or client.refresh_token
        users = await storage.list_allowed_users()
        parts = [
            "⚙️ Admin Panel",
            "─────────────────────",
            f"Auth: {'✅' if has_token else '❌'}",
            f"Users: {len(users)}",
            "",
        ]
        text = "\n".join(parts)
        kb = admin_panel_keyboard()
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, reply_markup=kb)
            await event.answer()
        else:
            await event.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "a:panel")
    @admin_access.require_access
    async def callback_admin_panel(callback: CallbackQuery) -> None:
        await _admin_panel(callback)

    @router.callback_query(F.data == "a:users")
    @admin_access.require_access
    async def callback_user_list(callback: CallbackQuery) -> None:
        users = await storage.list_allowed_users()
        if not users:
            text = "👥 Users\n─────────────────────\nNo users configured."
        else:
            text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {uid}" for uid in users)
        await callback.message.edit_text(text, reply_markup=user_list_keyboard(users))
        await callback.answer()

    @router.callback_query(F.data == "a:add")
    @admin_access.require_access
    async def callback_add_user_start(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.message.edit_text(
            "Send me the Telegram user ID to add:\n\n"
            "Example: `123456789`\n\n"
            "Type /cancel to abort.",
        )
        await state.set_state(AdminStates.waiting_user_id)
        await callback.answer()

    @router.message(AdminStates.waiting_user_id, F.text)
    @admin_access.require_access
    async def fsm_add_user_id(message: Message, state: FSMContext) -> None:
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("Invalid ID. Please send a numeric Telegram user ID.")
            return

        uid = int(text)
        await storage.set_user_allowed(uid)
        await message.answer(f"✅ User {uid} added.")
        await state.clear()

        users = await storage.list_allowed_users()
        text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {u}" for u in users) if users else "No users."
        await message.answer(text, reply_markup=user_list_keyboard(users))

    @router.message(AdminStates.waiting_user_id, F.text == "/cancel")
    async def fsm_cancel_add(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=back_keyboard("a:panel"))

    @router.callback_query(F.data.startswith("a:rm:"))
    @admin_access.require_access
    async def callback_remove_user(callback: CallbackQuery) -> None:
        uid_str = callback.data.removeprefix("a:rm:")
        try:
            uid = int(uid_str)
        except ValueError:
            await callback.answer("Invalid user ID.", show_alert=True)
            return

        await storage.remove_user(uid)
        await callback.answer(f"User {uid} removed.")

        users = await storage.list_allowed_users()
        text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {u}" for u in users) if users else "No users."
        await callback.message.edit_text(text, reply_markup=user_list_keyboard(users))

    @router.callback_query(F.data == "a:auth")
    @admin_access.require_access
    async def callback_admin_auth(callback: CallbackQuery) -> None:
        phone = client.phone
        if not phone:
            await callback.message.edit_text("No phone configured.", reply_markup=back_keyboard("a:panel"))
            await callback.answer()
            return
        success = await client.login(phone)
        if success:
            masked = "".join(c for c in phone if c.isdigit())
            masked = masked[:3] + "***" + masked[-2:] if len(masked) >= 4 else masked
            if phone.startswith("+"):
                masked = f"+{masked}"
            await callback.message.edit_text(
                f"SMS sent to {masked}. Use /code <code> to complete.",
                reply_markup=back_keyboard("a:panel"),
            )
        else:
            await callback.message.edit_text("Failed to request SMS.", reply_markup=back_keyboard("a:panel"))
        await callback.answer()

    @router.callback_query(F.data == "a:logout")
    @admin_access.require_access
    async def callback_admin_logout(callback: CallbackQuery) -> None:
        await client.token_storage.clear()
        client.mark_session_expired("admin logout")
        await callback.message.edit_text("✅ Logged out.", reply_markup=back_keyboard("a:panel"))
        await callback.answer()
```

- [ ] **Step 3: Write admin tests**

```python
# tests/test_admin.py
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.fsm import AdminStates


@pytest.fixture
def cooldown() -> CooldownManager:
    return CooldownManager()


@pytest.fixture
def storage(tmp_path: str) -> SqliteStorage:
    import tempfile
    from pathlib import Path
    s = SqliteStorage(Path(tmp_path) / "admin_test.db")
    # We need to handle this differently - using MagicMock for storage
    return s


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def _make_message(user_id: int, text: str = "") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _build_admin_router(storage_mock: MagicMock) -> dict[str, object]:
    router = Router()
    client = MagicMock()
    admin_access = AccessControl([1], default_allow=False)
    cooldown = CooldownManager()
    register_admin_handlers(router, client, storage_mock, admin_access, cooldown)
    handlers: dict[str, object] = {}
    for h in router.callback_query.handlers:
        if hasattr(h.callback, "__name__"):
            handlers[h.callback.__name__] = h.callback
    # FSM message handlers aren't in callback_query.handlers
    for h in router.message.handlers:
        if hasattr(h.callback, "__name__"):
            handlers[h.callback.__name__] = h.callback
    return handlers


class TestAdminPanel:
    async def test_admin_panel_shows_status(self) -> None:
        storage_mock = MagicMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1, 2])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:panel"

        await handlers["callback_admin_panel"](cb)

        assert "Admin Panel" in cb.message.edit_text.call_args[0][0]
        cb.answer.assert_awaited_once()

    async def test_admin_panel_blocks_non_admin(self) -> None:
        storage_mock = MagicMock()
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=99)
        cb.data = "a:panel"

        await handlers["callback_admin_panel"](cb)

        cb.answer.assert_awaited_with("Access denied.", show_alert=True)


class TestUserList:
    async def test_user_list_shows_users(self) -> None:
        storage_mock = MagicMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1, 42, 100])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:users"

        await handlers["callback_user_list"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "42" in text
        assert "100" in text
        cb.answer.assert_awaited_once()


class TestAddUserFSM:
    async def test_add_user_start_shows_prompt(self) -> None:
        storage_mock = MagicMock()
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:add"
        state = FSMContext(storage=MemoryStorage(), key="test")

        await handlers["callback_add_user_start"](cb, state)

        text = cb.message.edit_text.call_args[0][0]
        assert "user ID" in text.lower()
        assert await state.get_state() == AdminStates.waiting_user_id

    async def test_add_user_id_saves(self) -> None:
        storage_mock = MagicMock()
        storage_mock.set_user_allowed = AsyncMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[42])
        handlers = _build_admin_router(storage_mock)

        msg = _make_message(user_id=1, text="42")
        state = FSMContext(storage=MemoryStorage(), key="test")
        await state.set_state(AdminStates.waiting_user_id)

        await handlers["fsm_add_user_id"](msg, state)

        storage_mock.set_user_allowed.assert_awaited_once_with(42)
        msg.answer.assert_awaited()
        assert await state.get_state() is None


class TestRemoveUser:
    async def test_remove_user(self) -> None:
        storage_mock = MagicMock()
        storage_mock.remove_user = AsyncMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:rm:42"

        await handlers["callback_remove_user"](cb)

        storage_mock.remove_user.assert_awaited_once_with(42)
        cb.answer.assert_awaited_with("User 42 removed.")
```

- [ ] **Step 4: Run admin tests**

```bash
pytest tests/test_admin.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/domonap_bot/telegram/fsm.py src/domonap_bot/telegram/admin.py tests/test_admin.py
git commit -m "feat: add FSM-based admin panel with user management"
```

---

### Task 5: Menu + navigation

**Files:**
- Create: `src/domonap_bot/telegram/menu.py`
- Modify: `src/domonap_bot/telegram/bot.py` (register menu router)
- Create: `tests/test_menu.py`

**Interfaces:**
- Consumes: `DomonapClient`, `SqliteStorage`, `AccessControl`, `CooldownManager`
- Produces:
  - `dashboard: dict[int, int]` — per-user tracked message_id
  - `register_menu_handlers(router, client, storage, access, cooldown)` — registers /start and nav:back

- [ ] **Step 1: Create menu.py**

```python
# src/domonap_bot/telegram/menu.py
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

# Per-user tracked dashboard message_id
dashboard: dict[int, int] = {}


async def _render(
    target: Message | CallbackQuery,
    text: str,
    kb,
) -> None:
    if isinstance(target, CallbackQuery) and target.message:
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    elif isinstance(target, Message):
        sent = await target.answer(text, reply_markup=kb)
        if sent and hasattr(sent, "message_id"):
            uid = target.from_user.id if target.from_user else 0
            dashboard[uid] = sent.message_id


def register_menu_handlers(
    router: Router,
    client: DomonapClient,
    storage: SqliteStorage,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.message(Command("start"))
    @access.require_access
    async def cmd_start(message: Message) -> None:
        has_token = client.access_token or client.refresh_token
        doors_count = 0
        try:
            doors = await client.get_doors()
            doors_count = len(doors)
        except Exception:
            pass

        parts = [
            "🏠 Domonap Bot",
            "─────────────────────",
            f"Status: {'✅ Authorized' if has_token else '❌ Not authorized'}",
            f"Doors: {doors_count}",
            "",
        ]
        text = "\n".join(parts)
        is_admin = admin_access.is_allowed(message.from_user.id if message.from_user else 0)
        await _render(message, text, main_menu_keyboard(is_admin))

    @router.callback_query(F.data == "m:main")
    @access.require_access
    async def callback_main_menu(callback: CallbackQuery) -> None:
        has_token = client.access_token or client.refresh_token
        doors_count = 0
        try:
            doors = await client.get_doors()
            doors_count = len(doors)
        except Exception:
            pass

        parts = [
            "🏠 Domonap Bot",
            "─────────────────────",
            f"Status: {'✅ Authorized' if has_token else '❌ Not authorized'}",
            f"Doors: {doors_count}",
            "",
        ]
        text = "\n".join(parts)
        is_admin = admin_access.is_allowed(callback.from_user.id if callback.from_user else 0)
        await _render(callback, text, main_menu_keyboard(is_admin))

    @router.callback_query(F.data == "noop")
    async def callback_noop(callback: CallbackQuery) -> None:
        await callback.answer()
```

- [ ] **Step 2: Write menu tests**

```python
# tests/test_menu.py
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.menu import register_menu_handlers, dashboard


def _make_message(user_id: int) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


class TestMainMenu:
    async def test_cmd_start_shows_menu(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        msg = _make_message(user_id=1)
        await router.message.handlers[0].callback(msg)

        text = msg.answer.call_args[0][0]
        assert "Domonap" in text

    async def test_callback_main_menu(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "m:main"

        for h in router.callback_query.handlers:
            if hasattr(h.callback, "__name__") and h.callback.__name__ == "callback_main_menu":
                await h.callback(cb)
                break

        text = cb.message.edit_text.call_args[0][0]
        assert "Domonap" in text
        cb.answer.assert_awaited_once()

    async def test_noop_answers(self) -> None:
        router = Router()
        client = MagicMock()
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        cb = _make_callback(user_id=1)
        for h in router.callback_query.handlers:
            if hasattr(h.callback, "__name__") and h.callback.__name__ == "callback_noop":
                await h.callback(cb)
                break

        cb.answer.assert_awaited_once()
```

- [ ] **Step 3: Run menu tests**

```bash
pytest tests/test_menu.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/domonap_bot/telegram/menu.py tests/test_menu.py
git commit -m "feat: add main menu with dashboard navigation"
```

---

### Task 6: Doors UI

**Files:**
- Create: `src/domonap_bot/telegram/doors.py`
- Create: `tests/test_doors.py`

**Interfaces:**
- Consumes: `DomonapClient`, `AccessControl`, `CooldownManager`, `dashboard` dict (from menu), `_render` (from menu)
- Produces: `register_door_handlers(router, client, access, cooldown)`

- [ ] **Step 1: Create doors.py**

```python
# src/domonap_bot/telegram/doors.py
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import door_list_keyboard, door_detail_keyboard
from domonap_bot.telegram.menu import _render

logger = logging.getLogger(__name__)

_PER_PAGE = 10


def register_door_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.callback_query(F.data.startswith("d:p:"))
    @access.require_access
    async def callback_door_list(callback: CallbackQuery) -> None:
        page_str = callback.data.removeprefix("d:p:")
        try:
            page = int(page_str)
        except ValueError:
            page = 0

        try:
            doors = await client.get_doors()
        except DomonapError:
            await callback.message.edit_text("Failed to load doors.")
            await callback.answer()
            return

        total = len(doors)
        total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
        start = page * _PER_PAGE
        page_doors = doors[start: start + _PER_PAGE]

        text = f"🚪 Doors ({total})\n─────────────────────\n" if total > 0 else "No doors available."
        lines = [f"{start + i + 1}. 🚪 {d.name}" for i, d in enumerate(page_doors)]
        text += "\n".join(lines)

        kb = door_list_keyboard(page_doors, page, total_pages)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("d:det:"))
    @access.require_access
    async def callback_door_detail(callback: CallbackQuery) -> None:
        door_id = callback.data.removeprefix("d:det:")

        try:
            doors = await client.get_doors()
        except DomonapError:
            await callback.message.edit_text("Failed to load door details.")
            await callback.answer()
            return

        door = next((d for d in doors if d.id == door_id), None)
        if not door:
            await callback.message.edit_text("Door not found.")
            await callback.answer()
            return

        parts = [
            f"🚪 {door.name}",
            "─────────────────────",
        ]
        if door.domofon_public_pin:
            masked = door.domofon_public_pin[:2] + "****" + door.domofon_public_pin[-2:] if len(door.domofon_public_pin) >= 4 else "****"
            parts.append(f"PIN: {masked}")
        if door.http_video_url or door.webrtc_video_url:
            parts.append("📹 Video available")
        text = "\n".join(parts)

        await callback.message.edit_text(text, reply_markup=door_detail_keyboard(door))
        await callback.answer()

    @router.callback_query(F.data.startswith("d:open:"))
    @access.require_access
    async def callback_door_open(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Invalid data", show_alert=True)
            return
        door_id = callback.data.removeprefix("d:open:")
        user_id = callback.from_user.id if callback.from_user else 0

        if not cooldown.is_ready(user_id, door_id):
            remaining = cooldown.remaining(user_id, door_id)
            await callback.answer(f"Wait {remaining:.0f}s", show_alert=True)
            return

        await callback.answer("Opening...")
        cooldown.set(user_id, door_id)

        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            await callback.message.edit_text(f"❌ {exc}")
            return

        text = "✅ Door opened!" if success else "❌ Failed to open."
        await callback.message.edit_text(
            text,
            reply_markup=door_detail_keyboard(
                DoorKey(id=door_id, door_id=door_id, name="")
            ),
        )
```

- [ ] **Step 2: Write doors tests**

```python
# tests/test_doors.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, User

from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=CallbackQuery)
    cb.message.edit_text = AsyncMock()
    return cb


def _handlers(router: Router) -> dict[str, object]:
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


class TestDoorList:
    async def test_door_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "No doors" in text
        cb.answer.assert_awaited_once()

    async def test_door_list_shows_doors(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[
            DoorKey(id="1", doorId="d1", name="Main"),
            DoorKey(id="2", doorId="d2", name="Back"),
        ])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Main" in text
        assert "Back" in text


class TestDoorDetail:
    async def test_door_detail_shows_info(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[
            DoorKey(id="1", doorId="d1", name="Main", domofonPublicPin="1234"),
        ])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:det:1"

        h = _handlers(router)
        await h["callback_door_detail"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Main" in text
        assert "PIN" in text


class TestDoorOpen:
    async def test_door_open_success(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=True)
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"

        h = _handlers(router)
        await h["callback_door_open"](cb)

        client.open_door.assert_awaited_once_with("door123")
        cb.message.edit_text.assert_awaited()
        assert "✅" in cb.message.edit_text.call_args[0][0]

    async def test_door_open_failure(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=False)
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"

        h = _handlers(router)
        await h["callback_door_open"](cb)

        assert "❌" in cb.message.edit_text.call_args[0][0]
```

- [ ] **Step 3: Run doors tests**

```bash
pytest tests/test_doors.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/domonap_bot/telegram/doors.py tests/test_doors.py
git commit -m "feat: add paginated door list, detail view, and open action"
```

---

### Task 7: Calls UI

**Files:**
- Create: `src/domonap_bot/telegram/calls.py`
- Modify: `src/domonap_bot/telegram/keyboards.py` (add `call_detail_keyboard` — done in Task 3)
- Create: `tests/test_calls.py`

**Interfaces:**
- Consumes: `DomonapClient`, `AccessControl`, `CooldownManager`, `_render` (from menu)
- Produces: `register_call_handlers(router, client, access, cooldown)`

- [ ] **Step 1: Create calls.py**

```python
# src/domonap_bot/telegram/calls.py
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import call_list_keyboard, call_detail_keyboard
from domonap_bot.telegram.menu import _render

logger = logging.getLogger(__name__)

_PER_PAGE = 10
# Per-user filter state: True = missed only, False = all
user_call_filter: dict[int, bool] = {}


def register_call_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.callback_query(F.data.startswith("c:p:"))
    @access.require_access
    async def callback_call_list(callback: CallbackQuery) -> None:
        page_str = callback.data.removeprefix("c:p:")
        try:
            page = int(page_str)
        except ValueError:
            page = 0

        uid = callback.from_user.id if callback.from_user else 0
        filter_missed = user_call_filter.get(uid, False)

        try:
            entries = await client.get_call_logs(
                per_page=_PER_PAGE,
                current_page=page + 1,
                missed_calls=filter_missed,
            )
        except DomonapError:
            await callback.message.edit_text("Failed to load call logs.")
            await callback.answer()
            return

        if not entries and page > 0:
            page = 0
            try:
                entries = await client.get_call_logs(
                    per_page=_PER_PAGE,
                    current_page=1,
                    missed_calls=filter_missed,
                )
            except DomonapError:
                await callback.message.edit_text("Failed to load call logs.")
                await callback.answer()
                return

        # Estimate total pages from API (we don't have total count from client directly)
        # Use the PagedResponse — but get_call_logs returns flat list. We'll assume
        # if fewer than per_page, it's the last page.
        has_more = len(entries) >= _PER_PAGE
        # Since we don't have total, use 999 as "more" indicator
        if has_more:
            total_pages_display = f"{page + 1}+"
        else:
            total_pages_display = str(page + 1)

        text = f"📞 Calls\n─────────────────────\n"
        text += f"Filter: {'Missed' if filter_missed else 'All'}\n\n"

        if not entries:
            text += "No calls found."
        else:
            for e in entries:
                status = "❌" if not e.answered else "✅"
                name = ""
                if e.door_id:
                    try:
                        doors = await client.get_doors()
                        door = next((d for d in doors if d.door_id == e.door_id or d.id == e.door_id), None)
                        if door:
                            name = door.name
                    except Exception:
                        pass
                time_str = e.call_time.strftime("%H:%M") if e.call_time else "??"
                text += f"\n{status} {name or e.caller or e.call_id[:8]} — {time_str}"

        kb = call_list_keyboard(entries, page, max(1, page + (1 if has_more else 0)), filter_missed)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("c:f:"))
    @access.require_access
    async def callback_call_filter(callback: CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        mode = callback.data.removeprefix("c:f:")
        user_call_filter[uid] = mode == "missed"

        # Re-render list on page 0
        cb = callback
        cb.data = "c:p:0"
        # Re-dispatch to the list handler
        await callback_call_list(cb)

    @router.callback_query(F.data.startswith("c:det:"))
    @access.require_access
    async def callback_call_detail(callback: CallbackQuery) -> None:
        call_id = callback.data.removeprefix("c:det:")

        try:
            entries = await client.get_call_logs(per_page=50, missed_calls=False)
        except DomonapError:
            await callback.message.edit_text("Failed to load call details.")
            await callback.answer()
            return

        entry = next((e for e in entries if e.call_id == call_id), None)
        if not entry:
            await callback.message.edit_text("Call not found.")
            await callback.answer()
            return

        door_name = entry.caller or ""
        if entry.door_id:
            try:
                doors = await client.get_doors()
                door = next((d for d in doors if d.door_id == entry.door_id or d.id == entry.door_id), None)
                if door:
                    door_name = door.name
            except Exception:
                pass

        parts = [
            "📞 Call Details",
            "─────────────────────",
            f"Door: {door_name}",
            f"Time: {entry.call_time.strftime('%H:%M:%S') if entry.call_time else '??'}",
            f"Status: {'Answered ✅' if entry.answered else 'Missed ❌'}",
        ]
        text = "\n".join(parts)

        video_url = None
        if entry.door_id:
            try:
                doors = await client.get_doors()
                door = next((d for d in doors if d.door_id == entry.door_id or d.id == entry.door_id), None)
                if door:
                    video_url = door.http_video_url or door.webrtc_video_url
            except Exception:
                pass

        kb = call_detail_keyboard(entry.call_id, entry.door_id, video_url)

        if entry.photo_url:
            try:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=entry.photo_url,
                    caption=text,
                    reply_markup=kb,
                )
            except Exception:
                await callback.message.edit_text(text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
```

- [ ] **Step 2: Write calls tests**

```python
# tests/test_calls.py
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, User

from domonap_bot.domonap.models import CallLogEntry
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.calls import register_call_handlers, user_call_filter
from domonap_bot.telegram.cooldown import CooldownManager


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=CallbackQuery)
    cb.message.edit_text = AsyncMock()
    return cb


class TestCallList:
    async def test_call_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Calls" in text
        cb.answer.assert_awaited_once()

    async def test_call_list_shows_entries(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[
            CallLogEntry(
                callId="call1",
                doorId="d1",
                caller="John",
                callTime=datetime(2024, 1, 1, 14, 30, 0),
                answered=False,
            ),
        ])
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Calls" in text

    async def test_call_list_filter_toggle(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:f:missed"

        # Find the filter handler
        for h in router.callback_query.handlers:
            cb_data_check = getattr(h.callback, "__name__", None)
            if cb_data_check == "callback_call_filter":
                await h.callback(cb)
                break

        assert user_call_filter.get(1) is True
```

- [ ] **Step 3: Run calls tests**

```bash
pytest tests/test_calls.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/domonap_bot/telegram/calls.py tests/test_calls.py
git commit -m "feat: add paginated call log browser with filter and detail view"
```

---

### Task 8: Wire everything together — refactor handlers.py + bot.py

**Files:**
- Modify: `src/domonap_bot/telegram/handlers.py` (remove callbacks moved to doors/calls/admin, keep only /auth, /code, /logout + error handlers)
- Modify: `src/domonap_bot/telegram/bot.py` (register all new routers)
- Modify: `tests/test_handlers.py` (update for refactored handlers)
- Modify: `src/domonap_bot/main.py` (pass storage to build_bot)

**Interfaces:**
- Consumes: all handlers from menu.py, doors.py, calls.py, admin.py, `SqliteStorage`
- Produces: fully wired `build_bot()` with all routers and shared `CooldownManager`

**Retained in handlers.py after refactor:**
- `cmd_status`, `cmd_doors`, `cmd_open` — text commands still useful
- `cmd_auth`, `cmd_code`, `cmd_logout` — admin commands
- `callback_open_door` (handles `open:` prefix from CallWatcher + `/doors`/`/open` keyboards)
- `callback_answer_call`, `callback_end_call` (handles `answer:`/`reject:` from CallWatcher)
- `_auto_open_door`, `_describe_error`, `_mask_phone`
- `register_handlers` — refactored to accept `cooldown: CooldownManager` param
- `cmd_start` → **removed** (handled by menu.py now)
- `CooldownManager` class → **removed** (moved to cooldown.py)

- [ ] **Step 1: Refactor handlers.py**

Remove CooldownManager class. Change import and register_handlers signature:

```python
# src/domonap_bot/telegram/handlers.py — top changes
from domonap_bot.telegram.cooldown import CooldownManager

# Remove cmd_start entirely (now in menu.py)

def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    # Remove: cooldown = CooldownManager()
    # Rest of the function is unchanged
```

- [ ] **Step 2: Update bot.py**

```python
# src/domonap_bot/telegram/bot.py
from aiogram import Bot, Dispatcher, Router

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.calls import register_call_handlers
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers
from domonap_bot.telegram.handlers import register_handlers
from domonap_bot.telegram.menu import register_menu_handlers


def build_bot(
    settings: Settings,
    client: DomonapClient,
    storage: SqliteStorage,
) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    access = AccessControl(settings.allowed_telegram_user_ids)
    admin_access = AccessControl(
        settings.admin_telegram_user_ids,
        default_allow=False,
    )

    cooldown = CooldownManager()
    router = Router()
    register_handlers(router, client, access, admin_access, cooldown)
    register_menu_handlers(router, client, storage, access, admin_access, cooldown)
    register_door_handlers(router, client, access, cooldown)
    register_call_handlers(router, client, access, cooldown)
    register_admin_handlers(router, client, storage, admin_access, cooldown)

    dp.include_router(router)
    return bot, dp
```

- [ ] **Step 3: Update main.py to pass storage to build_bot**

```python
# src/domonap_bot/main.py — change build_bot call
bot, dp = build_bot(settings, client, storage)
```

- [ ] **Step 4: Update tests/test_handlers.py**

Update the `_build_callback_handlers` function to pass `cooldown` and remove `cmd_start` references.

```python
def _build_callback_handlers(client: MagicMock) -> dict[str, object]:
    router = Router()
    access = AccessControl([1])
    admin_access = AccessControl([1], default_allow=False)
    cooldown = CooldownManager()
    register_handlers(router, client, access, admin_access, cooldown)
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all 30+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/domonap_bot/telegram/handlers.py src/domonap_bot/telegram/bot.py src/domonap_bot/main.py tests/test_handlers.py
git commit -m "feat: wire all interactive modules together in bot.py"
```<｜end▁of▁thinking｜>

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="read">
<｜｜DSML｜｜parameter name="filePath" string="true">/home/mnevrov/pet/domonap-telegram-bot/docs/superpowers/plans/2026-07-13-interactivity-plan.md