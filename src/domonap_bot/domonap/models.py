from datetime import datetime

from pydantic import BaseModel, field_validator


class Door(BaseModel):
    id: str
    name: str
    building: str | None = None
    flat: str | None = None


class CallLogEntry(BaseModel):
    id: str
    door_id: str
    caller: str | None = None
    timestamp: datetime
    answered: bool = False

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: str | datetime) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v


class AuthSession(BaseModel):
    token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    phone: str = ""


class LoginCodeResponse(BaseModel):
    session_id: str
    retry_after: int = 30
