from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_user_ids(v: Any) -> list[int]:
    if isinstance(v, list):
        return [int(item) for item in v]
    if isinstance(v, (int, float)):
        return [int(v)]
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return []
        if v.startswith("[") and v.endswith("]"):
            parsed = json.loads(v)
            if not isinstance(parsed, list):
                return []
            return [int(item) for item in parsed]
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    return []


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    allowed_telegram_user_ids: list[int] = []
    admin_telegram_user_ids: list[int] = []
    domonap_phone: str = ""
    domonap_register_device_token: bool = False
    storage_path: str = "data/storage.db"
    storage_encryption_key: SecretStr | None = None
    log_level: str = "INFO"
    call_watcher_enabled: bool = True
    public_base_url: str = ""
    camera_proxy_secret: SecretStr | None = None
    camera_proxy_port: int = 8080
    camera_link_ttl_seconds: int = 300

    @field_validator("allowed_telegram_user_ids", "admin_telegram_user_ids", mode="before")
    @classmethod
    def coerce_user_ids(cls, v: Any) -> list[int]:
        return _parse_user_ids(v)

    @model_validator(mode="after")
    def validate_access_control_ids(self) -> "Settings":
        for field_name, user_ids in (
            ("ALLOWED_TELEGRAM_USER_IDS", self.allowed_telegram_user_ids),
            ("ADMIN_TELEGRAM_USER_IDS", self.admin_telegram_user_ids),
        ):
            if any(user_id <= 0 for user_id in user_ids):
                raise ValueError(f"{field_name} must contain only positive Telegram user IDs")

        allowed = set(self.allowed_telegram_user_ids)
        unexpected_admins = sorted(set(self.admin_telegram_user_ids) - allowed)
        if unexpected_admins:
            raise ValueError(
                "ADMIN_TELEGRAM_USER_IDS must be a subset of ALLOWED_TELEGRAM_USER_IDS; "
                f"not allowed: {unexpected_admins}"
            )
        if self.camera_proxy_port not in range(1, 65536):
            raise ValueError("CAMERA_PROXY_PORT must be between 1 and 65535")
        if self.camera_link_ttl_seconds <= 0:
            raise ValueError("CAMERA_LINK_TTL_SECONDS must be positive")
        return self

    @property
    def storage_path_resolved(self) -> Path:
        return Path(self.storage_path).resolve()
