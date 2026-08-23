from dataclasses import dataclass

from aiogram.types import InlineKeyboardMarkup

from domonap_bot.domonap.models import CallLogEntry, DoorKey
from domonap_bot.telegram.keyboards import (
    call_detail_keyboard,
    call_list_keyboard,
    door_detail_keyboard,
    door_list_keyboard,
    main_menu_keyboard,
)


@dataclass(frozen=True, slots=True)
class View:
    text: str
    keyboard: InlineKeyboardMarkup | None = None


def home_view(*, authorized: bool, is_admin: bool) -> View:
    if authorized:
        text = "🏠 Домофон\n\nВыберите действие."
    else:
        text = "🏠 Домофон\n\n⚠️ Domonap не подключён."
    return View(text=text, keyboard=main_menu_keyboard(is_admin))


def door_list_view(
    doors: list[DoorKey],
    *,
    page: int,
    total_pages: int,
    total: int,
) -> View:
    if not doors:
        text = "🚪 Открыть дверь\n\nДоступных дверей нет."
    else:
        text = f"🚪 Открыть дверь ({total})\n\nКакую дверь открыть?"
    return View(text=text, keyboard=door_list_keyboard(doors, page, total_pages))


def door_detail_view(door: DoorKey) -> View:
    parts = [f"🚪 {door.name or 'Дверь'}"]
    if door.domofon_public_pin:
        pin = door.domofon_public_pin
        masked = pin[:2] + "****" + pin[-2:] if len(pin) >= 4 else "****"
        parts.append(f"PIN: {masked}")
    if door.http_video_url or door.webrtc_video_url:
        parts.append("📹 Камера доступна")
    return View(text="\n".join(parts), keyboard=door_detail_keyboard(door))


def calls_view(
    entries: list[CallLogEntry],
    *,
    page: int,
    total_pages: int,
    filter_missed: bool,
    names_by_call_id: dict[str, str],
) -> View:
    mode = "Пропущенные" if filter_missed else "Все"
    text = f"📞 Звонки\n\nФильтр: {mode}"
    if not entries:
        text += "\n\nЗвонков нет."
    return View(
        text=text,
        keyboard=call_list_keyboard(
            entries,
            page,
            total_pages,
            filter_missed,
            names_by_call_id=names_by_call_id,
        ),
    )


def call_detail_view(
    entry: CallLogEntry,
    *,
    door_name: str,
    video_url: str | None,
) -> View:
    time_text = entry.call_time.strftime("%H:%M:%S") if entry.call_time else "—"
    status = "Принят ✅" if entry.answered else "Пропущен ❌"
    name = door_name or entry.caller or "Неизвестно"
    return View(
        text=f"📞 Звонок\n\nДверь: {name}\nВремя: {time_text}\nСтатус: {status}",
        keyboard=call_detail_keyboard(entry.call_id, entry.door_id, video_url),
    )
