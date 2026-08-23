from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


def message_text(message: Message) -> str:
    if isinstance(message.caption, str):
        return message.caption
    if isinstance(message.text, str):
        return message.text
    return ""


def append_status(message: Message, status: str) -> str:
    body = message_text(message).rstrip()
    return f"{body}\n\n{status}" if body else status


def mark_door_opened(
    keyboard: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in keyboard.inline_keyboard:
        updated: list[InlineKeyboardButton] = []
        for button in row:
            callback_data = button.callback_data or ""
            if callback_data.startswith("open:"):
                updated.append(
                    button.model_copy(
                        update={
                            "text": "✅ Открыто",
                            "callback_data": "noop",
                            "style": "success",
                        }
                    )
                )
            else:
                updated.append(button)
        rows.append(updated)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mark_call_finished(
    keyboard: InlineKeyboardMarkup | None,
    *,
    text: str,
    style: str,
) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for row in keyboard.inline_keyboard:
        callbacks = {button.callback_data or "" for button in row}
        if any(
            callback.startswith("answer:") or callback.startswith("reject:")
            for callback in callbacks
        ):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=text,
                        callback_data="noop",
                        style=style,
                    )
                ]
            )
        else:
            rows.append(list(row))
    return InlineKeyboardMarkup(inline_keyboard=rows)
