"""Short-lived same-origin WHEP proxy for Domonap camera readers."""

# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.url_policy import safe_http_url

logger = logging.getLogger(__name__)


@dataclass
class _Link:
    upstream_url: str
    expires_at: float


@dataclass
class _Session:
    upstream_url: str
    expires_at: float


_PLAYER_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Камера</title><style>body{margin:0;background:#111;color:#eee;font:16px sans-serif;text-align:center}video{width:100vw;height:100vh;object-fit:contain;background:#000}p{padding:2rem}</style></head>
<body><video id="video" autoplay muted playsinline controls></video><p id="status">Подключение…</p>
<script>
const video=document.getElementById('video'), status=document.getElementById('status');
const base=location.pathname.replace(/\\/$/,''); let sessionUrl=null, pc=null, pendingCandidates=[];
function setStatus(s){status.textContent=s}
function sendCandidate(candidate){
  if(!sessionUrl || !pc.localDescription)return;
  const lines=pc.localDescription.sdp.split('\\r\\n');
  const ufrag=(lines.find(line=>line.startsWith('a=ice-ufrag:'))||'').trim();
  const pwd=(lines.find(line=>line.startsWith('a=ice-pwd:'))||'').trim();
  const mediaLines=lines.filter(line=>line.startsWith('m='));
  const midLines=lines.filter(line=>line.startsWith('a=mid:'));
  const index=candidate.sdpMLineIndex||0;
  const mid=(candidate.sdpMid||midLines[index]?.slice(6)||String(index));
  const media=mediaLines[index]||mediaLines[0]||'m=video';
  const fragment=[ufrag,pwd,media,'a=mid:'+mid,'a='+candidate.candidate,''].join('\\r\\n');
  fetch(sessionUrl,{method:'PATCH',headers:{'Content-Type':'application/trickle-ice-sdpfrag'},body:fragment}).catch(()=>{});
}
async function start(){
  pc=new RTCPeerConnection(); pc.addTransceiver('video',{direction:'recvonly'});
  pc.ontrack=e=>{video.srcObject=e.streams[0];setStatus('')};
  pc.onicecandidate=e=>{if(e.candidate){if(sessionUrl)sendCandidate(e.candidate);else pendingCandidates.push(e.candidate)}};
  const offer=await pc.createOffer(); await pc.setLocalDescription(offer);
  const response=await fetch(base+'/whep',{method:'POST',headers:{'Content-Type':'application/sdp','Accept':'application/sdp'},body:offer.sdp});
  if(!response.ok) throw new Error('WHEP '+response.status);
  sessionUrl=response.headers.get('Location');
  await pc.setRemoteDescription({type:'answer',sdp:await response.text()});
  pendingCandidates.splice(0).forEach(sendCandidate);
}
window.addEventListener('pagehide',()=>{if(sessionUrl) fetch(sessionUrl,{method:'DELETE',keepalive:true}).catch(()=>{});if(pc)pc.close()});
start().catch(e=>setStatus('Не удалось подключить камеру: '+e.message));
</script></body></html>"""


def _whep_url(url: str) -> str | None:
    safe = safe_http_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    path = parts.path.rstrip("/") + "/whep"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


class CameraProxy:
    def __init__(
        self,
        client: DomonapClient,
        *,
        public_base_url: str,
        secret: str,
        link_ttl_seconds: int = 300,
        max_entries: int = 1000,
    ) -> None:
        if len(secret) < 16:
            raise ValueError("Camera proxy secret must be at least 16 characters")
        self._client = client
        self._base_url = public_base_url.rstrip("/")
        self._secret = secret.encode()
        self._ttl = link_ttl_seconds
        self._max_entries = max_entries
        self._links: dict[str, _Link] = {}
        self._sessions: dict[str, _Session] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def url_for(self, door: DoorKey) -> str | None:
        upstream_url = safe_http_url(door.webrtc_video_url)
        if not self.enabled:
            return safe_http_url(door.http_video_url)
        if upstream_url is None:
            return safe_http_url(door.http_video_url)
        self._prune()
        nonce = secrets.token_urlsafe(18)
        expires_at = time.time() + self._ttl
        payload = f"{nonce}.{int(expires_at)}".encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()[:18]
        token = f"{base64.urlsafe_b64encode(payload).decode().rstrip('=')}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
        self._links[token] = _Link(upstream_url, expires_at)
        return f"{self._base_url}/camera/{token}"

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/camera/{token}", self._page)
        app.router.add_post("/camera/{token}/whep", self._create_session)
        app.router.add_patch("/camera/session/{session_id}", self._patch_session)
        app.router.add_delete("/camera/session/{session_id}", self._delete_session)
        return app

    def _prune(self) -> None:
        now = time.time()
        self._links = {key: value for key, value in self._links.items() if value.expires_at > now}
        self._sessions = {
            key: value for key, value in self._sessions.items() if value.expires_at > now
        }
        while len(self._links) > self._max_entries:
            self._links.pop(next(iter(self._links)))

    def _link(self, token: str) -> _Link | None:
        self._prune()
        link = self._links.get(token)
        if link is None or link.expires_at <= time.time():
            return None
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = base64.urlsafe_b64decode(encoded_payload + "===")
            signature = base64.urlsafe_b64decode(encoded_signature + "===")
        except (ValueError, UnicodeDecodeError):
            return None
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()[:18]
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            _, expires_text = payload.decode().rsplit(".", 1)
            if int(expires_text) <= int(time.time()):
                return None
        except (ValueError, UnicodeDecodeError):
            return None
        return link

    async def _page(self, request: web.Request) -> web.Response:
        if self._link(request.match_info["token"]) is None:
            raise web.HTTPNotFound()
        return web.Response(text=_PLAYER_HTML, content_type="text/html")

    async def _create_session(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        link = self._link(token)
        if link is None:
            raise web.HTTPNotFound()
        offer = await request.text()
        if not offer or len(offer) > 100_000:
            raise web.HTTPBadRequest(text="Invalid SDP offer")
        upstream_whep = _whep_url(link.upstream_url)
        if upstream_whep is None:
            raise web.HTTPBadGateway(text="Invalid camera URL")
        try:
            session = await self._client.create_whep_session(upstream_whep, offer)
        except Exception as exc:
            logger.warning("Failed to create WHEP session: %s", exc)
            raise web.HTTPBadGateway(text="Camera connection failed") from exc
        local_id = secrets.token_urlsafe(24)
        self._sessions[local_id] = _Session(session.location, link.expires_at)
        response = web.Response(text=session.answer_sdp, content_type="application/sdp", status=201)
        response.headers["Location"] = f"/camera/session/{local_id}"
        return response

    def _session(self, request: web.Request) -> _Session:
        self._prune()
        session = self._sessions.get(request.match_info["session_id"])
        if session is None:
            raise web.HTTPNotFound()
        return session

    async def _patch_session(self, request: web.Request) -> web.Response:
        session = self._session(request)
        fragment = await request.text()
        if not fragment or len(fragment) > 100_000:
            raise web.HTTPBadRequest(text="Invalid ICE fragment")
        try:
            await self._client.patch_whep_session(session.upstream_url, fragment)
        except Exception as exc:
            logger.warning("Failed to patch WHEP session: %s", exc)
            raise web.HTTPBadGateway(text="Camera connection failed") from exc
        return web.Response(status=204)

    async def _delete_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        session = self._session(request)
        self._sessions.pop(session_id, None)
        try:
            await self._client.delete_whep_session(session.upstream_url)
        except Exception as exc:
            logger.debug("Failed to close WHEP session: %s", exc)
        return web.Response(status=204)


async def start_camera_proxy(proxy: CameraProxy, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(proxy.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


async def stop_camera_proxy(runner: web.AppRunner) -> None:
    await runner.cleanup()
