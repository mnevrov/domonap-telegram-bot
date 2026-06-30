from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IncomingCall:
    door_id: str
    caller: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DoorbellRing:
    door_id: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AuthCodeRequested:
    phone: str
    session_id: str
    retry_after: int = 30
