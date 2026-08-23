from cryptography.fernet import Fernet

from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.tokens import (
    KEY_ACCESS_TOKEN,
    KEY_PHONE,
    KEY_REFRESH_TOKEN,
    TokenStorage,
    TokenStorageEncryptionError,
)
from tests.test_client import FakeStorage


async def test_session_values_are_encrypted_at_rest() -> None:
    storage = FakeStorage()
    key = Fernet.generate_key().decode()
    tokens = TokenStorage(storage, encryption_key=key)
    session = AuthSession(
        access_token="access-secret-marker",
        refresh_token="refresh-secret-marker",
        refresh_expiration_date="2027-01-01T00:00:00+00:00",
        device_token="device-secret-marker",
        instance_id="instance-secret-marker",
        phone="+79991234567",
    )

    await tokens.save(session)

    assert storage._data[KEY_ACCESS_TOKEN].startswith("fernet:v1:")
    assert storage._data[KEY_REFRESH_TOKEN].startswith("fernet:v1:")
    assert storage._data[KEY_PHONE].startswith("fernet:v1:")
    serialized = "\n".join(storage._data.values())
    assert "access-secret-marker" not in serialized
    assert "refresh-secret-marker" not in serialized
    assert "+79991234567" not in serialized
    assert await tokens.load_full() == session


async def test_plaintext_session_is_migrated_on_load() -> None:
    storage = FakeStorage()
    storage._data[KEY_ACCESS_TOKEN] = "legacy-access"
    storage._data[KEY_REFRESH_TOKEN] = "legacy-refresh"
    storage._data[KEY_PHONE] = "+79991234567"
    tokens = TokenStorage(storage, encryption_key=Fernet.generate_key().decode())

    session = await tokens.load_full()

    assert session is not None
    assert session.access_token == "legacy-access"
    assert session.refresh_token == "legacy-refresh"
    assert session.phone == "+79991234567"
    assert storage._data[KEY_ACCESS_TOKEN].startswith("fernet:v1:")
    assert storage._data[KEY_REFRESH_TOKEN].startswith("fernet:v1:")
    assert storage._data[KEY_PHONE].startswith("fernet:v1:")
    assert "legacy-access" not in storage._data[KEY_ACCESS_TOKEN]


async def test_wrong_key_fails_closed() -> None:
    storage = FakeStorage()
    first = TokenStorage(storage, encryption_key=Fernet.generate_key().decode())
    await first.save(AuthSession(access_token="access-secret"))
    second = TokenStorage(storage, encryption_key=Fernet.generate_key().decode())

    try:
        await second.load_full()
    except TokenStorageEncryptionError:
        pass
    else:
        raise AssertionError("wrong encryption key must not return session data")


async def test_encrypted_session_requires_key() -> None:
    storage = FakeStorage()
    encrypted = TokenStorage(storage, encryption_key=Fernet.generate_key().decode())
    await encrypted.save(AuthSession(access_token="access-secret"))
    keyless = TokenStorage(storage)

    try:
        await keyless.load()
    except TokenStorageEncryptionError:
        pass
    else:
        raise AssertionError("encrypted session must not be readable without a key")


async def test_ciphertext_is_bound_to_storage_field() -> None:
    storage = FakeStorage()
    tokens = TokenStorage(storage, encryption_key=Fernet.generate_key().decode())
    await tokens.save(
        AuthSession(access_token="access-secret", refresh_token="refresh-secret")
    )
    storage._data[KEY_ACCESS_TOKEN], storage._data[KEY_REFRESH_TOKEN] = (
        storage._data[KEY_REFRESH_TOKEN],
        storage._data[KEY_ACCESS_TOKEN],
    )

    try:
        await tokens.load_full()
    except TokenStorageEncryptionError:
        pass
    else:
        raise AssertionError("ciphertext moved between fields must be rejected")
