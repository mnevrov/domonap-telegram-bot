from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import CallLogEntry, DoorKey


def door_selection_keyboard(doors: list[DoorKey]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d.name, callback_data=f"open:{d.door_id}")]
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
        [InlineKeyboardButton(text=f"🚪 {d.name}", callback_data=f"d:det:{d.door_id}")]
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
        [InlineKeyboardButton(text="🔓 Open", callback_data=f"d:open:{door.door_id}")],
    ]
    if door.http_video_url or door.webrtc_video_url:
        url = door.http_video_url or door.webrtc_video_url
        if url:
            rows.append([InlineKeyboardButton(text="📹 Video", url=url)])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="d:p:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_list_keyboard(
    entries: list[CallLogEntry], page: int, total_pages: int, filter_all: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{'📍' if e.door_id else '📞'} {e.caller or e.call_id[:8]} "
                f"– {e.call_time.strftime('%H:%M') if e.call_time else '??'} "
                f"{'❌' if not e.answered else '✅'}",
                callback_data=f"c:det:{e.call_id}",
            )
        ]
        for e in entries
    ]
    filter_label = "📋 All" if not filter_all else "📋 Missed"
    filter_data = "c:f:missed" if filter_all else "c:f:all"
    nav: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text=filter_label, callback_data=filter_data)
    ]
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"c:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"c:p:{page + 1}"))
    if len(nav) > 1:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Back", callback_data="m:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_detail_keyboard(
    call_id: str, door_id: str | None, video_url: str | None
) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Users", callback_data="a:users")],
            [InlineKeyboardButton(text="🔑 /auth", callback_data="a:auth")],
            [InlineKeyboardButton(text="🚪 /logout", callback_data="a:logout")],
            [InlineKeyboardButton(text="🏠 Back", callback_data="m:main")],
        ]
    )


def user_list_keyboard(
    users: list[int], admin_users: set[int] | None = None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for uid in users:
        is_admin = admin_users is not None and uid in admin_users
        label = f"👤 {uid}{' 👑' if is_admin else ''}  ❌"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"a:rm:{uid}")])
    rows.append([InlineKeyboardButton(text="➕ Add user", callback_data="a:add")])
    if admin_users is not None:
        non_admin = [uid for uid in users if uid not in admin_users]
        if non_admin:
            rows.append([InlineKeyboardButton(text="⬆ Grant admin", callback_data="a:grant")])
    rows.append([InlineKeyboardButton(text="◀️ Back", callback_data="a:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard(dest: str = "m:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Back", callback_data=dest)],
        ]
    )
