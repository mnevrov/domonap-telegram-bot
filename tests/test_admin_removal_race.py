import asyncio
from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from tests.test_client import FakeStorage


class YieldingAdminStorage(FakeStorage):
    async def list_admin_users(self) -> list[int]:
        snapshot = await super().list_admin_users()
        await asyncio.sleep(0)
        return snapshot


def _callback(user_id: int, target_id: int) -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = user_id
    callback.data = f"a:rmc:{target_id}"
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def _remove_handler(
    storage: FakeStorage,
    admin_access: AccessControl,
    access: AccessControl,
) -> object:
    router = Router()
    register_admin_handlers(router, MagicMock(), storage, admin_access, access)
    handlers = {
        handler.callback.__name__: handler.callback
        for handler in router.callback_query.handlers
    }
    return handlers["callback_remove_user_confirm"]


async def test_concurrent_admin_removals_cannot_remove_every_admin() -> None:
    storage = YieldingAdminStorage()
    for uid in (1, 2):
        await storage.set_user_allowed(uid)
        await storage.set_user_admin(uid)

    access = AccessControl([1, 2])
    admin_access = AccessControl([1, 2])
    handler = _remove_handler(storage, admin_access, access)
    admin_one = _callback(1, 2)
    admin_two = _callback(2, 1)

    await asyncio.gather(
        handler(admin_one),  # type: ignore[operator]
        handler(admin_two),  # type: ignore[operator]
    )

    stored_admins = set(await storage.list_admin_users())
    runtime_admins = set(admin_access.user_ids())
    allowed_users = set(access.user_ids())

    assert len(stored_admins) == 1
    assert runtime_admins == stored_admins
    assert stored_admins <= allowed_users

    final_answers = [
        admin_one.answer.await_args_list[-1],
        admin_two.answer.await_args_list[-1],
    ]
    assert sum(call.args[0] == "Пользователь удалён" for call in final_answers) == 1
    assert sum(
        call.args[0] == "Нельзя удалить последнего администратора"
        for call in final_answers
    ) == 1
