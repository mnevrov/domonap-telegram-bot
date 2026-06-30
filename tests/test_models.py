from datetime import datetime

from domonap_bot.domonap.models import (
    AuthSession,
    CallLogEntry,
    DoorKey,
    IncomingCallPayload,
    PagedResponse,
    TokenData,
)


class TestDoorKey:
    def test_full_parsing(self) -> None:
        raw = {
            "id": "key_123",
            "doorId": "door_456",
            "name": "Main Entrance",
            "domofonPublicPin": "1234",
            "httpVideoUrl": "https://example.com/video",
            "webrtcVideoUrl": "https://example.com/webrtc",
            "videoPreview": "https://example.com/preview",
        }
        key = DoorKey(**raw)
        assert key.id == "key_123"
        assert key.door_id == "door_456"
        assert key.name == "Main Entrance"
        assert key.domofon_public_pin == "1234"
        assert key.http_video_url == "https://example.com/video"
        assert key.webrtc_video_url == "https://example.com/webrtc"
        assert key.video_preview == "https://example.com/preview"

    def test_empty_pin_becomes_none(self) -> None:
        key = DoorKey(id="k1", door_id="d1", name="Door", domofon_public_pin="")
        assert key.domofon_public_pin is None

    def test_missing_pin_becomes_none(self) -> None:
        key = DoorKey(id="k1", door_id="d1", name="Door")
        assert key.domofon_public_pin is None

    def test_minimal_fields(self) -> None:
        key = DoorKey(id="k1", door_id="d1", name="Minimal")
        assert key.domofon_public_pin is None
        assert key.http_video_url is None
        assert key.webrtc_video_url is None
        assert key.video_preview is None


class TestCallLogEntry:
    def test_full_parsing(self) -> None:
        raw = {
            "callId": "call_001",
            "doorId": "door_456",
            "caller": "+79991234567",
            "callTime": "2024-06-15T14:30:00.000000+03:00",
            "answered": True,
            "photoUrl": "https://example.com/photo.jpg",
        }
        entry = CallLogEntry(**raw)
        assert entry.call_id == "call_001"
        assert entry.door_id == "door_456"
        assert entry.caller == "+79991234567"
        assert entry.answered is True
        assert entry.photo_url == "https://example.com/photo.jpg"
        assert isinstance(entry.call_time, datetime)
        assert entry.call_time.tzinfo is not None

    def test_unanswered_call(self) -> None:
        entry = CallLogEntry(call_id="c1", answered=False)
        assert entry.answered is False

    def test_missing_call_time(self) -> None:
        entry = CallLogEntry(call_id="c1")
        assert entry.call_time is None

    def test_empty_call_time(self) -> None:
        entry = CallLogEntry(call_id="c1", call_time="")
        assert entry.call_time is None

    def test_none_call_time(self) -> None:
        entry = CallLogEntry(call_id="c1", call_time=None)
        assert entry.call_time is None

    def test_iso_format_no_tz(self) -> None:
        entry = CallLogEntry(
            call_id="c1",
            call_time="2024-06-15T14:30:00",
        )
        assert isinstance(entry.call_time, datetime)
        assert entry.call_time.year == 2024

    def test_z_suffix(self) -> None:
        entry = CallLogEntry(
            call_id="c1",
            call_time="2024-06-15T14:30:00Z",
        )
        assert isinstance(entry.call_time, datetime)
        assert entry.call_time.tzinfo is not None

    def test_default_raw(self) -> None:
        entry = CallLogEntry(call_id="c1")
        assert entry.raw == {}

    def test_missing_fields_defaults(self) -> None:
        entry = CallLogEntry(call_id="c1")
        assert entry.door_id is None
        assert entry.caller is None
        assert entry.answered is False
        assert entry.photo_url is None


class TestIncomingCallPayload:
    def test_full_parsing(self) -> None:
        raw = {
            "CallId": "call_001",
            "DoorId": "door_456",
            "VideoPreview": "https://example.com/video",
            "PhotoUrl": "https://example.com/photo",
            "Body": "Doorbell rang",
            "Title": "Main Entrance",
            "Address": "ул. Ленина, д. 1",
        }
        payload = IncomingCallPayload(**raw)
        assert payload.call_id == "call_001"
        assert payload.door_id == "door_456"
        assert payload.video_preview == "https://example.com/video"
        assert payload.photo_url == "https://example.com/photo"
        assert payload.body == "Doorbell rang"
        assert payload.title == "Main Entrance"
        assert payload.address == "ул. Ленина, д. 1"

    def test_missing_fields(self) -> None:
        payload = IncomingCallPayload(call_id="c1")
        assert payload.door_id is None
        assert payload.video_preview is None
        assert payload.photo_url is None
        assert payload.body is None
        assert payload.title is None
        assert payload.address is None


class TestAuthSession:
    def test_full_session(self) -> None:
        session = AuthSession(
            access_token="at_123",
            refresh_token="rt_456",
            refresh_expiration_date="2024-07-15T14:30:00+03:00",
            phone="+79991234567",
            device_token="dt_789",
            instance_id="ii_000",
        )
        assert session.access_token == "at_123"
        assert session.refresh_token == "rt_456"
        assert session.refresh_expiration_date == "2024-07-15T14:30:00+03:00"
        assert session.phone == "+79991234567"
        assert session.device_token == "dt_789"
        assert session.instance_id == "ii_000"

    def test_minimal_session(self) -> None:
        session = AuthSession()
        assert session.access_token is None
        assert session.refresh_token is None
        assert session.refresh_expiration_date is None
        assert session.phone == ""
        assert session.device_token == ""
        assert session.instance_id == ""


class TestTokenData:
    def test_creation(self) -> None:
        td = TokenData(
            access_token="at",
            refresh_token="rt",
            refresh_expiration_date="2024-07-01T00:00:00Z",
        )
        assert td.access_token == "at"
        assert td.refresh_token == "rt"
        assert td.refresh_expiration_date == "2024-07-01T00:00:00Z"


class TestPagedResponse:
    def test_defaults(self) -> None:
        pr = PagedResponse()
        assert pr.results == []
        assert pr.current_page == 1
        assert pr.per_page == 100
        assert pr.total == 0

    def test_with_results(self) -> None:
        pr = PagedResponse(
            results=[{"id": "1"}, {"id": "2"}],
            current_page=1,
            per_page=10,
            total=2,
        )
        assert len(pr.results) == 2
        assert pr.total == 2
