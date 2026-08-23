import pytest
from pydantic import ValidationError

from domonap_bot.config import Settings


def make_settings(**kwargs: object) -> Settings:
    return Settings(telegram_bot_token="test-token", _env_file=None, **kwargs)  # type: ignore[arg-type]


def test_access_control_accepts_admin_subset() -> None:
    settings = make_settings(
        allowed_telegram_user_ids=[100, 200],
        admin_telegram_user_ids=[200],
    )

    assert settings.allowed_telegram_user_ids == [100, 200]
    assert settings.admin_telegram_user_ids == [200]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("allowed_telegram_user_ids", [0]),
        ("allowed_telegram_user_ids", [-1]),
        ("admin_telegram_user_ids", [0]),
        ("admin_telegram_user_ids", [-1]),
    ],
)
def test_access_control_rejects_non_positive_ids(field_name: str, value: list[int]) -> None:
    kwargs: dict[str, object] = {
        "allowed_telegram_user_ids": [100],
        "admin_telegram_user_ids": [],
    }
    kwargs[field_name] = value

    with pytest.raises(ValidationError, match="positive Telegram user IDs"):
        make_settings(**kwargs)


def test_access_control_rejects_admin_outside_allow_list() -> None:
    with pytest.raises(ValidationError, match="must be a subset"):
        make_settings(
            allowed_telegram_user_ids=[100],
            admin_telegram_user_ids=[200],
        )
