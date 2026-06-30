from dataclasses import dataclass, field
from datetime import datetime

from domonap_bot.domonap.models import IncomingCallPayload


@dataclass
class IncomingCall:
    call_id: str
    door_id: str
    caller: str | None = None
    video_preview: str | None = None
    photo_url: str | None = None
    body: str | None = None
    title: str | None = None
    address: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_payload(cls, payload: IncomingCallPayload) -> "IncomingCall":
        return cls(
            call_id=payload.call_id,
            door_id=payload.door_id or "",
            video_preview=payload.video_preview,
            photo_url=payload.photo_url,
            body=payload.body,
            title=payload.title,
            address=payload.address,
        )


@dataclass
class DoorbellRing:
    door_id: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AuthCodeRequested:
    phone: str
    session_id: str
    retry_after: int = 30
