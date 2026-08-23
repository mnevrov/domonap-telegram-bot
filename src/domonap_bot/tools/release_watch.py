from __future__ import annotations

import argparse
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PACKAGE_NAME = "com.domonap.app"
RUSTORE_INFO_URL = (
    "https://backapi.rustore.ru/applicationData/overallInfo/" + PACKAGE_NAME
)
RUSTORE_DOWNLOAD_URL = "https://backapi.rustore.ru/applicationData/download-link"
_RUSTORE_CLIENT_VERSION_CODES = (12000, 20000, 99999, 247)
_MAX_APK_BYTES = 512 * 1024 * 1024


class ReleaseWatchError(RuntimeError):
    pass


def _json_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    rustore_version_code: int,
) -> dict[str, Any]:
    encoded: bytes | None = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "domonap-telegram-bot-api-watch/1.0",
        "ruStoreVerCode": str(rustore_version_code),
    }
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=encoded, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(2 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReleaseWatchError(f"RuStore request failed: {exc}") from exc
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ReleaseWatchError("RuStore returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ReleaseWatchError("RuStore returned unexpected JSON type")
    return parsed


def _request_with_version_fallback(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    for version_code in _RUSTORE_CLIENT_VERSION_CODES:
        try:
            payload = _json_request(
                url,
                method=method,
                body=body,
                rustore_version_code=version_code,
            )
        except ReleaseWatchError as exc:
            errors.append(str(exc))
            continue
        if str(payload.get("code", "")).upper() == "OK" and payload.get("body") is not None:
            return payload, version_code
        errors.append(f"ruStoreVerCode={version_code}: code={payload.get('code')!r}")
    raise ReleaseWatchError("RuStore API rejected all client versions: " + "; ".join(errors))


def fetch_release_metadata() -> dict[str, Any]:
    payload, client_version = _request_with_version_fallback(RUSTORE_INFO_URL)
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ReleaseWatchError("RuStore application metadata has no object body")
    try:
        version_code = int(body["versionCode"])
        app_id = int(body["appId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseWatchError("RuStore metadata misses appId/versionCode") from exc
    return {
        "package_name": str(body.get("packageName") or PACKAGE_NAME),
        "app_id": app_id,
        "version_code": version_code,
        "version_name": str(body.get("versionName") or version_code),
        "updated_at": str(body.get("appVerUpdatedAt") or ""),
        "file_size": body.get("fileSize"),
        "rustore_client_version_code": client_version,
    }


def fetch_apk_url(app_id: int) -> str:
    payload, _ = _request_with_version_fallback(
        RUSTORE_DOWNLOAD_URL,
        method="POST",
        body={"appId": app_id, "firstInstall": True},
    )
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ReleaseWatchError("RuStore download response has no object body")
    apk_url = body.get("apkUrl")
    if not isinstance(apk_url, str) or not apk_url:
        raise ReleaseWatchError("RuStore download response has no apkUrl")
    parsed = urllib.parse.urlparse(apk_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ReleaseWatchError("RuStore returned a non-HTTPS APK URL")
    return apk_url


def download_apk(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "domonap-telegram-bot-api-watch/1.0"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_APK_BYTES:
                    raise ReleaseWatchError("APK exceeds the configured size limit")
                output.write(chunk)
        if total == 0:
            raise ReleaseWatchError("Downloaded APK is empty")
        shutil.move(str(temporary), str(destination))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_baseline(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReleaseWatchError("Contract baseline must be a JSON object")
    return payload


def build_report(metadata: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    source = baseline.get("source")
    if not isinstance(source, dict):
        raise ReleaseWatchError("Contract baseline has no source object")
    try:
        baseline_version = int(source["app_version_code"])
        current_version = int(metadata["version_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseWatchError("Cannot compare app version codes") from exc
    return {
        "package_name": metadata["package_name"],
        "baseline_version_code": baseline_version,
        "current_version_code": current_version,
        "current_version_name": metadata["version_name"],
        "updated_at": metadata["updated_at"],
        "changed": current_version != baseline_version,
        "direction": (
            "newer"
            if current_version > baseline_version
            else "older"
            if current_version < baseline_version
            else "same"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the current Domonap Android release")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--download-apk", type=Path)
    parser.add_argument("--force-download", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = fetch_release_metadata()
    baseline = load_baseline(args.contract)
    report = build_report(metadata, baseline)

    if args.download_apk is not None and (report["changed"] or args.force_download):
        apk_url = fetch_apk_url(int(metadata["app_id"]))
        download_apk(apk_url, args.download_apk)
        report["apk_downloaded"] = True
    else:
        report["apk_downloaded"] = False

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
