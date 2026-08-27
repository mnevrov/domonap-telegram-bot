# Yandex Alice integration plan

## Goal

Add two independent, opt-in Yandex Alice flows without using the existing Domonap skill:

1. **Domonap -> Alice**: on a live intercom call, run a Yandex Smart Home user scenario so selected Yandex Stations announce a preconfigured phrase such as "К вам пришли. Домофон Подъезд".
2. **Alice -> Domonap**: expose one virtual `devices.types.openable` device named `Домофон`; the command "Алиса, открой домофон" opens only the door associated with a currently active live Domonap call.

The two flows must not depend on Telegram delivery success and must remain disabled by default.

## Non-goals

- Do not use or depend on the existing Domonap Yandex skill.
- Do not use Home Assistant.
- Do not use undocumented Yandex Station / Quasar / Glagol APIs.
- Do not add paid TTS or cloud compute requirements.
- Do not infer an active call from call-log polling.
- Do not allow Alice to choose an arbitrary Domonap door.

## Architecture

```text
Domonap SignalR
      |
      v
ObservedCallEventSource
      |
      +--------------------------+
      |                          |
      v                          v
CallWatcher                YandexCallObserver
(Telegram)                       |
                                 +--> ActiveCallRegistry
                                 |
                                 +--> YandexScenarioAnnouncer
                                         |
                                         v
                               api.iot.yandex.net
                                         |
                                         v
                               Yandex user scenario
                                         |
                                         v
                                  Yandex Stations

Yandex Station
      |
      | "Алиса, открой домофон"
      v
Yandex Smart Home
      |
      v
Provider Adapter API
      |
      +--> YandexIdTokenVerifier
      |
      +--> ActiveCallRegistry.claim_openable()
      |
      v
DomonapClient.open_door(active_call.door_id)
```

## Scenario 1: live call announcement

### Yandex side

Create one Yandex Smart Home scenario per physical Domonap door that should be announced. The scenario itself contains the fixed phrase and target Stations. Example:

- `door_id=entrance-1` -> scenario `Domonap — Подъезд` -> "К вам пришли. Домофон Подъезд".
- `door_id=gate-1` -> scenario `Domonap — Калитка` -> "К вам пришли. Звонят у калитки".

The bot stores only the mapping `door_id -> scenario_id` and invokes:

`POST https://api.iot.yandex.net/v1.0/scenarios/{scenario_id}/actions`

using a Yandex OAuth token with `iot:control`.

### Delivery semantics

Voice notifications are **at-most-once per call_id**:

- mark a call as attempted before the HTTP request;
- do not automatically retry an ambiguous timeout/network failure;
- keep a bounded LRU of attempted call IDs;
- only live SignalR events trigger voice announcements;
- call-log polling remains Telegram-only.

This deliberately prefers a missed announcement over multiple speakers repeating the same message.

## Scenario 2: voice opening of the active call

### Yandex Smart Home device

Expose exactly one virtual device:

- id: `domonap-active-intercom`
- name: `Домофон`
- type: `devices.types.openable`
- capability: `devices.capabilities.on_off`
- `retrievable=false`

The only accepted state change is `on=true`, interpreted as "open". `off=false` is rejected as an invalid action.

### Account linking

For the private, unofficial skill use **Yandex ID / Yandex OAuth as the authorization server** instead of implementing a password database in the bot.

The Provider Adapter receives the Yandex OAuth token in the Smart Home `Authorization` header and validates it server-side with `https://login.yandex.ru/info`.

Authorization is fail-closed and requires both:

- returned Yandex `id` is present in configured `YANDEX_ALLOWED_USER_IDS`;
- returned `client_id` equals configured `YANDEX_ID_OAUTH_CLIENT_ID`.

Only token hashes may be cached; raw bearer tokens must never be logged.

### Active call registry

An active call is created **only by a live SignalR incoming-call event** containing both `call_id` and `door_id`.

It becomes non-openable when any of the following happens:

- matching `DomofonCallEnded` event arrives;
- SignalR session terminates or fails;
- configured TTL expires;
- the door has already been opened successfully for that call.

Polling call-log entries must never create an active call.

If more than one unconsumed active call exists, voice opening is rejected as ambiguous.

### Atomic open flow

`ActiveCallRegistry` uses an asyncio lock and a claim/release/complete lifecycle:

1. `claim_openable()` prunes expired calls and atomically claims the only eligible call.
2. Provider calls `DomonapClient.open_door(door_id)`.
3. On success, `complete(call_id)` permanently consumes the call.
4. On failure, `release(call_id)` allows another attempt while the live call and TTL are still valid.

This prevents two concurrent Yandex requests from opening the relay twice.

### Request idempotency

Cache a bounded set of Yandex `X-Request-Id` values and their completed responses. A repeated request returns the previous result without invoking Domonap again.

### Dry-run gate

`YANDEX_SMART_HOME_DRY_RUN=true` is the default. In dry-run mode the provider validates authorization, request shape, active-call state, deduplication and one-shot semantics but does not call `DomonapClient.open_door`.

Real relay control must require an explicit configuration change after end-to-end testing.

## Configuration

Planned settings:

```env
# Domonap -> Alice
YANDEX_ANNOUNCEMENTS_ENABLED=false
YANDEX_IOT_OAUTH_TOKEN=
YANDEX_SCENARIO_MAP={}

# Alice -> Domonap
YANDEX_SMART_HOME_ENABLED=false
YANDEX_SMART_HOME_DRY_RUN=true
YANDEX_SMART_HOME_PORT=8081
YANDEX_ACTIVE_CALL_TTL_SECONDS=60
YANDEX_ID_OAUTH_CLIENT_ID=
YANDEX_ALLOWED_USER_IDS=[]
```

`YANDEX_SCENARIO_MAP` is a JSON object mapping Domonap `door_id` values to Yandex `scenario_id` values.

## Security invariants

Voice open MUST return an error and MUST NOT call Domonap when any invariant fails:

- no live SignalR call;
- SignalR is disconnected;
- call TTL expired;
- `door_id` is missing;
- more than one live call is openable;
- call was already consumed;
- request is for an unknown virtual device;
- capability is not `devices.capabilities.on_off`;
- state is not `instance=on, value=true`;
- bearer token is invalid;
- Yandex user ID is not allowed;
- token belongs to another OAuth client application.

Secrets, OAuth tokens, Domonap tokens, media URLs, request bodies and voice phrases must not be written to INFO/WARNING logs.

## Implementation phases

### Phase 1 — safe core

- `ActiveCallRegistry` with TTL and atomic claim semantics.
- `YandexScenarioClient` and at-most-once announcer.
- `ObservedCallEventSource` / `YandexCallObserver` so only live SignalR events affect Alice state.
- Unit tests for expiry, ambiguity, disconnect clearing, one-shot open and announcement deduplication.

### Phase 2 — Provider Adapter in dry-run

- Yandex ID token verifier with user/client allow-list.
- REST endpoints: `HEAD /v1.0/`, `POST /v1.0/user/unlink`, `GET /v1.0/user/devices`, `POST /v1.0/user/devices/query`, `POST /v1.0/user/devices/action`.
- `X-Request-Id` logging and response deduplication.
- Dry-run action execution.
- Unit tests for authorization and fail-closed action handling.

### Phase 3 — runtime wiring

- Add settings and `.env.example` documentation.
- Wire the observed SignalR source into `CallWatcher` without changing polling semantics.
- Start the Smart Home provider as a separate aiohttp listener.
- Keep all Yandex functionality off by default.

### Phase 4 — end-to-end setup

- Register a Yandex OAuth app for scenario control (`iot:control`) and obtain a token.
- Create per-door Yandex scenarios and populate the map.
- Register a separate Yandex ID OAuth application for private Smart Home account linking.
- Create a private Smart Home skill and point its Endpoint URL at the provider adapter.
- Verify discovery and the exact phrase "Алиса, открой домофон" while dry-run is enabled.

### Phase 5 — controlled enablement

- Perform a real intercom test call.
- Confirm SignalR start/end events and TTL behavior.
- Confirm repeated `X-Request-Id` does not repeat an action.
- Confirm no-call, ended-call, disconnected-SignalR and ambiguous-call cases fail closed.
- Set `YANDEX_SMART_HOME_DRY_RUN=false` only after those checks pass.

## Acceptance criteria

1. A mapped live SignalR call invokes its Yandex scenario at most once.
2. Polling-only discovery never makes speakers announce a call and never creates an openable call.
3. "Алиса, открой домофон" can affect only the one currently active live door.
4. A second voice request for the same call cannot operate the relay again.
5. Disconnect, end event and TTL all revoke voice-open permission.
6. Unauthorized Yandex accounts and tokens for a different OAuth app are rejected.
7. Yandex features are disabled by default and existing Telegram behavior remains unchanged.
8. CI passes Ruff, strict mypy and pytest before merge.
