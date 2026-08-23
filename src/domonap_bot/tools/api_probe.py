from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from domonap_bot.domonap.compatibility import json_shape
from domonap_bot.domonap.protocol import CURRENT_PROFILE
from domonap_bot.domonap.signalr import SIGNALR_USER_AGENT


@dataclass(frozen=True)
class Probe:
    name: str
    path: str
    payload: dict[str, Any] | None = None


@dataclass
class ProbeResult:
    name: str
    status: str
    http_status: int | None = None
    response_shape: Any = None


# Deliberately excludes SMS authorization, token refresh and every operation that can
# open a door, answer/end a call, register a device token or otherwise mutate state.
READ_ONLY_PROBES = (
    Probe("user", "/sso-api/User/GetUser"),
    Probe(
        "keys",
        "/client-api/Key/GetPagedKeysByKeysType",
        {"currentPage": 1, "perPage": 1, "keysType": 0, "search": None},
    ),
    Probe(
        "call-log",
        "/client-api/CallLog/GetCallLogs",
        {"currentPage": 1, "perPage": 1, "missedCalls": False},
    ),
)


async def _probe_rest(client: httpx.AsyncClient, probe: Probe, token: str) -> ProbeResult:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = await client.post(probe.path, json=probe.payload, headers=headers)
    except httpx.HTTPError:
        return ProbeResult(probe.name, "network-error")
    if not response.is_success:
        return ProbeResult(probe.name, "http-error", http_status=response.status_code)
    try:
        payload = response.json()
    except ValueError:
        return ProbeResult(
            probe.name,
            "invalid-json",
            http_status=response.status_code,
            response_shape="invalid-json",
        )
    return ProbeResult(
        probe.name,
        "ok",
        http_status=response.status_code,
        response_shape=json_shape(payload),
    )


async def _probe_signalr(token: str) -> ProbeResult:
    headers = {
        "User-Agent": SIGNALR_USER_AGENT,
        "dom-app": CURRENT_PROFILE.dom_app,
        "dom-platform": CURRENT_PROFILE.dom_platform,
        "Authorization": f"Bearer {token}",
    }
    url = f"{CURRENT_PROFILE.base_url}{CURRENT_PROFILE.signalr_hub}/negotiate"
    params = {"negotiateVersion": "1"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, params=params, headers=headers)
    except httpx.HTTPError:
        return ProbeResult("signalr-negotiate", "network-error")
    if not response.is_success:
        return ProbeResult(
            "signalr-negotiate", "http-error", http_status=response.status_code
        )
    try:
        payload = response.json()
    except ValueError:
        return ProbeResult(
            "signalr-negotiate",
            "invalid-json",
            http_status=response.status_code,
            response_shape="invalid-json",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("connectionToken"), str):
        status = "contract-mismatch"
    else:
        status = "ok"
    return ProbeResult(
        "signalr-negotiate",
        status,
        http_status=response.status_code,
        response_shape=json_shape(payload),
    )


async def run_probe(token: str) -> dict[str, Any]:
    headers = {
        "User-Agent": CURRENT_PROFILE.user_agent,
        "dom-app": CURRENT_PROFILE.dom_app,
        "dom-platform": CURRENT_PROFILE.dom_platform,
        "instanceId": f"{uuid4()};",
    }
    async with httpx.AsyncClient(
        base_url=CURRENT_PROFILE.base_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers=headers,
    ) as client:
        results = [await _probe_rest(client, probe, token) for probe in READ_ONLY_PROBES]
    results.append(await _probe_signalr(token))

    statuses = {item.status for item in results}
    overall = "compatible" if statuses == {"ok"} else "degraded"
    return {
        "profile": CURRENT_PROFILE.name,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "results": [asdict(item) for item in results],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run non-mutating Domonap API canary probes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict-missing-token", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("DOMONAP_CANARY_ACCESS_TOKEN", "").strip()
    if not token:
        report = {
            "profile": CURRENT_PROFILE.name,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "overall": "skipped",
            "reason": "DOMONAP_CANARY_ACCESS_TOKEN is not configured",
            "results": [],
        }
        exit_code = 2 if args.strict_missing_token else 0
    else:
        report = asyncio.run(run_probe(token))
        exit_code = 0 if report["overall"] == "compatible" else 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
