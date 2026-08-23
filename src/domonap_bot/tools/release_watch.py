from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_NAME = "com.domonap.app"
RUSTORE_INFO_URL = (
    "https://backapi.rustore.ru/applicationData/overallInfo/" + PACKAGE_NAME
)
RUSTORE_DOWNLOAD_URL = "https://backapi.rustore.ru/applicationData/download-link"
RUSTORE_DOWNLOAD_V2_URL = "https://backapi.rustore.ru/applicationData/v2/download-link"
_RUSTORE_CLIENT_VERSION_CODES = (12000, 20000, 99999, 247)
_MAX_APK_BYTES = 512 * 1024 * 1024
_SHA256_HEX_LEN = 64


class ReleaseWatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApkDescriptor:
    url: str
    version_code: int | None
    signer_sha256: str | None
    source: str


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
        code_ok = str(payload.get("code", "")).upper() == "OK"
        if code_ok and payload.get("body") is not None:
            return payload, version_code
        errors.append(
            f"ruStoreVerCode={version_code}: code={payload.get('code')!r}"
        )
    detail = "; ".join(errors)
    raise ReleaseWatchError(f"RuStore API rejected all client versions: {detail}")


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


def _normalize_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^0-9a-fA-F]", "", value).lower()
    return normalized if len(normalized) == _SHA256_HEX_LEN else None


def _validate_apk_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseWatchError("RuStore download response has no APK URL")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ReleaseWatchError("RuStore returned a non-HTTPS APK URL")
    return value


def _fetch_apk_descriptor_v2(app_id: int) -> ApkDescriptor:
    payload, _ = _request_with_version_fallback(
        RUSTORE_DOWNLOAD_V2_URL,
        method="POST",
        body={
            "appId": app_id,
            "firstInstall": True,
            "screenDensity": 480,
            "sdkVersion": 35,
            "withoutSplits": True,
            "supportedAbis": ["arm64-v8a", "armeabi-v7a", "x86_64", "x86"],
        },
    )
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ReleaseWatchError("RuStore v2 download response has no object body")
    raw_urls = body.get("downloadUrls")
    if not isinstance(raw_urls, list) or not raw_urls:
        raise ReleaseWatchError("RuStore v2 download response has no downloadUrls")
    first = raw_urls[0]
    if not isinstance(first, dict):
        raise ReleaseWatchError("RuStore v2 downloadUrls entry is not an object")
    url = _validate_apk_url(first.get("url"))
    try:
        version_code = int(body["versionCode"])
    except (KeyError, TypeError, ValueError):
        version_code = None
    return ApkDescriptor(
        url=url,
        version_code=version_code,
        signer_sha256=_normalize_sha256(body.get("signature")),
        source="rustore-v2",
    )


def _fetch_apk_descriptor_v1(app_id: int) -> ApkDescriptor:
    payload, _ = _request_with_version_fallback(
        RUSTORE_DOWNLOAD_URL,
        method="POST",
        body={"appId": app_id, "firstInstall": True},
    )
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ReleaseWatchError("RuStore v1 download response has no object body")
    url = _validate_apk_url(body.get("apkUrl"))
    try:
        version_code = int(body["versionCode"])
    except (KeyError, TypeError, ValueError):
        version_code = None
    return ApkDescriptor(
        url=url,
        version_code=version_code,
        signer_sha256=None,
        source="rustore-v1",
    )


def fetch_apk_descriptor(app_id: int) -> ApkDescriptor:
    try:
        return _fetch_apk_descriptor_v2(app_id)
    except ReleaseWatchError:
        return _fetch_apk_descriptor_v1(app_id)


def _curl_command(url: str, output: Path, *, insecure: bool) -> list[str]:
    command = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "3",
        "--retry-all-errors",
        "--connect-timeout",
        "20",
        "--max-time",
        "240",
        "--max-filesize",
        str(_MAX_APK_BYTES),
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--tlsv1.2",
        "--output",
        str(output),
    ]
    if insecure:
        command.append("--insecure")
    command.append(url)
    return command


def _run_curl(url: str, output: Path, *, insecure: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _curl_command(url, output, insecure=insecure),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _find_apksigner() -> str | None:
    direct = shutil.which("apksigner")
    if direct:
        return direct
    android_home = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if not android_home:
        return None
    candidates = sorted(
        Path(android_home).glob("build-tools/*/apksigner"),
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def _apk_signer_sha256(apk_path: Path) -> str:
    apksigner = _find_apksigner()
    if apksigner is None:
        raise ReleaseWatchError("apksigner is unavailable for APK identity verification")
    result = subprocess.run(
        [apksigner, "verify", "--print-certs", str(apk_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise ReleaseWatchError("Downloaded APK failed Android signature verification")
    match = re.search(
        r"Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F:]+)",
        result.stdout,
    )
    if match is None:
        raise ReleaseWatchError("Cannot read APK signer SHA-256 digest")
    digest = _normalize_sha256(match.group(1))
    if digest is None:
        raise ReleaseWatchError("APK signer digest has an unexpected format")
    return digest


def download_apk(descriptor: ApkDescriptor, destination: Path) -> dict[str, Any]:
    """Download an APK and verify identity if CDN TLS is misconfigured.

    Normal path requires valid TLS. A curl certificate-chain error may be recovered only
    when RuStore v2 supplied a SHA-256 signer fingerprint over its independently verified
    backapi connection. The insecure transport is then only a byte carrier: the APK is
    accepted if Android cryptographic signature verification succeeds and the signer digest
    exactly matches the fingerprint supplied by RuStore.
    """
    parsed = urllib.parse.urlparse(descriptor.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ReleaseWatchError("Refusing to download APK from a non-HTTPS URL")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    transport_verified = True
    signer_verified = False

    try:
        result = _run_curl(descriptor.url, temporary, insecure=False)
        if result.returncode != 0:
            tls_chain_error = result.returncode == 60
            if not tls_chain_error or descriptor.signer_sha256 is None:
                detail = result.stderr.strip()[-500:]
                raise ReleaseWatchError(
                    f"Verified APK download failed with curl {result.returncode}: {detail}"
                )
            transport_verified = False
            temporary.unlink(missing_ok=True)
            retry = _run_curl(descriptor.url, temporary, insecure=True)
            if retry.returncode != 0:
                detail = retry.stderr.strip()[-500:]
                raise ReleaseWatchError(
                    f"APK fallback transport failed with curl {retry.returncode}: {detail}"
                )

        size = temporary.stat().st_size
        if size <= 0:
            raise ReleaseWatchError("Downloaded APK is empty")
        if size > _MAX_APK_BYTES:
            raise ReleaseWatchError("APK exceeds the configured size limit")

        actual_signer = _apk_signer_sha256(temporary)
        if descriptor.signer_sha256 is not None:
            if actual_signer != descriptor.signer_sha256:
                raise ReleaseWatchError("APK signer does not match RuStore metadata")
            signer_verified = True
        elif not transport_verified:
            raise ReleaseWatchError("Refusing unverified APK without a trusted signer digest")

        temporary.replace(destination)
        return {
            "source": descriptor.source,
            "transport_tls_verified": transport_verified,
            "signer_sha256_verified": signer_verified,
            "version_code": descriptor.version_code,
            "size": size,
        }
    except (OSError, subprocess.TimeoutExpired):
        temporary.unlink(missing_ok=True)
        raise
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
    parser = argparse.ArgumentParser(
        description="Check the current Domonap Android release"
    )
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
        descriptor = fetch_apk_descriptor(int(metadata["app_id"]))
        descriptor_version_mismatch = (
            descriptor.version_code is not None
            and descriptor.version_code != metadata["version_code"]
        )
        if descriptor_version_mismatch:
            raise ReleaseWatchError(
                "APK descriptor version does not match release metadata"
            )
        report["apk_acquisition"] = download_apk(descriptor, args.download_apk)
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
