from pathlib import Path

from domonap_bot.tools.apk_extract import extract_contract
from domonap_bot.tools.contract_diff import compare_contracts
from domonap_bot.tools.release_watch import build_report


def test_release_report_detects_newer_version() -> None:
    metadata = {
        "package_name": "com.domonap.app",
        "version_code": 9851,
        "version_name": "9851",
        "updated_at": "2026-08-24T00:00:00Z",
    }
    baseline = {"source": {"app_version_code": 9850}}

    report = build_report(metadata, baseline)

    assert report["changed"] is True
    assert report["direction"] == "newer"
    assert report["current_version_code"] == 9851


def test_apk_extractor_finds_protocol_markers(tmp_path: Path) -> None:
    source = tmp_path / "Api.java"
    source.write_text(
        """
        public static final int VERSION_CODE = 9851;
        public static final String VERSION_NAME = "9851";
        String host = "https://api.domonap.ru";
        String a = "dom-app";
        String b = "dom-platform";
        String c = "instanceId";
        String d = "device-info";
        @POST("client-api/Key/GetPagedKeysByKeysType")
        Object getKeys();
        String hub = "/notificationHub";
        String target = "ReceivePush";
        String event = "DomofonCalling";
        """,
        encoding="utf-8",
    )

    observed = extract_contract(tmp_path)

    assert observed["app"]["version_codes"] == [9851]
    assert "api.domonap.ru" in observed["hosts"]
    assert observed["api_hosts"] == ["api.domonap.ru"]
    assert "device-info" in observed["headers"]
    assert "POST /client-api/Key/GetPagedKeysByKeysType" in observed["endpoints"]
    assert observed["signalr"]["hubs"] == ["/notificationHub"]
    assert observed["signalr"]["targets"] == ["ReceivePush"]
    assert observed["signalr"]["events"] == ["DomofonCalling"]
    assert "endpoint:/client-api/Key/GetPagedKeysByKeysType" in observed["evidence"]


def test_contract_diff_flags_security_and_breaking_changes() -> None:
    baseline = {
        "trusted_hosts": ["api.domonap.ru"],
        "observed_hosts": ["api.domonap.ru", "www.domonap.ru"],
        "observed_headers": ["dom-app", "dom-platform", "instanceId"],
        "observed_endpoints": ["POST /client-api/Key/GetPagedKeysByKeysType"],
        "signalr": {
            "hub": "/notificationHub",
            "target": "ReceivePush",
            "events": ["DomofonCalling"],
        },
    }
    observed = {
        "hosts": ["api2.domonap.ru", "www.domonap.ru"],
        "api_hosts": ["api2.domonap.ru"],
        "headers": ["dom-app", "dom-platform", "device-info"],
        "endpoints": ["POST /client-api/Key/GetKeysV2"],
        "signalr": {
            "hubs": ["/notificationHubV2"],
            "targets": ["ReceivePushV2"],
            "events": ["DomofonCallingV2"],
        },
    }

    findings = compare_contracts(baseline, observed)
    severities = {item.severity for item in findings}
    messages = {item.message for item in findings}

    assert "SECURITY" in severities
    assert "HIGH" in severities
    assert "MEDIUM" in severities
    assert "New API-like Domonap host detected: api2.domonap.ru" in messages
    assert "New non-API Domonap host marker: www.domonap.ru" not in messages
    assert (
        "Expected endpoint disappeared: /client-api/Key/GetPagedKeysByKeysType" in messages
    )
