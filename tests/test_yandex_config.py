import pytest
from pydantic import ValidationError

from domonap_bot.config import Settings


def base_settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "telegram_bot_token": "telegram-token",
        "allowed_telegram_user_ids": [1],
    }
    values.update(overrides)
    return values


def test_yandex_features_are_disabled_and_dry_run_by_default() -> None:
    settings = Settings(**base_settings())  # type: ignore[arg-type]

    assert settings.yandex_announcements_enabled is False
    assert settings.yandex_smart_home_enabled is False
    assert settings.yandex_smart_home_dry_run is True


def test_yandex_features_require_live_call_watcher() -> None:
    with pytest.raises(ValidationError, match="CALL_WATCHER_ENABLED"):
        Settings(  # type: ignore[call-arg]
            **base_settings(
                call_watcher_enabled=False,
                yandex_announcements_enabled=True,
                yandex_iot_oauth_token="iot-token",
                yandex_scenario_map={"door-1": "scenario-1"},
            )
        )


def test_announcements_require_token_and_door_mapping() -> None:
    with pytest.raises(ValidationError, match="YANDEX_IOT_OAUTH_TOKEN"):
        Settings(  # type: ignore[call-arg]
            **base_settings(
                yandex_announcements_enabled=True,
                yandex_scenario_map={"door-1": "scenario-1"},
            )
        )

    with pytest.raises(ValidationError, match="YANDEX_SCENARIO_MAP"):
        Settings(  # type: ignore[call-arg]
            **base_settings(
                yandex_announcements_enabled=True,
                yandex_iot_oauth_token="iot-token",
            )
        )


def test_smart_home_requires_pinned_oauth_client_and_user() -> None:
    with pytest.raises(ValidationError, match="YANDEX_ID_OAUTH_CLIENT_ID"):
        Settings(  # type: ignore[call-arg]
            **base_settings(
                yandex_smart_home_enabled=True,
                yandex_allowed_user_ids=["123"],
            )
        )

    with pytest.raises(ValidationError, match="YANDEX_ALLOWED_USER_IDS"):
        Settings(  # type: ignore[call-arg]
            **base_settings(
                yandex_smart_home_enabled=True,
                yandex_id_oauth_client_id="client-1",
            )
        )


def test_yandex_string_maps_and_user_ids_accept_env_shapes() -> None:
    settings = Settings(  # type: ignore[call-arg]
        **base_settings(
            yandex_scenario_map='{"door-1":"scenario-1"}',
            yandex_allowed_user_ids="123,456",
        )
    )

    assert settings.yandex_scenario_map == {"door-1": "scenario-1"}
    assert settings.yandex_allowed_user_ids == ["123", "456"]
