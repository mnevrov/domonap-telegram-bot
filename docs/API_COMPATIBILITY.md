# Domonap API compatibility automation

Domonap does not expose a stable public API contract for this bot. The integration must be treated as a compatibility layer for the official Android application, not as a versioned public REST API.

The maintenance loop uses independent evidence with different trust levels:

1. **Runtime monitor** — passively observes structural response compatibility for endpoints actually used by the bot.
2. **RuStore release watch** — detects a new `com.domonap.app` Android release.
3. **Official APK analysis** — downloads the APK, verifies provenance/signature and extracts protocol markers after JADX decompilation.
4. **Live canary** — optionally performs a very small set of non-mutating requests against the real service when a canary credential is configured.
5. **Community watch** — uses selected sources from `svmironov/domonap_intercom` only as an early-warning sensor.

No source is allowed to change trusted hosts, authorization routing or mutating production endpoints automatically.

## Contract baseline

The checked-in baseline is:

```text
contracts/domonap/current.json
```

`source.app_version_code` identifies the public Android release used as provenance. It is not an API version published by Domonap.

Practical verification states:

- `runtime-baseline-awaiting-apk-verification`;
- `apk-verified-partial-static`;
- `apk-verified`;
- `apk-and-live-verified`.

The baseline separates:

- `trusted_hosts` — origins allowed to receive authenticated requests;
- `observed_hosts` — host strings seen in official APK evidence;
- `endpoints` — runtime operations required by this bot;
- `observed_endpoints` — endpoints independently visible in static APK evidence;
- `required_headers` — metadata currently required by runtime;
- `observed_headers` — markers found in the official APK.

An `observed_*` marker is evidence, not permission.

## Runtime monitor

`RuntimeCompatibilityMonitor` is attached to the existing `httpx.AsyncClient`.

It writes a value-free structural report to:

```text
/tmp/domonap-api-compatibility.json
```

Persisted data is limited to:

- method/path;
- HTTP status;
- JSON key/type shape;
- missing required fields;
- observation time.

Request bodies, response values, bearer tokens and authorization headers are not persisted.

States: `compatible`, `warning`, `degraded`, `unknown`.

A contract mismatch is also logged as an application error. The monitor is passive and never rewrites requests.

## Official APK watch

Workflow: `.github/workflows/domonap-api-watch.yml`.

It runs daily and on compatibility-related pull requests. It queries RuStore metadata, verifies APK provenance/signer, decompiles with JADX, extracts hosts/headers/endpoints/SignalR markers, compares the result with the baseline, uploads evidence and opens an issue for a new Android release.

A source/download failure is a monitoring failure, not proof that Domonap changed.

## Diff severity

| Severity | Meaning | Automatic action |
|---|---|---|
| `SECURITY` | new API-like origin or trust-sensitive change | report only |
| `HIGH` | removal/change with strong complete-source evidence | report only |
| `MEDIUM` | potentially required metadata change | report only |
| `LOW` | new capability/non-API marker | report only |
| `INFO` | no meaningful drift | none |

No finding automatically alters production trust.

### Complete vs partial observations

`contract_diff.py` has two modes.

Normal APK analysis is treated as sufficiently broad evidence to report missing previously observed markers.

`--partial-observation` is used when the source is intentionally incomplete. In that mode:

- new hosts/headers/endpoints/events are still reported;
- absent hosts/headers/endpoints/events are **not** interpreted as removals.

This distinction is essential for community integrations, where scanning a few source files cannot prove that an official APK capability disappeared.

## Live canary

Workflow: `.github/workflows/domonap-live-canary.yml`.

Optional repository secret: `DOMONAP_CANARY_ACCESS_TOKEN`.

Use a dedicated low-privilege Domonap account when possible.

Allowed probes:

- `POST /sso-api/User/GetUser`;
- `POST /client-api/Key/GetPagedKeysByKeysType` with one result;
- `POST /client-api/CallLog/GetCallLogs` with one result;
- SignalR `/notificationHub/negotiate`.

Explicitly prohibited: SMS authorization, refresh-token rotation, `UpdateDeviceToken`, door opening and call answer/end.

Only response shapes are stored.

### Missing canary credentials

A missing canary secret is explicit but non-blocking. If `DOMONAP_CANARY_ACCESS_TOKEN` is absent, the report contains `overall: skipped`, the workflow succeeds, and no configuration issue is opened. This allows production hardening and releases to proceed when a suitable canary credential is temporarily unavailable.

Once a credential is configured, actual live incompatibility remains blocking: `degraded` or probe execution failure opens/updates `[api-canary] Domonap live compatibility degraded` and fails the workflow. A later compatible run closes that issue automatically.

A skipped canary must not be described as live-verified evidence. In this state the project relies on the official APK analysis, passive runtime monitor and community sensor until a credential becomes available.

## Community watch

Workflow: `.github/workflows/domonap-community-watch.yml`.

It fetches selected source files from `svmironov/domonap_intercom`, extracts protocol markers and runs `contract_diff --partial-observation`.

Community evidence is intentionally partial. Therefore it may report new API-like hosts, headers, endpoints or SignalR events, but it does **not** claim an official capability disappeared merely because that marker is absent from selected community files.

When no actionable `MEDIUM/HIGH/SECURITY` additions remain, a stale community-drift issue is closed automatically.

Community output is advisory. Confirm changes with the official APK, runtime evidence or live canary before modifying production behavior.

## Promoting a new official baseline

When Android version `N` is detected:

1. inspect the `domonap-api-watch-N` artifact;
2. verify APK acquisition provenance and signer;
3. review JADX quality/coverage;
4. review every SECURITY/HIGH/MEDIUM finding;
5. distinguish runtime contract from statically observed markers;
6. compare passive runtime compatibility;
7. require a compatible live canary only when credentials are configured;
8. update implementation/tests only for confirmed changes;
9. update `contracts/domonap/current.json`;
10. choose only the strongest verification state justified by evidence;
11. run ordinary CI and forced APK analysis;
12. merge through the normal protected-branch process.

For a new host/origin, never add it to the authorization allow-list until ownership and TLS identity are independently verified.

## Current Android 9850 evidence

The current baseline is Android `versionCode=9850`, promoted on 2026-08-23.

Evidence:

- RuStore APK signer SHA-256 matched the fingerprint obtained independently from the TLS-verified RuStore backend;
- JADX returned partial-decompilation exit code `3`;
- 23,405 source files were produced;
- 25,700 text files were scanned.

Confirmed markers include trusted production API host `api.domonap.ru`, observed but untrusted `dev-api.domonap.ru` / `www.domonap.*`, `dom-app`, `dom-platform`, `instanceId`, official-client `device-info`, SignalR `/notificationHub`, target `ReceivePush`, and call events `DomofonCalling`, `DomofonCallAnswered`, `DomofonCallEnded`.

`device-info` is not automatically added to bot requests. It should become a runtime requirement only if passive/live evidence demonstrates that the service requires it.

## Local commands

Static extraction:

```bash
PYTHONPATH=src python -m domonap_bot.tools.apk_extract \
  --jadx-dir /tmp/jadx-out \
  --output /tmp/observed.json
```

Complete-source diff:

```bash
PYTHONPATH=src python -m domonap_bot.tools.contract_diff \
  --baseline contracts/domonap/current.json \
  --observed /tmp/observed.json \
  --json-output /tmp/diff.json \
  --markdown-output /tmp/diff.md
```

Partial-source diff:

```bash
PYTHONPATH=src python -m domonap_bot.tools.contract_diff \
  --baseline contracts/domonap/current.json \
  --observed /tmp/community-observed.json \
  --json-output /tmp/community-diff.json \
  --markdown-output /tmp/community-diff.md \
  --partial-observation
```

Read-only live probe when a credential is available:

```bash
DOMONAP_CANARY_ACCESS_TOKEN='...' \
PYTHONPATH=src python -m domonap_bot.tools.api_probe \
  --output /tmp/canary.json
```
