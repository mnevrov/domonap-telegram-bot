from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

_TEXT_SUFFIXES = {
    ".java",
    ".kt",
    ".kts",
    ".xml",
    ".json",
    ".properties",
    ".txt",
    ".smali",
}
_MAX_FILE_BYTES = 2 * 1024 * 1024
_ENDPOINT_RE = re.compile(
    r"[\"'](/(?:sso-api|client-api|communication-api)/[^\"'\\s?#]+)[\"']"
)
_DOMONAP_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]*domonap\.[A-Za-z.]+)")
_DOMOFON_EVENT_RE = re.compile(r"[\"'](Domofon[A-Za-z0-9_]+)[\"']")
_VERSION_CODE_RE = re.compile(r"\bVERSION_CODE\s*=\s*(\d+)\b")
_VERSION_NAME_RE = re.compile(r"\bVERSION_NAME\s*=\s*[\"']([^\"']+)[\"']")
_METHOD_ANNOTATION_RE = re.compile(
    r"@(GET|POST|PUT|PATCH|DELETE)\s*\(\s*[\"']([^\"']+)[\"']\s*\)"
)
_HEADER_MARKERS = (
    "Authorization",
    "User-Agent",
    "dom-app",
    "dom-platform",
    "instanceId",
    "device-info",
)
_SIGNALR_TARGETS = ("ReceivePush",)
_SIGNALR_HUBS = ("/notificationHub",)


def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def extract_contract(root: Path) -> dict[str, Any]:
    hosts: set[str] = set()
    headers: set[str] = set()
    endpoints: set[str] = set()
    signalr_events: set[str] = set()
    signalr_targets: set[str] = set()
    signalr_hubs: set[str] = set()
    version_codes: set[int] = set()
    version_names: set[str] = set()
    files_scanned = 0

    for path in _iter_text_files(root):
        text = _read_text(path)
        if not text:
            continue
        files_scanned += 1

        hosts.update(match.group(1).lower() for match in _DOMONAP_HOST_RE.finditer(text))
        signalr_events.update(match.group(1) for match in _DOMOFON_EVENT_RE.finditer(text))

        for marker in _HEADER_MARKERS:
            if marker in text:
                headers.add(marker)
        for target in _SIGNALR_TARGETS:
            if target in text:
                signalr_targets.add(target)
        for hub in _SIGNALR_HUBS:
            if hub in text:
                signalr_hubs.add(hub)

        for match in _METHOD_ANNOTATION_RE.finditer(text):
            method, endpoint = match.groups()
            if endpoint.startswith(("/sso-api/", "/client-api/", "/communication-api/")):
                endpoints.add(f"{method} {endpoint}")

        # Some decompilers lose Retrofit annotations while preserving literal paths.
        for match in _ENDPOINT_RE.finditer(text):
            endpoint = match.group(1)
            if not any(item.endswith(f" {endpoint}") for item in endpoints):
                endpoints.add(f"UNKNOWN {endpoint}")

        version_codes.update(int(match.group(1)) for match in _VERSION_CODE_RE.finditer(text))
        version_names.update(match.group(1) for match in _VERSION_NAME_RE.finditer(text))

    return {
        "schema_version": 1,
        "extraction": {
            "files_scanned": files_scanned,
            "source": "jadx-output",
        },
        "app": {
            "version_codes": sorted(version_codes),
            "version_names": sorted(version_names),
        },
        "hosts": sorted(hosts),
        "headers": sorted(headers),
        "endpoints": sorted(endpoints),
        "signalr": {
            "hubs": sorted(signalr_hubs),
            "targets": sorted(signalr_targets),
            "events": sorted(signalr_events),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Domonap protocol markers from JADX output")
    parser.add_argument("--jadx-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.jadx_dir.is_dir():
        raise SystemExit(f"JADX directory does not exist: {args.jadx_dir}")
    contract = extract_contract(args.jadx_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(contract, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
