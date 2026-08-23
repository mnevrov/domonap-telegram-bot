from domonap_bot.domonap.protocol import CURRENT_PROFILE


def test_profile_is_bound_to_current_public_release() -> None:
    assert CURRENT_PROFILE.source_app_version_code == 9850
    assert CURRENT_PROFILE.base_url == "https://api.domonap.ru"
    assert CURRENT_PROFILE.trusted_host == "api.domonap.ru"
    assert CURRENT_PROFILE.verification == "apk-verified-partial-static"


def test_readonly_profile_excludes_physical_and_call_mutations() -> None:
    readonly_paths = {item.path for item in CURRENT_PROFILE.readonly_endpoints}

    assert "/client-api/Device/OpenRelayByDoorId" not in readonly_paths
    assert "/client-api/Device/OpenRelayByKeyId" not in readonly_paths
    assert "/communication-api/Call/NotifyCallAnswered" not in readonly_paths
    assert "/communication-api/Call/NotifyCallEnded" not in readonly_paths
    assert "/sso-api/Authorization/UpdateDeviceToken" not in readonly_paths


def test_known_signalr_contract_is_explicit() -> None:
    assert CURRENT_PROFILE.signalr_hub == "/notificationHub"
    assert CURRENT_PROFILE.signalr_target == "ReceivePush"
    assert set(CURRENT_PROFILE.signalr_events) == {
        "DomofonCalling",
        "DomofonCallAnswered",
        "DomofonCallEnded",
    }
