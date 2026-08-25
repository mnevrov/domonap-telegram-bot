from unittest.mock import AsyncMock, MagicMock

from aiohttp.test_utils import TestClient, TestServer

from domonap_bot.domonap.client import WhepSession
from domonap_bot.domonap.models import DoorKey
from domonap_bot.web.camera_proxy import CameraProxy


def _door() -> DoorKey:
    return DoorKey(
        id="key-1",
        doorId="door-1",
        name="Door",
        webrtcVideoUrl="https://webrtc.example/camera-1/",
    )


async def test_camera_link_is_opaque_and_expires() -> None:
    proxy = CameraProxy(
        MagicMock(),
        public_base_url="https://bot.example",
        secret="a" * 32,
        link_ttl_seconds=300,
    )

    url = proxy.url_for(_door())

    assert url is not None
    assert "webrtc.example" not in url
    assert "/camera/" in url


async def test_whep_routes_forward_offer_and_map_location() -> None:
    client = MagicMock()
    client.create_whep_session = AsyncMock(
        return_value=WhepSession("https://webrtc.example/session/1", "answer-sdp")
    )
    client.patch_whep_session = AsyncMock()
    client.delete_whep_session = AsyncMock()
    proxy = CameraProxy(
        client,
        public_base_url="http://localhost:8080",
        secret="b" * 32,
    )
    link = proxy.url_for(_door())
    assert link is not None
    token = link.rsplit("/", 1)[1]

    async with TestClient(TestServer(proxy.app())) as http:
        page = await http.get(f"/camera/{token}")
        assert page.status == 200
        assert "RTCPeerConnection" in await page.text()
        page_html = await page.text()
        assert '<video id="video" autoplay muted playsinline controls>' in page_html
        assert "pendingCandidates" in page_html
        assert "pc.onicecandidate" in page_html
        assert "a=ice-ufrag:" in page_html
        assert "application/trickle-ice-sdpfrag" in page_html

        created = await http.post(f"/camera/{token}/whep", data="offer-sdp")
        assert created.status == 201
        assert await created.text() == "answer-sdp"
        local_location = created.headers["Location"]
        assert local_location.startswith("/camera/session/")
        client.create_whep_session.assert_awaited_once_with(
            "https://webrtc.example/camera-1/whep",
            "offer-sdp",
        )

        patched = await http.patch(local_location, data="candidate")
        assert patched.status == 204
        client.patch_whep_session.assert_awaited_once_with(
            "https://webrtc.example/session/1", "candidate"
        )

        deleted = await http.delete(local_location)
        assert deleted.status == 204
        client.delete_whep_session.assert_awaited_once_with("https://webrtc.example/session/1")


async def test_invalid_camera_token_is_not_accepted() -> None:
    proxy = CameraProxy(
        MagicMock(),
        public_base_url="https://bot.example",
        secret="c" * 32,
    )

    async with TestClient(TestServer(proxy.app())) as http:
        response = await http.get("/camera/not-a-token")

    assert response.status == 404
