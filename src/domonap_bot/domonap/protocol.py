from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EndpointContract:
    method: str
    path: str
    mutating: bool = False
    response_kind: str = "json"
    required_response_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomonapProtocolProfile:
    name: str
    source_app_version_code: int
    source_app_release_date: str
    verification: str
    base_url: str
    trusted_host: str
    user_agent: str
    dom_app: str
    dom_platform: str
    endpoints: tuple[EndpointContract, ...]
    signalr_hub: str
    signalr_target: str
    signalr_events: tuple[str, ...]
    expected_header_markers: tuple[str, ...]

    def endpoint(self, method: str, path: str) -> EndpointContract | None:
        normalized_method = method.upper()
        return next(
            (
                item
                for item in self.endpoints
                if item.method == normalized_method and item.path == path
            ),
            None,
        )

    @property
    def readonly_endpoints(self) -> tuple[EndpointContract, ...]:
        return tuple(item for item in self.endpoints if not item.mutating)


CURRENT_PROFILE: Final = DomonapProtocolProfile(
    name="domonap-android-9850-baseline",
    source_app_version_code=9850,
    source_app_release_date="2026-07-30",
    # 9850 is the current public app release. The protocol baseline below is the
    # implementation currently known to work; APK extraction is responsible for
    # independently verifying and reporting drift from it.
    verification="runtime-baseline-awaiting-apk-verification",
    base_url="https://api.domonap.ru",
    trusted_host="api.domonap.ru",
    user_agent="okhttp/5.3.2",
    dom_app="mobile;",
    dom_platform="Android;",
    endpoints=(
        EndpointContract("POST", "/sso-api/Authorization/Authorize", response_kind="text"),
        EndpointContract(
            "POST", "/sso-api/Authorization/ConfirmAuthorization", required_response_fields=()
        ),
        EndpointContract(
            "POST",
            "/sso-api/Authorization/RefreshToken",
            required_response_fields=("accessToken", "refreshToken", "refreshExpirationDate"),
        ),
        EndpointContract(
            "POST", "/sso-api/Authorization/UpdateDeviceToken", mutating=True, response_kind="text"
        ),
        EndpointContract("POST", "/sso-api/User/GetUser"),
        EndpointContract(
            "POST",
            "/client-api/Key/GetPagedKeysByKeysType",
            required_response_fields=("results",),
        ),
        EndpointContract("POST", "/client-api/Key/GetUserKey"),
        EndpointContract(
            "POST", "/client-api/Device/OpenRelayByDoorId", mutating=True, response_kind="text"
        ),
        EndpointContract(
            "POST", "/client-api/Device/OpenRelayByKeyId", mutating=True, response_kind="text"
        ),
        EndpointContract(
            "POST", "/client-api/CallLog/GetCallLogs", required_response_fields=("results",)
        ),
        EndpointContract(
            "POST",
            "/communication-api/Call/NotifyCallAnswered",
            mutating=True,
            response_kind="text",
        ),
        EndpointContract(
            "POST",
            "/communication-api/Call/NotifyCallEnded",
            mutating=True,
            response_kind="text",
        ),
    ),
    signalr_hub="/notificationHub",
    signalr_target="ReceivePush",
    signalr_events=("DomofonCalling", "DomofonCallEnded"),
    expected_header_markers=("dom-app", "dom-platform", "instanceId"),
)
