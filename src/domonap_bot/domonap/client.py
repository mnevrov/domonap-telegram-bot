import asyncio
import logging
from datetime import datetime, timezone
from secrets import token_bytes
from typing import Any, Callable
from uuid import UUID

import httpx

from domonap_bot.domonap.auth import DomonapAuth
from domonap_bot.domonap.exceptions import (
    ApiError,
    AuthenticationError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.domonap.models import (
    AuthSession,
    CallLogEntry,
    CallLogPage,
    DoorKey,
    PagedResponse,
    TokenData,
)
from domonap_bot.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)

BASE_URL = "https://api.domonap.ru"
DEFAULT_USER_AGENT = "okhttp/5.3.2"
DEFAULT_DEVICE_PLATFORM = "Android"
DEFAULT_DOM_APP = "mobile"
DOOR_KEY_TYPES: tuple[int, ...] = (0, 1, 2, 4, 5, 6)
_DEFAULT_KEYS_PAGE_SIZE = 100
_MAX_KEYS_PAGES = 100
_ANDROID_GUID_RETRY_LIMIT = 8
_MAX_CALL_LOG_PAGES = 100
_generated_android_guids: set[str] = set()


def _generate_android_guid() -> str:
    random_bytes = bytearray(token_bytes(16))
    random_bytes[6] = (random_bytes[6] & 0x0F) | 0x40
    random_bytes[8] = (random_bytes[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(random_bytes)))


def _generate_unique_android_guid() -> str:
    for _ in range(_ANDROID_GUID_RETRY_LIMIT):
        guid = _generate_android_guid()
        if guid not in _generated_android_guids:
            _generated_android_guids.add(guid)
            return guid
    guid = _generate_android_guid()
    _generated_android_guids.add(guid)
    return guid


def _with_suffix(value: str) -> str:
    return value if value.endswith(";") else f"{value};"


def _phone_digits(phone: str) -> tuple[str, str]:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("7") or digits.startswith("8"):
        digits = digits[1:]
    return "7", digits


def _has_api_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("error") not in (None, "", False)


def _parse_dt(val: str) -> datetime | None:
    fmts = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")
    for fmt in fmts:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        pass
    logger.warning("Cannot parse datetime: %s", val)
    return None


class DomonapClient:
    def __init__(
        self,
        token_storage: TokenStorage,
        phone: str = "",
        device_token: str | None = None,
        instance_id: str | None = None,
        register_device_token: bool = False,
    ) -> None:
        self._token_storage = token_storage
        self._phone = phone
        self._register_device_token = register_device_token

        self._device_token_explicit = device_token is not None
        self._instance_id_explicit = instance_id is not None
        self._device_token = device_token or _generate_unique_android_guid()
        self._instance_id = instance_id or _generate_unique_android_guid()

        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.refresh_expiration_date: str | None = None

        self._refresh_token_invalid: bool = False
        self._refresh_lock = asyncio.Lock()
        self.token_update_callback: Callable[[AuthSession], None] | None = None

        headers: dict[str, str] = {
            "User-Agent": DEFAULT_USER_AGENT,
            "dom-app": _with_suffix(DEFAULT_DOM_APP),
            "dom-platform": _with_suffix(DEFAULT_DEVICE_PLATFORM),
            "instanceId": _with_suffix(self._instance_id),
        }

        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(30.0, connect=15.0),
            headers=headers,
        )
        self.auth = DomonapAuth(self._http)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "DomonapClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @property
    def token_storage(self) -> TokenStorage:
        return self._token_storage

    @property
    def phone(self) -> str:
        return self._phone

    @property
    def device_token(self) -> str:
        return self._device_token

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def register_device_token(self) -> bool:
        return self._register_device_token

    def set_tokens(
        self,
        access_token: str | None,
        refresh_token: str | None,
        refresh_expiration_date: str | None,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.refresh_expiration_date = refresh_expiration_date
        if refresh_token:
            self._refresh_token_invalid = False

    async def hydrate_from_storage(self) -> bool:
        """Restore a previously persisted session into this client.

        Must be called once during startup, before any concurrent request
        path (polling, call watcher) begins — no locking is needed here.
        """
        session = await self._token_storage.load_full()
        if session is None:
            return False
        self.set_tokens(
            session.access_token, session.refresh_token, session.refresh_expiration_date
        )
        if not self._phone and session.phone:
            self._phone = session.phone
        if session.device_token and not self._device_token_explicit:
            self._device_token = session.device_token
        if session.instance_id and not self._instance_id_explicit:
            self._instance_id = session.instance_id
            self._http.headers["instanceId"] = _with_suffix(session.instance_id)
        return True

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _refresh_expired(self) -> bool:
        if not self.refresh_token or not self.refresh_expiration_date:
            return False
        exp = _parse_dt(self.refresh_expiration_date)
        return bool(exp and self._now_utc() >= exp)

    def has_valid_refresh_token(self) -> bool:
        if self._refresh_token_invalid:
            return False
        if self._refresh_expired():
            return False
        return bool(self.refresh_token)

    def mark_session_expired(self, reason: str) -> None:
        self._invalidate_refresh(reason)

    def _invalidate_refresh(self, reason: str) -> None:
        if self._refresh_token_invalid and not self.refresh_token and not self.access_token:
            return
        logger.warning("Domonap session expired: %s", reason)
        self._refresh_token_invalid = True
        self.access_token = None
        self.refresh_token = None
        self.refresh_expiration_date = None
        if self.token_update_callback:
            self.token_update_callback(AuthSession(phone=self._phone))

    def _ensure_refresh_is_available(self) -> bool:
        if self._refresh_token_invalid:
            return False
        if self._refresh_expired():
            self._invalidate_refresh("refresh token expired")
            return False
        return bool(self.refresh_token)

    async def _ensure_alive(self) -> None:
        if self._refresh_expired():
            self._invalidate_refresh("refresh token expired")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        need_auth: bool = False,
        expect_text: bool = False,
        retry_on_401: bool = True,
        session_rejection_statuses: tuple[int, ...] = (),
    ) -> dict[str, Any] | str:
        if self._refresh_token_invalid and need_auth:
            raise SessionExpiredError("Session expired")

        if need_auth:
            if not self.access_token:
                raise TokenExpiredError("No access token available")
            await self._ensure_alive()
            if not self.access_token:
                raise SessionExpiredError("Session expired")

        url = f"{BASE_URL}{path}"
        first_try_access_token = self.access_token

        async def _do() -> httpx.Response:
            headers: dict[str, str] = {}
            if payload is not None:
                headers["Content-Type"] = "application/json; charset=UTF-8"
            if need_auth and self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            try:
                return await self._http.request(
                    method, url, json=payload, headers=headers,
                )
            except httpx.TimeoutException as exc:
                raise NetworkError("Request timed out") from exc
            except httpx.ConnectError as exc:
                raise NetworkError("Connection failed") from exc
            except httpx.HTTPError as exc:
                raise NetworkError(f"HTTP transport error: {exc}") from exc

        resp = await _do()

        if resp.status_code == 401 and retry_on_401 and bool(self.refresh_token):
            if await self._try_refresh(first_try_access_token):
                resp = await _do()

        if resp.is_success:
            if expect_text:
                return resp.text
            try:
                parsed = resp.json()
            except ValueError as exc:
                raise ApiError(
                    f"Invalid JSON response from {path}: {resp.text[:500]}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ApiError(
                    f"Unexpected JSON response from {path}: {type(parsed).__name__}"
                )
            data: dict[str, Any] = parsed
            return data

        body = resp.text[:2000]
        if resp.status_code in session_rejection_statuses:
            self._invalidate_refresh(f"token rejected with HTTP {resp.status_code}")
            raise SessionExpiredError(f"HTTP {resp.status_code}: {body}")

        if resp.status_code == 401:
            if self._refresh_token_invalid:
                raise SessionExpiredError(f"HTTP 401: {body}")
            raise TokenExpiredError(f"HTTP 401: {body}")

        raise ApiError(f"HTTP {resp.status_code}: {body}")

    async def _try_refresh(self, first_try_access_token: str | None) -> bool:
        if not self._ensure_refresh_is_available():
            return False
        async with self._refresh_lock:
            if (
                first_try_access_token
                and self.access_token
                and self.access_token != first_try_access_token
            ):
                return True
            if not self._ensure_refresh_is_available():
                return False
            try:
                await self._perform_token_refresh()
                return True
            except SessionExpiredError:
                return False

    async def _perform_token_refresh(self) -> None:
        if not self.refresh_token:
            raise SessionExpiredError("No refresh token")
        data = await self._request(
            "POST",
            "/sso-api/Authorization/RefreshToken",
            payload={"refreshToken": self.refresh_token},
            need_auth=False,
            retry_on_401=False,
            session_rejection_statuses=(400, 401, 403),
        )
        if isinstance(data, str):
            raise ApiError(f"Unexpected text response on refresh: {data}")

        self.set_tokens(
            data["accessToken"],
            data["refreshToken"],
            data["refreshExpirationDate"],
        )
        session = AuthSession(
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
            refresh_expiration_date=data["refreshExpirationDate"],
            phone=self._phone,
            device_token=self._device_token,
            instance_id=self._instance_id,
        )
        await self._token_storage.save(session)
        if self.token_update_callback:
            self.token_update_callback(session)

    # --- Auth helpers ---

    async def login(self, phone: str) -> bool:
        country_code, number = _phone_digits(phone)
        await self.auth.request_code(country_code, number)
        return True

    async def confirm_login(self, code: str) -> bool:
        try:
            token_data = await self._perform_confirm(code)
            session = AuthSession(
                access_token=token_data.access_token,
                refresh_token=token_data.refresh_token,
                refresh_expiration_date=token_data.refresh_expiration_date,
                phone=self._phone,
                device_token=self._device_token,
                instance_id=self._instance_id,
            )
            await self._token_storage.save(session)
            if self.token_update_callback:
                self.token_update_callback(session)
            return True
        except (ApiError, AuthenticationError, NetworkError):
            return False

    async def _perform_confirm(self, code: str) -> TokenData:
        country_code, phone_digits = _phone_digits(self._phone)
        raw = await self.auth.confirm_code(
            country_code=country_code,
            phone_number=phone_digits,
            confirm_code=code,
            device_token=self._device_token,
        )
        ct = raw.get("completeToken", raw)
        token_data = TokenData(
            access_token=ct["accessToken"],
            refresh_token=ct["refreshToken"],
            refresh_expiration_date=ct["refreshExpirationDate"],
        )
        self.set_tokens(
            token_data.access_token,
            token_data.refresh_token,
            token_data.refresh_expiration_date,
        )
        if self._register_device_token:
            await self._update_device_token()
        else:
            logger.info(
                "Skipping UpdateDeviceToken to preserve official Domonap push routing"
            )
        return token_data

    async def refresh_session(self) -> bool:
        try:
            await self._perform_token_refresh()
            return True
        except (ApiError, NetworkError, SessionExpiredError, TokenExpiredError):
            return False

    # --- Device token ---

    async def _update_device_token(self) -> None:
        await self._request(
            "POST",
            "/sso-api/Authorization/UpdateDeviceToken",
            payload={
                "deviceToken": self._device_token,
                "platform": DEFAULT_DEVICE_PLATFORM,
            },
            need_auth=True,
            expect_text=True,
            retry_on_401=True,
        )

    # --- User ---

    async def get_user(self) -> dict[str, Any]:
        data = await self._request("POST", "/sso-api/User/GetUser", need_auth=True)
        if isinstance(data, str):
            raise ApiError(f"Unexpected text response: {data}")
        return data

    async def get_username(self) -> str | None:
        user = await self.get_user()
        profile = user.get("userProfile") or {}
        return profile.get("username")

    # --- Keys / Doors ---

    async def get_paged_keys(
        self,
        per_page: int = _DEFAULT_KEYS_PAGE_SIZE,
        current_page: int = 1,
        keys_type: int = 0,
    ) -> PagedResponse:
        payload = {
            "currentPage": current_page,
            "perPage": per_page,
            "keysType": keys_type,
            "search": None,
        }
        data = await self._request(
            "POST",
            "/client-api/Key/GetPagedKeysByKeysType",
            payload=payload,
            need_auth=True,
        )
        if isinstance(data, str):
            raise ApiError(f"Unexpected text response: {data}")
        return PagedResponse(
            results=data.get("results", []),
            current_page=data.get("currentPage", current_page),
            per_page=data.get("perPage", per_page),
            total=data.get("total", 0),
        )

    async def get_all_keys(
        self,
        keys_types: tuple[int, ...] = DOOR_KEY_TYPES,
        per_page: int = _DEFAULT_KEYS_PAGE_SIZE,
    ) -> list[DoorKey]:
        result: list[DoorKey] = []
        for keys_type in keys_types:
            current_page = 1
            for _ in range(_MAX_KEYS_PAGES):
                paged = await self.get_paged_keys(
                    per_page=per_page,
                    current_page=current_page,
                    keys_type=keys_type,
                )
                for item in paged.results:
                    key = DoorKey.model_validate(item)
                    key.raw = item
                    result.append(key)

                effective_per_page = paged.per_page if paged.per_page > 0 else per_page
                if paged.total > 0:
                    total_pages = max(
                        1,
                        (paged.total + effective_per_page - 1) // effective_per_page,
                    )
                    if paged.current_page >= total_pages:
                        break
                elif len(paged.results) < effective_per_page:
                    break

                current_page = max(current_page + 1, paged.current_page + 1)
            else:
                logger.warning(
                    "Stopped key pagination at safety limit: keysType=%s pages=%s",
                    keys_type,
                    _MAX_KEYS_PAGES,
                )
        return result

    async def get_doors(self) -> list[DoorKey]:
        doors_by_id: dict[str, DoorKey] = {}
        order: list[str] = []

        for key in await self.get_all_keys():
            door_id = key.door_id
            existing = doors_by_id.get(door_id)
            if existing is None:
                doors_by_id[door_id] = key
                order.append(door_id)
                continue

            updates: dict[str, Any] = {}
            if not existing.name and key.name:
                updates["name"] = key.name
            for field_name in (
                "domofon_public_pin",
                "http_video_url",
                "webrtc_video_url",
                "video_preview",
            ):
                if not getattr(existing, field_name) and getattr(key, field_name):
                    updates[field_name] = getattr(key, field_name)
            if key.raw:
                updates["raw"] = {**key.raw, **existing.raw}

            if updates:
                doors_by_id[door_id] = existing.model_copy(update=updates)

        return [doors_by_id[door_id] for door_id in order]

    async def get_user_key(self, key_id: str) -> DoorKey | None:
        payload = {"keyId": key_id}
        data = await self._request(
            "POST",
            "/client-api/Key/GetUserKey",
            payload=payload,
            need_auth=True,
        )
        if isinstance(data, str) or _has_api_error(data):
            return None
        key = DoorKey.model_validate(data)
        key.raw = data
        return key

    # --- Door control ---

    async def open_door(self, door_id: str) -> bool:
        payload = {"doorId": door_id}
        data = await self._request(
            "POST",
            "/client-api/Device/OpenRelayByDoorId",
            payload=payload,
            need_auth=True,
            expect_text=True,
        )
        return isinstance(data, str)

    async def open_door_by_key(self, key_id: str) -> bool:
        payload = {"keyId": key_id}
        data = await self._request(
            "POST",
            "/client-api/Device/OpenRelayByKeyId",
            payload=payload,
            need_auth=True,
            expect_text=True,
        )
        return isinstance(data, str)

    # --- Call logs ---

    async def get_call_logs_page(
        self,
        per_page: int = 20,
        current_page: int = 1,
        missed_calls: bool = False,
    ) -> CallLogPage:
        payload = {
            "currentPage": current_page,
            "perPage": per_page,
            "missedCalls": missed_calls,
        }
        data = await self._request(
            "POST",
            "/client-api/CallLog/GetCallLogs",
            payload=payload,
            need_auth=True,
        )
        if isinstance(data, str):
            raise ApiError(f"Unexpected text response: {data}")

        entries: list[CallLogEntry] = []
        for item in data.get("results", []):
            entry = CallLogEntry.model_validate(item)
            entry.raw = item
            entries.append(entry)

        return CallLogPage(
            entries=entries,
            current_page=data.get("currentPage", current_page),
            per_page=data.get("perPage", per_page),
            total=data.get("total", 0),
        )

    async def get_call_logs(
        self,
        per_page: int = 20,
        current_page: int = 1,
        missed_calls: bool = False,
    ) -> list[CallLogEntry]:
        page = await self.get_call_logs_page(
            per_page=per_page,
            current_page=current_page,
            missed_calls=missed_calls,
        )
        return page.entries

    async def find_call_log(
        self,
        call_id: str,
        *,
        per_page: int = 50,
        max_pages: int = _MAX_CALL_LOG_PAGES,
    ) -> CallLogEntry | None:
        current_page = 1
        for _ in range(max_pages):
            page = await self.get_call_logs_page(
                per_page=per_page,
                current_page=current_page,
                missed_calls=False,
            )
            entry = next((item for item in page.entries if item.call_id == call_id), None)
            if entry is not None:
                return entry

            if current_page >= page.total_pages:
                return None
            current_page += 1

        logger.warning(
            "Stopped call-log lookup at safety limit: call_id=%s pages=%s",
            call_id,
            max_pages,
        )
        return None

    # --- Calls ---

    async def answer_call(self, call_id: str) -> bool:
        payload = {"callId": call_id}
        data = await self._request(
            "POST",
            "/communication-api/Call/NotifyCallAnswered",
            payload=payload,
            need_auth=True,
            expect_text=True,
        )
        return isinstance(data, str)

    async def end_call(self, call_id: str) -> bool:
        payload = {"callId": call_id}
        data = await self._request(
            "POST",
            "/communication-api/Call/NotifyCallEnded",
            payload=payload,
            need_auth=True,
            expect_text=True,
        )
        return isinstance(data, str)

    # --- Fetch external resource (for media) ---

    async def fetch_external_bytes(
        self,
        url: str,
        *,
        authorized: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if authorized:
            if not self.access_token:
                return {"ok": False, "error": "No access token available", "body": b""}
            await self._ensure_alive()
            if not self.access_token:
                return {"ok": False, "error": "Session expired", "body": b""}

        request_headers = dict(extra_headers or {})
        if authorized and self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"

        first_try_access_token = self.access_token

        try:
            resp = await self._http.get(url, headers=request_headers)
            if resp.status_code == 401 and authorized and bool(self.refresh_token):
                if await self._try_refresh(first_try_access_token):
                    if self.access_token:
                        request_headers["Authorization"] = f"Bearer {self.access_token}"
                    resp = await self._http.get(url, headers=request_headers)

            body = resp.read()
            if resp.is_success:
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "body": body,
                    "content_type": resp.headers.get("Content-Type"),
                }
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}",
                "status": resp.status_code,
                "body": body[:2000],
            }
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc), "body": b""}
