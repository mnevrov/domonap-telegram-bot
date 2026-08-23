import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.config import Settings
from domonap_bot.domonap.client import BASE_URL, DomonapClient
from domonap_bot.domonap.models import CallLogEntry, DoorKey, IncomingCallPayload
from domonap_bot.domonap.signalr import DomonapSignalRTransport
from domonap_bot.telegram.access import AccessControl

logger = logging.getLogger(__name__)

_MAX_SEEN_IDS = 1000
_POLL_INTERVAL = 5.0
_SIGNALR_RETRY_INTERVAL = 300.0
_DOOR_MAP_TTL = 300.0


class CallEventSource(Protocol):
    def listen_once(self) -> AsyncIterator[IncomingCallPayload]: ...

    async def close(self) -> None: ...


class CallWatcher:
    def __init__(
        self,
        client: DomonapClient,
        bot: Bot,
        settings: Settings,
        *,
        event_source: CallEventSource | None = None,
        access: AccessControl | None = None,
    ) -> None:
        self._client = client
        self._bot = bot
        self._settings = settings
        self._access = access
        self._task: asyncio.Task[Any] | None = None
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._door_map: dict[str, DoorKey] = {}
        self._door_map_loaded_at = 0.0
        if event_source is None:
            self._event_source: CallEventSource = DomonapSignalRTransport(
                base_url=BASE_URL,
                token_provider=lambda: self._client.access_token,
                refresh_callback=self._client.refresh_session,
            )
        else:
            self._event_source = event_source

    async def start(self) -> None:
        if not self._settings.call_watcher_enabled:
            logger.info("CallWatcher disabled by config")
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._event_source.close()

    async def _run(self) -> None:
        await self._wait_for_auth()
        await self._load_door_map()
        await self._prepopulate_seen()

        while True:
            try:
                async for event in self._event_source.listen_once():
                    await self._handle_payload(event)
                logger.info("SignalR session ended, using polling before reconnect")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("SignalR session failed (%s), falling back to polling", exc)

            await self._poll_loop(max_duration=_SIGNALR_RETRY_INTERVAL)

    async def _wait_for_auth(self) -> None:
        """Block until the client has an access or refresh token."""
        while not self._client.access_token and not self._client.refresh_token:
            logger.debug("Waiting for authentication before starting call watcher...")
            await asyncio.sleep(10)

    async def _prepopulate_seen(self) -> None:
        try:
            logs = await self._client.get_call_logs(per_page=20, missed_calls=False)
            for entry in logs:
                self._add_seen(entry.call_id)
            logger.info("Pre-populated %s seen call IDs from call logs", len(logs))
        except Exception as exc:
            logger.warning("Failed to pre-populate seen IDs: %s", exc)

    async def _poll_loop(self, max_duration: float | None = None) -> None:
        deadline = time.monotonic() + max_duration if max_duration is not None else None
        while True:
            try:
                await self._ensure_door_map_fresh()
                logs = await self._client.get_call_logs(per_page=10, missed_calls=False)
                for entry in logs:
                    await self._handle_entry(entry)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Call log poll error: %s", exc)

            if deadline is not None and time.monotonic() >= deadline:
                return

            await asyncio.sleep(_POLL_INTERVAL)

    async def _load_door_map(self) -> None:
        try:
            doors = await self._client.get_doors()
            door_map: dict[str, DoorKey] = {}
            for door in doors:
                door_map[door.door_id] = door
                door_map[door.id] = door
            self._door_map = door_map
            self._door_map_loaded_at = time.monotonic()
        except Exception as exc:
            logger.warning("Failed to load door map: %s", exc)

    async def _ensure_door_map_fresh(self, *, force: bool = False) -> None:
        age = time.monotonic() - self._door_map_loaded_at
        if force or age >= _DOOR_MAP_TTL:
            await self._load_door_map()

    async def _resolve_door(self, door_id: str | None) -> DoorKey | None:
        await self._ensure_door_map_fresh()
        if not door_id:
            return None
        door = self._door_map.get(door_id)
        if door is None:
            await self._ensure_door_map_fresh(force=True)
            door = self._door_map.get(door_id)
        return door

    def _recipient_ids(self) -> list[int]:
        if self._access is not None:
            return self._access.user_ids()
        return list(dict.fromkeys(self._settings.allowed_telegram_user_ids))

    async def _handle_payload(self, payload: IncomingCallPayload) -> None:
        if payload.call_id in self._seen_ids:
            return
        self._add_seen(payload.call_id)

        door = await self._resolve_door(payload.door_id)

        video_url = payload.video_preview
        if not video_url and door:
            video_url = door.http_video_url or door.webrtc_video_url

        await self._send_notification(
            user_ids=self._recipient_ids(),
            text=self._build_message_text(
                door=door,
                address=payload.address or payload.title,
            ),
            photo_url=payload.photo_url or payload.video_preview,
            door_id=payload.door_id or (door.door_id if door else None),
            video_url=video_url,
            call_id=payload.call_id,
        )

    async def _handle_entry(self, entry: CallLogEntry) -> None:
        if entry.call_id in self._seen_ids:
            return
        self._add_seen(entry.call_id)

        door = await self._resolve_door(entry.door_id)
        video_url = door.http_video_url or door.webrtc_video_url if door else None

        await self._send_notification(
            user_ids=self._recipient_ids(),
            text=self._build_message_text(door=door, call_time=entry.call_time),
            photo_url=entry.photo_url,
            door_id=entry.door_id or (door.door_id if door else None),
            video_url=video_url,
            call_id=entry.call_id,
        )

    def _add_seen(self, call_id: str) -> None:
        if call_id in self._seen_ids:
            return
        self._seen_ids.add(call_id)
        self._seen_order.append(call_id)
        while len(self._seen_order) > _MAX_SEEN_IDS:
            oldest = self._seen_order.popleft()
            self._seen_ids.discard(oldest)

    @staticmethod
    def _build_message_text(
        door: DoorKey | None = None,
        address: str | None = None,
        call_time: datetime | None = None,
    ) -> str:
        parts = ["📞 Входящий звонок"]
        if door:
            parts.append(f"Дверь: {door.name}")
        elif address:
            parts.append(f"Адрес: {address}")
        if call_time:
            parts.append(f"Время: {call_time.strftime('%H:%M:%S')}")
        else:
            parts.append(f"Время: {datetime.now().strftime('%H:%M:%S')}")
        return "\n".join(parts)

    @staticmethod
    def _build_keyboard(
        door_id: str | None,
        video_url: str | None,
        call_id: str | None = None,
    ) -> InlineKeyboardMarkup | None:
        buttons: list[list[InlineKeyboardButton]] = []
        if call_id:
            buttons.append([
                InlineKeyboardButton(text="📞 Ответить", callback_data=f"answer:{call_id}"),
                InlineKeyboardButton(text="🔴 Сбросить", callback_data=f"reject:{call_id}"),
            ])
        if door_id:
            buttons.append(
                [InlineKeyboardButton(text="🔓 Открыть", callback_data=f"open:{door_id}")]
            )
        if video_url:
            buttons.append([InlineKeyboardButton(text="📹 Видео", url=video_url)])
        if not buttons:
            return None
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def _send_notification(
        self,
        user_ids: list[int],
        text: str,
        photo_url: str | None = None,
        door_id: str | None = None,
        video_url: str | None = None,
        call_id: str | None = None,
    ) -> None:
        kb = self._build_keyboard(door_id=door_id, video_url=video_url, call_id=call_id)

        for uid in user_ids:
            try:
                if photo_url:
                    await self._bot.send_photo(
                        chat_id=uid,
                        photo=photo_url,
                        caption=text,
                        reply_markup=kb,
                    )
                else:
                    await self._bot.send_message(
                        chat_id=uid,
                        text=text,
                        reply_markup=kb,
                    )
            except Exception as exc:
                logger.warning("Failed to send notification to user %s: %s", uid, exc)

    def get_seen_ids_count(self) -> int:
        return len(self._seen_ids)
