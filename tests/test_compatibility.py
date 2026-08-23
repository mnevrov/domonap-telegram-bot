import json
from pathlib import Path

import httpx

from domonap_bot.domonap.compatibility import RuntimeCompatibilityMonitor, json_shape


def test_json_shape_contains_no_values() -> None:
    shaped = json_shape(
        {
            "accessToken": "super-secret-token",
            "count": 42,
            "enabled": True,
            "items": [{"doorId": "private-door-id"}],
        }
    )

    rendered = json.dumps(shaped)
    assert "super-secret-token" not in rendered
    assert "private-door-id" not in rendered
    assert '"accessToken": "string"' in rendered
    assert '"count": "integer"' in rendered


async def test_monitor_records_compatible_shape_without_values(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/client-api/CallLog/GetCallLogs"
        return httpx.Response(
            200,
            json={
                "results": [{"callId": "secret-call-id", "answered": False}],
                "total": 1,
            },
        )

    report_path = tmp_path / "compatibility.json"
    monitor = RuntimeCompatibilityMonitor(report_path=report_path)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.domonap.ru",
        transport=transport,
    ) as client:
        monitor.attach(client)
        response = await client.post("/client-api/CallLog/GetCallLogs", json={})
        assert response.status_code == 200

    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["overall"] == "compatible"
    assert "secret-call-id" not in report_text
    endpoint = report["endpoints"]["POST /client-api/CallLog/GetCallLogs"]
    assert endpoint["status"] == "ok"


async def test_monitor_marks_missing_required_field_as_mismatch(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 0})

    report_path = tmp_path / "compatibility.json"
    monitor = RuntimeCompatibilityMonitor(report_path=report_path)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.domonap.ru",
        transport=transport,
    ) as client:
        monitor.attach(client)
        await client.post("/client-api/CallLog/GetCallLogs", json={})

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["overall"] == "degraded"
    endpoint = report["endpoints"]["POST /client-api/CallLog/GetCallLogs"]
    assert endpoint["status"] == "contract-mismatch"
    assert endpoint["missing_fields"] == ["results"]


async def test_monitor_ignores_untrusted_origin(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accessToken": "must-not-be-observed"})

    report_path = tmp_path / "compatibility.json"
    monitor = RuntimeCompatibilityMonitor(report_path=report_path)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        monitor.attach(client)
        await client.post("https://example.com/sso-api/Authorization/RefreshToken", json={})

    assert not report_path.exists()
