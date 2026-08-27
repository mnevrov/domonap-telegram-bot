from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_YANDEX_IOT_BASE_URL = "https://api.iot.yandex.net"
_MAX_ATTEMPTED_CALLS = 1000


class YandexScenarioError(RuntimeError):
    """Yandex Smart Home scenario invocation failed."""


class YandexScenarioClient:
    def __init__(
        self,
        oauth_token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        token = oauth_token.strip()
        if not token:
            raise ValueError("Yandex OAuth token must not be empty")
        self._token = token
        self._http = http_client or httpx.AsyncClient(
            base_url=_YANDEX_IOT_BASE_URL,
            timeout=httpx.Timeout(5.0, connect=3.0),
        )
        self._owns_http = http_client is None

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def run_scenario(self, scenario_id: str) -> str:
        scenario = scenario_id.strip()
        if not scenario:
            raise ValueError("scenario_id must not be empty")

        # Intentionally no automatic retry: if the POST reached Yandex but the response
        # was lost, retrying could make every Station repeat the announcement.
        try:
            response = await self._http.post(
                f"/v1.0/scenarios/{scenario}/actions",
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise YandexScenarioError("Yandex scenario request failed") from exc

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise YandexScenarioError(
                f"Yandex scenario returned invalid JSON (HTTP {response.status_code})"
            ) from exc

        if (
            not response.is_success
            or not isinstance(payload, dict)
            or payload.get("status") != "ok"
        ):
            raise YandexScenarioError(f"Yandex scenario failed with HTTP {response.status_code}")

        request_id = payload.get("request_id")
        return str(request_id) if request_id is not None else ""


class YandexScenarioAnnouncer:
    """Map live Domonap doors to Yandex scenarios with at-most-once delivery."""

    def __init__(
        self,
        client: YandexScenarioClient,
        scenario_by_door_id: dict[str, str],
        *,
        max_attempted_calls: int = _MAX_ATTEMPTED_CALLS,
    ) -> None:
        if max_attempted_calls <= 0:
            raise ValueError("max_attempted_calls must be positive")
        self._client = client
        self._scenario_by_door_id = {
            str(door_id): str(scenario_id)
            for door_id, scenario_id in scenario_by_door_id.items()
            if str(door_id).strip() and str(scenario_id).strip()
        }
        self._max_attempted_calls = max_attempted_calls
        self._attempted: OrderedDict[str, None] = OrderedDict()

    def _mark_attempted(self, call_id: str) -> bool:
        if call_id in self._attempted:
            return False
        self._attempted[call_id] = None
        self._attempted.move_to_end(call_id)
        while len(self._attempted) > self._max_attempted_calls:
            self._attempted.popitem(last=False)
        return True

    async def announce(self, *, call_id: str, door_id: str) -> bool:
        scenario_id = self._scenario_by_door_id.get(door_id)
        if scenario_id is None:
            logger.debug("No Yandex announcement scenario mapped for door_id=%s", door_id)
            return False
        if not self._mark_attempted(call_id):
            return False

        try:
            request_id = await self._client.run_scenario(scenario_id)
        except Exception as exc:
            # Do not retry this call automatically. At-most-once semantics are more
            # important than recovering an ambiguous delivery failure.
            logger.warning(
                "Yandex call announcement failed: call_id=%s door_id=%s error=%s",
                call_id,
                door_id,
                type(exc).__name__,
            )
            return False

        logger.info(
            "Yandex call announcement accepted: call_id=%s door_id=%s request_id=%s",
            call_id,
            door_id,
            request_id or "<missing>",
        )
        return True
