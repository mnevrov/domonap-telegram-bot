from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    storage_path: str = "data/storage.db"
    log_level: str = "INFO"
    call_watcher_enabled: bool = True

    @property
    def storage_path_resolved(self) -> Path:
        return Path(self.storage_path).resolve()
