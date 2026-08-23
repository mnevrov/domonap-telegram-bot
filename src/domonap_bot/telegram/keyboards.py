from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import CallLogEntry, DoorKey
from domonap_bot.telegram.url_policy import safe_http_url


def door_selection_keyboard(doors: list[DoorKey]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🔓 {door.name}",
                callback_data=f"open:{door.door_id}",
                style="success",
            )
        ]
        for door in doors
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔓 Открыть дверь",
                callback_data="d:p:0",
                style="success",
            )
        ],
        [InlineKeyboardButton(text="📞 Звонки", callback_data="c:p:0")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="⚙️ Управление", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def door_list_keyboard(doors: list[DoorKey], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"🚪 {door.name}", callback_data=f"d:det:{door.door_id}")]
        for door in doors
    ]
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"d:p:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"d:p:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def door_detail_keyboard(door: DoorKey) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔓 Открыть",
                callback_data=f"d:open:{door.door_id}",
                style="success",
            )
        ],
    ]
    video_url = safe_http_url(door.http_video_url) or safe_http_url(door.webrtc_video_url)
    if video_url:
        rows.append([InlineKeyboardButton(text="📹 Камера", url=video_url)])
    rows.append([InlineKeyboardButton(text="← Двери", callback_data="d:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_list_keyboard(
    entries: list[CallLogEntry],
    page: int,
    total_pages: int,
    filter_missed: bool,
    *,
    names_by_call_id: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    names = names_by_call_id or {}
    rows: list[list[InlineKeyboardButton]] = []
    for entry in entries:
        status = "❌" if not entry.answered else "✅"
        name = names.get(entry.call_id) or entry.caller or entry.call_id[:8]
        time_text = entry.call_time.strftime("%H:%M") if entry.call_time else "—"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {name} · {time_text}",
                    callback_data=f"c:det:{entry.call_id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Все",
                callback_data="noop" if not filter_missed else "c:f:all",
                style="primary" if not filter_missed else None,
            ),
            InlineKeyboardButton(
                text="Пропущенные",
                callback_data="noop" if filter_missed else "c:f:missed",
                style="primary" if filter_missed else None,
            ),
        ]
    )

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"c:p:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"c:p:{page + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_detail_keyboard(
    call_id: str, door_id: str | None, video_url: str | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📞 Ответить",
                callback_data=f"answer:{call_id}",
                style="primary",
            ),
            InlineKeyboardButton(
                text="Сбросить",
                callback_data=f"reject:{call_id}",
                style="danger",
            ),
        ],
    ]
    if door_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔓 Открыть дверь",
                    callback_data=f"open:{door_id}",
                    style="success",
                )
            ]
        )
    safe_video_url = safe_http_url(video_url)
    if safe_video_url:
        rows.append([InlineKeyboardButton(text="📹 Камера", url=safe_video_url)])
    rows.append([InlineKeyboardButton(text="← Звонки", callback_data="c:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="a:users")],
            [InlineKeyboardButton(text="🔑 Подключить Domonap", callback_data="a:auth")],
            [
                InlineKeyboardButton(
                    text="Выйти из Domonap",
                    callback_data="a:logout",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="← Главное меню", callback_data="m:main")],
        ]
    )


def user_list_keyboard(
    users: list[int], admin_users: set[int] | None = None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for uid in users:
        is_admin = admin_users is not None and uid in admin_users
        label = f"👤 {uid}{' 👑' if is_admin else ''}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"a:rm:{uid}")])
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить пользователя",
                callback_data="a:add",
                style="primary",
            )
        ]
    )
    if admin_users is not None:
        non_admin = [uid for uid in users if uid not in admin_users]
        if non_admin:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⬆️ Назначить администратора",
                        callback_data="a:grant",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="← Управление", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard(dest: str = "m:main", text: str = "← Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=dest)]]
    )
