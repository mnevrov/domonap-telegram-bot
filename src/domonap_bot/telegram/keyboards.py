from collections.abc import Callable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import CallLogEntry, DoorKey
from domonap_bot.telegram.callback_utils import compact_callback_id
from domonap_bot.telegram.url_policy import safe_http_url

CameraUrlProvider = Callable[[DoorKey], str | None]


def door_selection_keyboard(doors: list[DoorKey]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🔓 {door.name}",
                callback_data=f"open:{compact_callback_id('open:', door.door_id)}",
                style="success",
            )
        ]
        for door in doors
    ]
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(is_admin: bool, *, authorized: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if authorized:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="🔓 Открыть дверь",
                        callback_data="d:p:0",
                        style="success",
                    )
                ],
                [InlineKeyboardButton(text="📞 Звонки", callback_data="c:p:0")],
            ]
        )
    if is_admin:
        rows.append([InlineKeyboardButton(text="⚙️ Управление", callback_data="a:panel")])
        if not authorized:
            rows.append(
                [InlineKeyboardButton(text="🔑 Подключить Domonap", callback_data="a:auth")]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def door_list_keyboard(
    doors: list[DoorKey],
    page: int,
    total_pages: int,
    *,
    camera_url_provider: CameraUrlProvider | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for door in doors:
        row = [
            InlineKeyboardButton(
                text=f"🔓 {door.name}",
                callback_data=f"d:open:{compact_callback_id('d:open:', door.door_id)}",
                style="success",
            )
        ]
        video_url = (
            safe_http_url(camera_url_provider(door))
            if camera_url_provider is not None
            else safe_http_url(door.http_video_url) or safe_http_url(door.webrtc_video_url)
        )
        if video_url:
            row.append(InlineKeyboardButton(text="📹", url=video_url))
        rows.append(row)

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


def door_detail_keyboard(
    door: DoorKey, *, camera_url_provider: CameraUrlProvider | None = None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔓 Открыть",
                callback_data=f"d:open:{compact_callback_id('d:open:', door.door_id)}",
                style="success",
            )
        ],
    ]
    video_url = (
        safe_http_url(camera_url_provider(door))
        if camera_url_provider is not None
        else safe_http_url(door.http_video_url) or safe_http_url(door.webrtc_video_url)
    )
    if video_url:
        rows.append([InlineKeyboardButton(text="📹 Камера", url=video_url)])
    rows.append([InlineKeyboardButton(text="← Двери", callback_data="d:back")])
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
                    callback_data=f"c:det:{compact_callback_id('c:det:', entry.call_id)}",
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
    _call_id: str, door_id: str | None, video_url: str | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if door_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔓 Открыть дверь",
                    callback_data=f"open:{compact_callback_id('open:', door_id)}",
                    style="success",
                )
            ]
        )
    safe_video_url = safe_http_url(video_url)
    if safe_video_url:
        rows.append([InlineKeyboardButton(text="📹 Камера", url=safe_video_url)])
    rows.append([InlineKeyboardButton(text="← Звонки", callback_data="c:back")])
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
                )
            ],
            [InlineKeyboardButton(text="← Главное меню", callback_data="m:main")],
        ]
    )


def confirm_logout_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, выйти", callback_data="a:logoutc", style="danger")],
            [InlineKeyboardButton(text="Отмена", callback_data="a:panel")],
        ]
    )


def user_list_keyboard(
    users: list[int],
    admin_users: set[int] | None = None,
    profiles: dict[int, dict[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    admin_ids = admin_users or set()
    user_profiles = profiles or {}
    rows: list[list[InlineKeyboardButton]] = []
    for uid in users:
        profile = user_profiles.get(uid, {})
        display_name = profile.get("first_name") or profile.get("username") or str(uid)
        username = profile.get("username")
        if username and profile.get("first_name"):
            display_name = f"{display_name} (@{username})"
        label = f"👤 {display_name}{' 👑' if uid in admin_ids else ''}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"a:user:{uid}")])
    rows.append(
        [
            InlineKeyboardButton(
                text="🔗 Пригласить пользователя",
                callback_data="a:invite",
                style="primary",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="← Управление", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_detail_keyboard(user_id: int, *, is_admin: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Снять права администратора",
                    callback_data=f"a:rev:{user_id}",
                    style="danger",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬆️ Сделать администратором",
                    callback_data=f"a:grant:{user_id}",
                    style="primary",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить пользователя",
                callback_data=f"a:rm:{user_id}",
                style="danger",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="← Пользователи", callback_data="a:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_remove_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"a:rmc:{user_id}",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data=f"a:user:{user_id}")],
        ]
    )


def confirm_revoke_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, снять права",
                    callback_data=f"a:revc:{user_id}",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text="Отмена", callback_data=f"a:user:{user_id}")],
        ]
    )


def back_keyboard(dest: str = "m:main", text: str = "← Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=dest)]]
    )


def retry_back_keyboard(
    retry_callback: str,
    back_callback: str = "m:main",
    back_text: str = "← Главное меню",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить", callback_data=retry_callback)],
            [InlineKeyboardButton(text=back_text, callback_data=back_callback)],
        ]
    )
