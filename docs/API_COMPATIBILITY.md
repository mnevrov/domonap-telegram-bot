# Domonap API compatibility automation

Domonap does not expose a stable public API contract for this bot. Treat the integration as a
compatibility layer for the official Android client rather than as a versioned public REST API.

The maintenance loop therefore uses several independent signals:

1. **Runtime monitor** — passively observes the shape of real API responses used by the bot.
2. **RuStore release watch** — detects a new `com.domonap.app` Android version.
3. **APK static analysis** — downloads the current APK, decompiles it with JADX and extracts
   hosts, header markers, REST paths, SignalR hub/target/events and app version markers.
4. **Live canary** — optional non-mutating requests against the real service.
5. **Community watch** — compares protocol markers from `svmironov/domonap_intercom` as an
   early-warning sensor. It is never treated as the source of truth.

## Contract baseline

The checked-in baseline is `contracts/domonap/current.json`.

The version in `source.app_version_code` is provenance: it identifies the public Android release
against which the contract is maintained. It is not an API version advertised by Domonap.

A baseline can have one of these practical states:

- `runtime-baseline-awaiting-apk-verification` — known working behavior, APK verification pending;
- `apk-verified-partial-static` — the APK origin/signature and static markers were checked, but a
  partial JADX result does not prove that every runtime endpoint must be visible as a literal;
- `apk-verified` — static extraction was complete enough to verify all claimed APK markers;
- `apk-and-live-verified` — APK markers and the safe live canary agree with the baseline.

Do not change the verification state merely because a community integration changed.

The baseline deliberately separates different trust levels:

- `trusted_hosts` — origins to which authenticated requests may be sent;
- `observed_hosts` — host strings seen in the official APK, including development/web hosts;
- `endpoints` — runtime API operations required by the bot implementation;
- `observed_endpoints` — endpoint literals independently proven by static APK extraction;
- `required_headers` — request metadata the bot currently relies on;
- `observed_headers` — header markers seen in the official APK.

An item appearing in an `observed_*` list is evidence that the official client contains the marker;
it does not automatically make that marker trusted or required by the bot.

## Runtime monitor

`RuntimeCompatibilityMonitor` is attached to the existing `httpx.AsyncClient` at startup. It
writes a value-free report to:

```text
/tmp/domonap-api-compatibility.json
```

Only the following information is persisted:

- request method and path;
- HTTP status;
- JSON key/type structure;
- missing required fields;
- observation timestamp.

Response values, request bodies, bearer tokens and authorization headers are never persisted.
The report is atomic and can be collected by external monitoring without affecting bot behavior.

Runtime states:

- `compatible` — observed known endpoints match required structural invariants;
- `warning` — upstream HTTP errors were observed;
- `degraded` — a known successful endpoint returned an incompatible structure;
- `unknown` — no known API response has been observed yet.

The monitor is passive. It does not rewrite requests, discover replacement hosts or modify
protocol settings automatically.

## Scheduled APK watch

Workflow: `.github/workflows/domonap-api-watch.yml`.

It runs daily and can also be started manually. Compatibility pull requests force analysis of the
current APK so that changes to the extraction logic are exercised before merge.

The workflow:

1. queries RuStore metadata for `com.domonap.app`;
2. compares the published `versionCode` with the checked-in baseline;
3. obtains the APK descriptor and signer fingerprint from the TLS-verified RuStore backend;
4. attempts a normal TLS-verified APK download;
5. if the RuStore CDN has an incomplete certificate chain, permits a transport fallback only when
   the downloaded APK's Android signer SHA-256 exactly matches the independently obtained RuStore
   signer fingerprint;
6. installs the latest JADX release and decompiles the APK;
7. accepts partial JADX output only when a substantial source tree was actually produced and
   records the exit code/file counts as analysis-quality metadata;
8. creates a value-free structural observation and evidence file paths;
9. compares it with `contracts/domonap/current.json`;
10. uploads the analysis as a GitHub Actions artifact;
11. opens or updates an issue when a new Android version is detected.

The RuStore installation backend used for APK retrieval is not a documented publisher API, so a
failure of that source must be treated as a monitoring failure rather than evidence that the
Domonap API itself changed.

The APK binary itself is never trusted merely because it downloaded successfully. A TLS-fallback
APK is accepted only after independent Android signer verification.

## Diff severity

`contract_diff.py` classifies findings as follows:

| Severity | Meaning | Automatic action |
|---|---|---|
| `SECURITY` | new API-like host/origin or similarly trust-sensitive change | report only |
| `HIGH` | a previously APK-observed endpoint, trusted host, SignalR hub/target/event disappeared | report only |
| `MEDIUM` | potentially required request metadata/header changed | report only |
| `LOW` | new endpoint/event/capability or non-API host marker discovered | report only |
| `INFO` | no meaningful drift | none |

A bot runtime endpoint that was never visible in the static APK output is not declared removed
merely because JADX cannot find its string. Runtime monitoring/live canary provide the stronger
signal for those operations.

No finding changes the trusted API origin, Authorization routing, door-control endpoints or
production contract automatically.

## Live canary

Workflow: `.github/workflows/domonap-live-canary.yml`.

The canary is disabled automatically when repository secret `DOMONAP_CANARY_ACCESS_TOKEN` is not
configured. When the secret exists, only these operations are performed:

- `POST /sso-api/User/GetUser`;
- `POST /client-api/Key/GetPagedKeysByKeysType` with a single-item page;
- `POST /client-api/CallLog/GetCallLogs` with a single-item page;
- SignalR `/notificationHub/negotiate`.

The probe intentionally does **not** call:

- SMS authorization;
- refresh-token rotation;
- `UpdateDeviceToken`;
- `OpenRelayByDoorId` or `OpenRelayByKeyId`;
- call answer/end methods.

Use a dedicated low-privilege test account when possible. The workflow stores only response
shapes in artifacts/issues, never response values.

An access token can expire. An expired token is reported as degradation and must not be confused
with a protocol change until authentication state is checked.

## Community watch

Workflow: `.github/workflows/domonap-community-watch.yml`.

It scans selected source files from `svmironov/domonap_intercom`, runs the same marker extractor
and opens/updates an issue for `MEDIUM`, `HIGH` or `SECURITY` drift.

Community output is advisory. Before adapting the bot, confirm the change with the official APK,
a safe live observation, or both.

## Promoting a new baseline

When Android version `N` is detected:

1. inspect the `domonap-api-watch-N` artifact;
2. verify APK acquisition provenance, signer verification, version candidates and extraction
   coverage;
3. review every `SECURITY`, `HIGH` and `MEDIUM` finding;
4. distinguish the bot runtime contract from markers actually proven by static extraction;
5. compare runtime compatibility state and, when configured, live-canary results;
6. update implementation/tests only for confirmed changes;
7. update `contracts/domonap/current.json` to version `N`;
8. set the strongest verification state justified by the evidence;
9. run ordinary CI and the forced APK analysis on the pull request;
10. merge only after both agree.

For a new host/origin, do not add it to the authorization allow-list until ownership and TLS
identity are verified. Existing cross-origin Authorization stripping remains a security invariant.

## Current 9850 evidence

The baseline for Android `versionCode=9850` was promoted on 2026-08-23 after a real RuStore APK
analysis. The APK signer matched the fingerprint returned independently by the RuStore backend.
JADX returned partial-decompilation code `3`, but produced 23,405 source files; 25,700 text files
were scanned for protocol markers.

Confirmed markers include:

- trusted production API host `api.domonap.ru`;
- observed but untrusted `dev-api.domonap.ru` and `www.domonap.*` markers;
- `dom-app`, `dom-platform`, `instanceId` and official-client `device-info` marker;
- SignalR `/notificationHub`, target `ReceivePush`, and call events
  `DomofonCalling`, `DomofonCallAnswered`, `DomofonCallEnded`;
- a static subset of the runtime endpoints plus additional official-client capabilities recorded in
  `observed_endpoints`.

`device-info` is intentionally not injected into bot requests automatically. It should become a
runtime requirement only if passive/live evidence demonstrates that the service starts requiring
it.

## Local commands

Static extraction after JADX decompilation:

```bash
PYTHONPATH=src python -m domonap_bot.tools.apk_extract \
  --jadx-dir /tmp/jadx-out \
  --output /tmp/observed.json

PYTHONPATH=src python -m domonap_bot.tools.contract_diff \
  --baseline contracts/domonap/current.json \
  --observed /tmp/observed.json \
  --json-output /tmp/diff.json \
  --markdown-output /tmp/diff.md
```

Read-only live probe:

```bash
DOMONAP_CANARY_ACCESS_TOKEN='...' \
PYTHONPATH=src python -m domonap_bot.tools.api_probe --output /tmp/canary.json
```

Release metadata check without forcing APK download:

```bash
PYTHONPATH=src python -m domonap_bot.tools.release_watch \
  --contract contracts/domonap/current.json \
  --report /tmp/release.json
```
