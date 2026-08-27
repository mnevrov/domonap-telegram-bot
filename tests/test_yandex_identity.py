import httpx
import pytest

from domonap_bot.yandex.smart_home import YandexIdTokenVerifier


@pytest.mark.asyncio
async def test_yandex_id_token_requires_allowed_user_and_expected_client() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "OAuth secret-token"
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={"id": "123", "client_id": "client-1", "login": "owner"},
        )

    http = httpx.AsyncClient(
        base_url="https://login.yandex.ru",
        transport=httpx.MockTransport(handler),
    )
    verifier = YandexIdTokenVerifier(
        expected_client_id="client-1",
        allowed_user_ids={"123"},
        http_client=http,
    )

    first = await verifier.verify("secret-token")
    second = await verifier.verify("secret-token")

    assert first is not None
    assert first.user_id == "123"
    assert second == first
    assert len(requests) == 1
    await http.aclose()


@pytest.mark.asyncio
async def test_yandex_id_token_rejects_wrong_oauth_application() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"id": "123", "client_id": "other-client", "login": "owner"},
        )

    http = httpx.AsyncClient(
        base_url="https://login.yandex.ru",
        transport=httpx.MockTransport(handler),
    )
    verifier = YandexIdTokenVerifier(
        expected_client_id="client-1",
        allowed_user_ids={"123"},
        http_client=http,
    )

    assert await verifier.verify("secret-token") is None
    await http.aclose()


@pytest.mark.asyncio
async def test_yandex_id_token_rejects_unapproved_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"id": "999", "client_id": "client-1", "login": "stranger"},
        )

    http = httpx.AsyncClient(
        base_url="https://login.yandex.ru",
        transport=httpx.MockTransport(handler),
    )
    verifier = YandexIdTokenVerifier(
        expected_client_id="client-1",
        allowed_user_ids={"123"},
        http_client=http,
    )

    assert await verifier.verify("secret-token") is None
    await http.aclose()


@pytest.mark.asyncio
async def test_yandex_id_transport_failure_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    http = httpx.AsyncClient(
        base_url="https://login.yandex.ru",
        transport=httpx.MockTransport(handler),
    )
    verifier = YandexIdTokenVerifier(
        expected_client_id="client-1",
        allowed_user_ids={"123"},
        http_client=http,
    )

    assert await verifier.verify("secret-token") is None
    await http.aclose()
