from domonap_bot.tools.api_probe import READ_ONLY_PROBES


def test_live_canary_contains_only_non_mutating_paths() -> None:
    paths = {probe.path for probe in READ_ONLY_PROBES}

    assert paths == {
        "/sso-api/User/GetUser",
        "/client-api/Key/GetPagedKeysByKeysType",
        "/client-api/CallLog/GetCallLogs",
    }

    forbidden_fragments = (
        "Authorize",
        "RefreshToken",
        "UpdateDeviceToken",
        "OpenRelay",
        "NotifyCallAnswered",
        "NotifyCallEnded",
    )
    for path in paths:
        assert not any(fragment in path for fragment in forbidden_fragments)
