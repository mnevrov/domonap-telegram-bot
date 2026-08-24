import logging

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ForceReply, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError, NetworkError
from domonap_bot.telegram.errors import describe_error

logger = logging.getLogger(__name__)

_MAX_SMS_CODE_LENGTH = 12


class AuthStates(StatesGroup):
    waiting_sms_code = State()


def mask_phone(phone: str) -> str:
    digits = "".join(char for char in phone if char.isdigit())
    if len(digits) < 4:
        return phone
    masked = digits[:3] + "***" + digits[-2:]
    return f"+{masked}" if phone.startswith("+") else masked


def normalize_sms_code(value: str) -> str | None:
    code = value.strip()
    if not code or len(code) > _MAX_SMS_CODE_LENGTH:
        return None
    if not code.isascii() or not code.isdecimal():
        return None
    return code


def sms_code_reply() -> ForceReply:
    return ForceReply(
        selective=True,
        input_field_placeholder="Код из SMS",
    )


async def _delete_code_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def request_sms_code(
    message: Message,
    client: DomonapClient,
    state: FSMContext,
) -> bool:
    # A new authorization attempt supersedes any previous pending SMS flow.
    await state.clear()

    phone = client.phone
    if not phone:
        await message.answer("Номер телефона Domonap не настроен.")
        return False

    try:
        success = await client.login(phone)
    except NetworkError:
        await message.answer("Сеть недоступна. Повторите позже.")
        return False
    except DomonapError as exc:
        logger.warning("SMS request failed for phone %s: %s", mask_phone(phone), exc)
        await message.answer(describe_error(exc))
        return False

    if not success:
        await message.answer("Не удалось запросить SMS-код. Проверьте номер телефона.")
        return False

    await state.set_state(AuthStates.waiting_sms_code)
    await message.answer(
        f"SMS отправлена на {mask_phone(phone)}.\n\nВведите код из сообщения:",
        reply_markup=sms_code_reply(),
    )
    return True


async def submit_sms_code(
    message: Message,
    client: DomonapClient,
    state: FSMContext,
    code: str,
) -> bool:
    normalized = normalize_sms_code(code)
    if normalized is None:
        await _delete_code_message(message)
        await message.answer(
            "Код должен состоять только из цифр. Попробуйте ещё раз:",
            reply_markup=sms_code_reply(),
        )
        return False

    error: DomonapError | None = None
    try:
        success = await client.confirm_login(normalized)
    except DomonapError as exc:
        success = False
        error = exc
    finally:
        await _delete_code_message(message)

    if success:
        await state.clear()
        await message.answer("✅ Domonap подключён.")
        return True

    await state.clear()
    if error is not None:
        await message.answer(f"❌ {describe_error(error)}")
        return False

    await message.answer(
        "❌ Код не принят или сессия авторизации истекла. "
        "Запросите новый код через /auth или раздел «Управление»."
    )
    return False
