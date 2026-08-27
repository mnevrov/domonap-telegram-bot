from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
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


def _parse_string_ids(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(item).strip() for item in v if str(item).strip()]
    if isinstance(v, (int, float)):
        return [str(v)]
    if isinstance(v, str):
        value = v.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                return []
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_string_map(v: Any) -> dict[str, str]:
    if v is None or v == "":
        return {}
    if isinstance(v, dict):
        return {
            str(key).strip(): str(value).strip()
            for key, value in v.items()
            if str(key).strip() and str(value).strip()
        }
    if isinstance(v, str):
        parsed = json.loads(v)
        if not isinstance(parsed, dict):
            raise ValueError("YANDEX_SCENARIO_MAP must be a JSON object")
        return {
            str(key).strip(): str(value).strip()
            for key, value in parsed.items()
            if str(key).strip() and str(value).strip()
        }
    raise ValueError("YANDEX_SCENARIO_MAP must be a JSON object")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    allowed_telegram_user_ids: list[int] = Field(default_factory=list)
    admin_telegram_user_ids: list[int] = Field(default_factory=list)
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

    # Domonap -> Alice: run a preconfigured Yandex Smart Home scenario for a live call.
    yandex_announcements_enabled: bool = False
    yandex_iot_oauth_token: SecretStr | None = None
    yandex_scenario_map: dict[str, str] = Field(default_factory=dict)

    # Alice -> Domonap: private Smart Home provider for the current live call only.
    yandex_smart_home_enabled: bool = False
    yandex_smart_home_dry_run: bool = True
    yandex_smart_home_port: int = 8081
    yandex_active_call_ttl_seconds: int = 60
    yandex_id_oauth_client_id: str = ""
    yandex_allowed_user_ids: list[str] = Field(default_factory=list)

    @field_validator("allowed_telegram_user_ids", "admin_telegram_user_ids", mode="before")
    @classmethod
    def coerce_user_ids(cls, v: Any) -> list[int]:
        return _parse_user_ids(v)

    @field_validator("yandex_allowed_user_ids", mode="before")
    @classmethod
    def coerce_yandex_user_ids(cls, v: Any) -> list[str]:
        return _parse_string_ids(v)

    @field_validator("yandex_scenario_map", mode="before")
    @classmethod
    def coerce_yandex_scenario_map(cls, v: Any) -> dict[str, str]:
        return _parse_string_map(v)

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

        if self.yandex_announcements_enabled:
            token = (
                self.yandex_iot_oauth_token.get_secret_value().strip()
                if self.yandex_iot_oauth_token is not None
                else ""
            )
            if not token:
                raise ValueError(
                    "YANDEX_IOT_OAUTH_TOKEN is required when YANDEX_ANNOUNCEMENTS_ENABLED=true"
                )
            if not self.yandex_scenario_map:
                raise ValueError(
                    "YANDEX_SCENARIO_MAP must not be empty when YANDEX_ANNOUNCEMENTS_ENABLED=true"
                )

        if self.yandex_smart_home_port not in range(1, 65536):
            raise ValueError("YANDEX_SMART_HOME_PORT must be between 1 and 65535")
        if self.yandex_active_call_ttl_seconds <= 0:
            raise ValueError("YANDEX_ACTIVE_CALL_TTL_SECONDS must be positive")
        if self.yandex_smart_home_enabled:
            if not self.yandex_id_oauth_client_id.strip():
                raise ValueError(
                    "YANDEX_ID_OAUTH_CLIENT_ID is required when YANDEX_SMART_HOME_ENABLED=true"
                )
            if not self.yandex_allowed_user_ids:
                raise ValueError(
                    "YANDEX_ALLOWED_USER_IDS must not be empty when YANDEX_SMART_HOME_ENABLED=true"
                )
            camera_secret = (
                self.camera_proxy_secret.get_secret_value().strip()
                if self.camera_proxy_secret is not None
                else ""
            )
            if (
                self.public_base_url
                and camera_secret
                and self.yandex_smart_home_port == self.camera_proxy_port
            ):
                raise ValueError(
                    "YANDEX_SMART_HOME_PORT and CAMERA_PROXY_PORT must differ when both servers are enabled"
                )
        return self

    @property
    def storage_path_resolved(self) -> Path:
        return Path(self.storage_path).resolve()
