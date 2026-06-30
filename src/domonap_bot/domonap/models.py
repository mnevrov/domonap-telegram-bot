from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    refresh_expiration_date: str


class AuthSession(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    refresh_expiration_date: str | None = None
    phone: str = ""
    device_token: str = ""
    instance_id: str = ""


class DoorKey(BaseModel):
    id: str
    door_id: str = Field(alias="doorId")
    name: str
    domofon_public_pin: str | None = Field(default=None, alias="domofonPublicPin")
    http_video_url: str | None = Field(default=None, alias="httpVideoUrl")
    webrtc_video_url: str | None = Field(default=None, alias="webrtcVideoUrl")
    video_preview: str | None = Field(default=None, alias="videoPreview")
    raw: dict[str, Any] = {}

    model_config = {"populate_by_name": True}

    @field_validator("domofon_public_pin", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: object) -> str | None:
        if v == "" or v is None:
            return None
        return str(v)


class CallLogEntry(BaseModel):
    call_id: str = Field(alias="callId")
    door_id: str | None = Field(default=None, alias="doorId")
    caller: str | None = None
    call_time: datetime | None = Field(default=None, alias="callTime")
    answered: bool = False
    photo_url: str | None = Field(default=None, alias="photoUrl")
    raw: dict[str, Any] = {}

    model_config = {"populate_by_name": True}

    @field_validator("call_time", mode="before")
    @classmethod
    def parse_call_time(cls, v: object) -> datetime | None:
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class IncomingCallPayload(BaseModel):
    call_id: str = Field(alias="CallId")
    door_id: str | None = Field(default=None, alias="DoorId")
    video_preview: str | None = Field(default=None, alias="VideoPreview")
    photo_url: str | None = Field(default=None, alias="PhotoUrl")
    body: str | None = Field(default=None, alias="Body")
    title: str | None = Field(default=None, alias="Title")
    address: str | None = Field(default=None, alias="Address")
    raw: dict[str, Any] = {}

    model_config = {"populate_by_name": True}


class PagedResponse(BaseModel):
    results: list[dict[str, Any]] = []
    current_page: int = 1
    per_page: int = 100
    total: int = 0
