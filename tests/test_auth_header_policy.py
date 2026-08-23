import httpx
import pytest

from domonap_bot.domonap.auth import DomonapAuth


@pytest.mark.asyncio
async def test_authorization_preserved_for_exact_domonap_origin() -> None:
    seen_authorization: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("Authorization"))
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(
        base_url="https://api.domonap.ru",
        transport=httpx.MockTransport(handler),
    ) as client:
        DomonapAuth(client)
        await client.get(
            "/client-api/test",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert seen_authorization == ["Bearer secret-token"]


@pytest.mark.asyncio
async def test_authorization_removed_for_external_host() -> None:
    seen_authorization: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("Authorization"))
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(
        base_url="https://api.domonap.ru",
        transport=httpx.MockTransport(handler),
    ) as client:
        DomonapAuth(client)
        await client.get(
            "https://cdn.example.test/media.jpg",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert seen_authorization == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://api.domonap.ru/client-api/test",
        "https://api.domonap.ru:444/client-api/test",
    ],
)
async def test_authorization_removed_for_non_trusted_scheme_or_port(url: str) -> None:
    seen_authorization: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("Authorization"))
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(
        base_url="https://api.domonap.ru",
        transport=httpx.MockTransport(handler),
    ) as client:
        DomonapAuth(client)
        await client.get(url, headers={"Authorization": "Bearer secret-token"})

    assert seen_authorization == [None]


def test_auth_hook_is_not_registered_twice() -> None:
    client = httpx.AsyncClient(base_url="https://api.domonap.ru")
    try:
        DomonapAuth(client)
        DomonapAuth(client)
        assert len(client.event_hooks["request"]) == 1
    finally:
        import asyncio

        asyncio.run(client.aclose())
