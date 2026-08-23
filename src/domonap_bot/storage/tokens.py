from cryptography.fernet import Fernet, InvalidToken

from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.base import Storage

KEY_ACCESS_TOKEN = "domonap_access_token"
KEY_REFRESH_TOKEN = "domonap_refresh_token"
KEY_REFRESH_EXPIRATION = "domonap_refresh_expiration"
KEY_DEVICE_TOKEN = "domonap_device_token"
KEY_INSTANCE_ID = "domonap_instance_id"
KEY_PHONE = "domonap_phone"

_FERNET_PREFIX = "fernet:v1:"
_SESSION_KEYS = (
    KEY_ACCESS_TOKEN,
    KEY_REFRESH_TOKEN,
    KEY_REFRESH_EXPIRATION,
    KEY_DEVICE_TOKEN,
    KEY_INSTANCE_ID,
    KEY_PHONE,
)


class TokenStorageEncryptionError(RuntimeError):
    """Persisted session data cannot be safely decrypted."""


class TokenStorage:
    def __init__(self, storage: Storage, encryption_key: str | None = None) -> None:
        self._storage = storage
        self._fernet: Fernet | None = None
        if encryption_key:
            try:
                self._fernet = Fernet(encryption_key.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise ValueError("STORAGE_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def _encrypt_value(self, key: str, value: str) -> str:
        if self._fernet is None:
            return value
        plaintext = f"{key}\0{value}".encode()
        encrypted = self._fernet.encrypt(plaintext).decode("ascii")
        return f"{_FERNET_PREFIX}{encrypted}"

    def _decrypt_value(self, key: str, value: str | None) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        if not value.startswith(_FERNET_PREFIX):
            return value, self._fernet is not None
        if self._fernet is None:
            raise TokenStorageEncryptionError(
                "Persisted Domonap session is encrypted but no storage encryption key is configured"
            )

        encrypted = value.removeprefix(_FERNET_PREFIX)
        try:
            plaintext = self._fernet.decrypt(encrypted.encode("ascii")).decode()
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise TokenStorageEncryptionError(
                "Persisted Domonap session cannot be decrypted with the configured key"
            ) from exc

        field_name, separator, field_value = plaintext.partition("\0")
        if separator != "\0" or field_name != key:
            raise TokenStorageEncryptionError("Persisted Domonap session field binding is invalid")
        return field_value, False

    async def _save_value(self, key: str, value: str | None) -> None:
        if value:
            await self._storage.set(key, self._encrypt_value(key, value))

    async def save(self, session: AuthSession) -> None:
        await self._save_value(KEY_ACCESS_TOKEN, session.access_token)
        await self._save_value(KEY_REFRESH_TOKEN, session.refresh_token)
        await self._save_value(KEY_REFRESH_EXPIRATION, session.refresh_expiration_date)
        await self._save_value(KEY_DEVICE_TOKEN, session.device_token)
        await self._save_value(KEY_INSTANCE_ID, session.instance_id)
        await self._save_value(KEY_PHONE, session.phone)

    async def load(self) -> str | None:
        value, _ = self._decrypt_value(
            KEY_ACCESS_TOKEN, await self._storage.get(KEY_ACCESS_TOKEN)
        )
        return value

    async def load_full(self) -> AuthSession | None:
        decoded: dict[str, str | None] = {}
        needs_migration = False
        for key in _SESSION_KEYS:
            value, legacy_plaintext = self._decrypt_value(key, await self._storage.get(key))
            decoded[key] = value
            needs_migration = needs_migration or legacy_plaintext

        access = decoded[KEY_ACCESS_TOKEN]
        if not access:
            return None

        session = AuthSession(
            access_token=access,
            refresh_token=decoded[KEY_REFRESH_TOKEN],
            refresh_expiration_date=decoded[KEY_REFRESH_EXPIRATION],
            device_token=decoded[KEY_DEVICE_TOKEN] or "",
            instance_id=decoded[KEY_INSTANCE_ID] or "",
            phone=decoded[KEY_PHONE] or "",
        )
        if needs_migration and self._fernet is not None:
            await self.save(session)
        return session

    async def load_refresh(self) -> str | None:
        value, _ = self._decrypt_value(
            KEY_REFRESH_TOKEN, await self._storage.get(KEY_REFRESH_TOKEN)
        )
        return value

    async def clear(self) -> None:
        await self._storage.delete(KEY_ACCESS_TOKEN)
        await self._storage.delete(KEY_REFRESH_TOKEN)
        await self._storage.delete(KEY_REFRESH_EXPIRATION)
        await self._storage.delete(KEY_DEVICE_TOKEN)
        await self._storage.delete(KEY_INSTANCE_ID)
        await self._storage.delete(KEY_PHONE)
