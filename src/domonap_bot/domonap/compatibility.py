from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from domonap_bot.domonap.protocol import CURRENT_PROFILE, DomonapProtocolProfile

logger = logging.getLogger(__name__)

DEFAULT_COMPATIBILITY_REPORT_PATH = Path("/tmp/domonap-api-compatibility.json")
_MAX_SHAPE_DEPTH = 6
_MAX_LIST_SAMPLE = 3


def json_shape(value: Any, *, _depth: int = 0) -> Any:
    """Return a value-free structural fingerprint safe for logs and reports."""
    if _depth >= _MAX_SHAPE_DEPTH:
        return "max-depth"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return {
            str(key): json_shape(item, _depth=_depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        samples = value[:_MAX_LIST_SAMPLE]
        return {
            "type": "array",
            "length_class": "empty" if not value else "non-empty",
            "items": [json_shape(item, _depth=_depth + 1) for item in samples],
        }
    return type(value).__name__


@dataclass
class EndpointCompatibility:
    method: str
    path: str
    status: str
    http_status: int | None = None
    missing_fields: list[str] = field(default_factory=list)
    response_shape: Any = None
    observed_at: str = ""


class RuntimeCompatibilityMonitor:
    """Passive httpx response observer for known Domonap endpoints.

    The monitor stores only HTTP metadata and structural JSON fingerprints. Response
    values, request bodies, Authorization headers and tokens are never persisted.
    """

    def __init__(
        self,
        *,
        profile: DomonapProtocolProfile = CURRENT_PROFILE,
        report_path: Path = DEFAULT_COMPATIBILITY_REPORT_PATH,
    ) -> None:
        self._profile = profile
        self._report_path = report_path
        self._endpoints: dict[str, EndpointCompatibility] = {}

    def attach(self, client: httpx.AsyncClient) -> None:
        hooks = client.event_hooks.setdefault("response", [])
        if self.observe_response not in hooks:
            hooks.append(self.observe_response)

    async def observe_response(self, response: httpx.Response) -> None:
        request = response.request
        if request.url.host != self._profile.trusted_host:
            return

        contract = self._profile.endpoint(request.method, request.url.path)
        if contract is None:
            return

        observed_at = datetime.now(timezone.utc).isoformat()
        item = EndpointCompatibility(
            method=request.method.upper(),
            path=request.url.path,
            status="ok" if response.is_success else "upstream-error",
            http_status=response.status_code,
            observed_at=observed_at,
        )

        if response.is_success and contract.response_kind == "json":
            try:
                await response.aread()
                payload = response.json()
            except (ValueError, httpx.HTTPError):
                item.status = "contract-mismatch"
                item.response_shape = "invalid-json"
            else:
                item.response_shape = json_shape(payload)
                if not isinstance(payload, dict):
                    item.status = "contract-mismatch"
                else:
                    missing = [
                        field_name
                        for field_name in contract.required_response_fields
                        if field_name not in payload
                    ]
                    if missing:
                        item.status = "contract-mismatch"
                        item.missing_fields = missing

        key = f"{item.method} {item.path}"
        previous = self._endpoints.get(key)
        self._endpoints[key] = item
        self._write_report()

        if item.status == "contract-mismatch" and (
            previous is None or previous.status != "contract-mismatch"
        ):
            logger.error(
                "Domonap API contract mismatch for %s %s; missing_fields=%s",
                item.method,
                item.path,
                item.missing_fields,
            )

    def report(self) -> dict[str, Any]:
        statuses = [item.status for item in self._endpoints.values()]
        if "contract-mismatch" in statuses:
            overall = "degraded"
        elif "upstream-error" in statuses:
            overall = "warning"
        elif statuses:
            overall = "compatible"
        else:
            overall = "unknown"

        return {
            "profile": {
                "name": self._profile.name,
                "source_app_version_code": self._profile.source_app_version_code,
                "verification": self._profile.verification,
            },
            "overall": overall,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "endpoints": {
                key: asdict(item) for key, item in sorted(self._endpoints.items())
            },
        }

    def _write_report(self) -> None:
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._report_path.with_name(f".{self._report_path.name}.tmp")
            temporary.write_text(
                json.dumps(self.report(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._report_path)
        except OSError:
            logger.warning("Cannot write Domonap compatibility report", exc_info=True)
