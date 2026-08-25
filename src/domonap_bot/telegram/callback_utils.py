import secrets
from collections import OrderedDict
from typing import cast

from aiogram.types import CallbackQuery, Message

_MAX_CALLBACK_DATA_BYTES = 64
_MAX_CALLBACK_ALIASES = 4096
_callback_aliases: OrderedDict[str, str] = OrderedDict()
_reverse_callback_aliases: dict[str, str] = {}


def compact_callback_id(prefix: str, value: str) -> str:
    """Keep callback data within Telegram's 64-byte limit."""
    if len(f"{prefix}{value}".encode("utf-8")) <= _MAX_CALLBACK_DATA_BYTES:
        return value

    existing = _reverse_callback_aliases.get(value)
    if existing is not None:
        _callback_aliases.move_to_end(existing)
        return existing

    while True:
        alias = f"~{secrets.token_urlsafe(8)}"
        if alias not in _callback_aliases:
            break
    _callback_aliases[alias] = value
    _reverse_callback_aliases[value] = alias
    while len(_callback_aliases) > _MAX_CALLBACK_ALIASES:
        old_alias, old_value = _callback_aliases.popitem(last=False)
        if _reverse_callback_aliases.get(old_value) == old_alias:
            del _reverse_callback_aliases[old_value]
    return alias


def resolve_callback_id(value: str) -> str:
    resolved = _callback_aliases.get(value)
    if resolved is None:
        return value
    _callback_aliases.move_to_end(value)
    return resolved


def editable_callback_message(callback: CallbackQuery) -> Message | None:
    """Return a callback message only when Telegram allows editing it."""
    message = callback.message
    if message is None or not hasattr(message, "edit_text"):
        return None
    return cast(Message, message)
