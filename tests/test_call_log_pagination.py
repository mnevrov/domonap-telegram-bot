from unittest.mock import AsyncMock, MagicMock

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.models import CallLogEntry, CallLogPage


def _client() -> DomonapClient:
    client = DomonapClient(token_storage=MagicMock())
    client.set_tokens("access", "refresh", "2027-01-01T00:00:00+03:00")
    return client


async def test_get_call_logs_page_preserves_server_metadata() -> None:
    client = _client()
    client._request = AsyncMock(
        return_value={
            "results": [
                {
                    "callId": "call-2",
                    "doorId": "door-1",
                    "caller": "Door",
                    "answered": False,
                }
            ],
            "currentPage": 2,
            "perPage": 10,
            "total": 23,
        }
    )

    try:
        page = await client.get_call_logs_page(
            per_page=10,
            current_page=2,
            missed_calls=True,
        )
    finally:
        await client.close()

    assert page.current_page == 2
    assert page.per_page == 10
    assert page.total == 23
    assert page.total_pages == 3
    assert [entry.call_id for entry in page.entries] == ["call-2"]
    client._request.assert_awaited_once_with(
        "POST",
        "/client-api/CallLog/GetCallLogs",
        payload={"currentPage": 2, "perPage": 10, "missedCalls": True},
        need_auth=True,
    )


async def test_find_call_log_walks_server_pages_until_match() -> None:
    client = _client()
    client.get_call_logs_page = AsyncMock(
        side_effect=[
            CallLogPage(
                entries=[CallLogEntry(callId="call-1")],
                current_page=1,
                per_page=1,
                total=3,
            ),
            CallLogPage(
                entries=[CallLogEntry(callId="call-2")],
                current_page=2,
                per_page=1,
                total=3,
            ),
        ]
    )

    try:
        entry = await client.find_call_log("call-2", per_page=1, max_pages=3)
    finally:
        await client.close()

    assert entry is not None
    assert entry.call_id == "call-2"
    assert [call.kwargs["current_page"] for call in client.get_call_logs_page.await_args_list] == [
        1,
        2,
    ]


async def test_find_call_log_stops_at_safety_limit() -> None:
    client = _client()
    client.get_call_logs_page = AsyncMock(
        side_effect=[
            CallLogPage(entries=[], current_page=1, per_page=1, total=1000),
            CallLogPage(entries=[], current_page=2, per_page=1, total=1000),
        ]
    )

    try:
        entry = await client.find_call_log("missing", per_page=1, max_pages=2)
    finally:
        await client.close()

    assert entry is None
    assert client.get_call_logs_page.await_count == 2
