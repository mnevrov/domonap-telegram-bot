from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    message: str


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _endpoint_path(value: str) -> str:
    parts = value.split(" ", 1)
    return parts[1] if len(parts) == 2 else value


def compare_contracts(
    baseline: dict[str, Any],
    observed: dict[str, Any],
    *,
    report_missing: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []

    legacy_hosts = _string_set(baseline.get("hosts"))
    trusted_hosts = _string_set(baseline.get("trusted_hosts")) or legacy_hosts
    known_observed_hosts = _string_set(baseline.get("observed_hosts")) or trusted_hosts
    observed_hosts = _string_set(observed.get("hosts"))
    observed_api_hosts = _string_set(observed.get("api_hosts"))

    for host in sorted(observed_hosts - known_observed_hosts):
        severity = "SECURITY" if host in observed_api_hosts else "LOW"
        description = (
            "New API-like Domonap host detected"
            if severity == "SECURITY"
            else "New non-API Domonap host marker"
        )
        findings.append(Finding(severity, "host", f"{description}: {host}"))
    if report_missing:
        for host in sorted(trusted_hosts - observed_hosts):
            findings.append(
                Finding("HIGH", "host", f"Trusted API host not found in APK: {host}")
            )

    expected_headers = (
        _string_set(baseline.get("observed_headers"))
        or _string_set(baseline.get("headers"))
    )
    observed_headers = _string_set(observed.get("headers"))
    for header in sorted(observed_headers - expected_headers):
        severity = "MEDIUM" if header == "device-info" else "LOW"
        findings.append(Finding(severity, "header", f"New client header marker: {header}"))
    if report_missing:
        for header in sorted(expected_headers - observed_headers):
            findings.append(
                Finding("MEDIUM", "header", f"Expected client header marker not found: {header}")
            )

    expected_endpoints = (
        _string_set(baseline.get("observed_endpoints"))
        or _string_set(baseline.get("endpoints"))
    )
    observed_endpoints = _string_set(observed.get("endpoints"))
    expected_paths = {_endpoint_path(item) for item in expected_endpoints}
    observed_paths = {_endpoint_path(item) for item in observed_endpoints}

    if report_missing:
        for path in sorted(expected_paths - observed_paths):
            findings.append(Finding("HIGH", "endpoint", f"Expected endpoint disappeared: {path}"))
    for path in sorted(observed_paths - expected_paths):
        findings.append(Finding("LOW", "endpoint", f"New official-app endpoint detected: {path}"))

    baseline_signalr = baseline.get("signalr")
    observed_signalr = observed.get("signalr")
    if isinstance(baseline_signalr, dict) and isinstance(observed_signalr, dict):
        expected_hub = str(baseline_signalr.get("hub") or "")
        observed_hubs = _string_set(observed_signalr.get("hubs"))
        if report_missing and expected_hub and expected_hub not in observed_hubs:
            findings.append(Finding("HIGH", "signalr", f"SignalR hub missing: {expected_hub}"))

        expected_target = str(baseline_signalr.get("target") or "")
        observed_targets = _string_set(observed_signalr.get("targets"))
        if report_missing and expected_target and expected_target not in observed_targets:
            findings.append(
                Finding("HIGH", "signalr", f"SignalR target missing: {expected_target}")
            )

        expected_events = _string_set(baseline_signalr.get("events"))
        observed_events = _string_set(observed_signalr.get("events"))
        if report_missing:
            for event in sorted(expected_events - observed_events):
                findings.append(
                    Finding("HIGH", "signalr", f"SignalR event disappeared: {event}")
                )
        for event in sorted(observed_events - expected_events):
            findings.append(Finding("LOW", "signalr", f"New SignalR event detected: {event}"))

    if not findings:
        findings.append(Finding("INFO", "summary", "No protocol drift detected"))
    return findings


def render_markdown(findings: list[Finding], observed: dict[str, Any]) -> str:
    app = observed.get("app") if isinstance(observed.get("app"), dict) else {}
    versions = app.get("version_codes", []) if isinstance(app, dict) else []
    extraction = observed.get("extraction")
    files_scanned = (
        extraction.get("files_scanned") if isinstance(extraction, dict) else None
    )
    lines = [
        "# Domonap APK protocol diff",
        "",
        f"Observed APK version code candidates: `{versions}`",
        f"Static files scanned: `{files_scanned}`",
        "",
        "| Severity | Category | Finding |",
        "|---|---|---|",
    ]
    for finding in findings:
        message = finding.message.replace("|", "\\|")
        lines.append(f"| {finding.severity} | {finding.category} | {message} |")
    lines.append("")
    lines.append(
        "Security findings and removals are intentionally never applied automatically."
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diff a Domonap APK observation")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--partial-observation",
        action="store_true",
        help=(
            "Treat the observed source as incomplete: report newly observed markers, "
            "but do not infer removals from absent markers."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = _load_json(args.baseline)
    observed = _load_json(args.observed)
    findings = compare_contracts(
        baseline,
        observed,
        report_missing=not args.partial_observation,
    )
    report = {
        "findings": [asdict(item) for item in findings],
        "highest_severity": next(
            (
                severity
                for severity in ("SECURITY", "HIGH", "MEDIUM", "LOW", "INFO")
                if any(item.severity == severity for item in findings)
            ),
            "INFO",
        ),
        "partial_observation": bool(args.partial_observation),
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(findings, observed), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
