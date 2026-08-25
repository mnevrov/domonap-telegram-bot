# WebRTC camera proxy

## Problem

`webrtcVideoUrl` points to a MediaMTX reader endpoint. Opening that endpoint
directly in a mobile browser produces a MediaMTX Basic Auth prompt, while the
bot already has the required Domonap Bearer session.

## Design

The bot exposes a small same-origin HTTP application. A Telegram button points
to a short-lived opaque URL issued by the proxy. The browser loads a minimal
WebRTC page and sends its WHEP offer to the proxy. The proxy forwards SDP and
ICE requests to Domonap with the current Bearer token, and maps the upstream
session location to an opaque local session identifier.

No Domonap access or refresh token is included in a Telegram URL or in browser
HTML. Proxy links expire and are stored only in memory; restarting the bot
invalidates old links.

## Configuration

`PUBLIC_BASE_URL` enables camera links. `CAMERA_PROXY_SECRET` is used for
application-level link signing/validation, `CAMERA_PROXY_PORT` selects the
listen port, and `CAMERA_LINK_TTL_SECONDS` controls link lifetime.

The application remains compatible with installations without
`PUBLIC_BASE_URL`: WebRTC buttons are omitted, while safe HTTP/HLS links retain
their existing behavior.

## Verification

Tests cover WHEP request headers and refresh retry, link expiry, local-to-upstream
session mapping, and Telegram keyboard selection. Static checks are followed by
a Docker restart and manual Android browser validation.
