from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.base import Storage

KEY_SESSION = "domonap_session_v2"
KEY_ACCESS_TOKEN = "domonap_access_token"
KEY_REFRESH_TOKEN = "domonap_refresh_token"
KEY_REFRESH_EXPIRATION = "domonap_refresh_expiration"
KEY_DEVICE_TOKEN = "domonap_device_token"
KEY_INSTANCE_ID = "domonap_instance_id"
KEY_PHONE = "domonap_phone"

_FERNET_PREFIX = "fernet:v1:"
_LEGACY_SESSION_KEYS = (
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

    async def _delete_legacy_values(self) -> None:
        for key in _LEGACY_SESSION_KEYS:
            await self._storage.delete(key)

    async def save(self, session: AuthSession) -> None:
        """Persist the complete session as one authenticated record.

        Writing the packed record first makes refresh-token rotation crash-safe: readers
        either observe the previous complete record or the new complete record, never a
        mixture of independently committed fields. Legacy keys are removed only after the
        new record is durable.
        """
        serialized = session.model_dump_json()
        await self._storage.set(KEY_SESSION, self._encrypt_value(KEY_SESSION, serialized))
        await self._delete_legacy_values()

    async def _load_packed(self) -> AuthSession | None:
        encoded = await self._storage.get(KEY_SESSION)
        if encoded is None:
            return None

        serialized, needs_encryption = self._decrypt_value(KEY_SESSION, encoded)
        if serialized is None:
            return None
        try:
            session = AuthSession.model_validate_json(serialized)
        except (ValidationError, ValueError) as exc:
            raise TokenStorageEncryptionError("Persisted Domonap session payload is invalid") from exc

        if needs_encryption and self._fernet is not None:
            await self.save(session)
        return session if session.access_token else None

    async def _load_legacy(self) -> AuthSession | None:
        decoded: dict[str, str | None] = {}
        for key in _LEGACY_SESSION_KEYS:
            value, _ = self._decrypt_value(key, await self._storage.get(key))
            decoded[key] = value

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
        await self.save(session)
        return session

    async def load(self) -> str | None:
        session = await self.load_full()
        return session.access_token if session is not None else None

    async def load_full(self) -> AuthSession | None:
        packed = await self._load_packed()
        if packed is not None:
            return packed
        return await self._load_legacy()

    async def load_refresh(self) -> str | None:
        session = await self.load_full()
        return session.refresh_token if session is not None else None

    async def clear(self) -> None:
        # Delete legacy records first and the authoritative packed record last. A crash
        # during cleanup can therefore leave the current complete session in place, but
        # cannot resurrect an older legacy token set after KEY_SESSION is removed.
        await self._delete_legacy_values()
        await self._storage.delete(KEY_SESSION)
