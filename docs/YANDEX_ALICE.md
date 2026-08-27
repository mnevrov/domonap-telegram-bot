# Yandex Alice integration

This integration intentionally does **not** use the existing Domonap skill. It provides two independent opt-in flows:

1. a live Domonap call launches a pre-created Yandex Smart Home scenario so selected Stations announce where the visitor arrived;
2. a private Yandex Smart Home device named `Домофон` accepts an Alice open command and operates only the single currently active live Domonap call.

Both features are disabled by default. Voice opening is dry-run by default.

## Safety model

The voice-open path is deliberately narrower than Telegram `/open`:

- only a live SignalR event can create an openable call;
- call-log polling never creates an openable call and never triggers a Station announcement;
- `DomofonCallEnded`, SignalR disconnect, or the active-call TTL revoke permission;
- a missing `door_id` fails closed;
- more than one simultaneous openable call fails closed;
- a successfully handled call is consumed and cannot operate the relay twice;
- concurrent duplicate `X-Request-Id` deliveries are serialized and reuse the cached result;
- an ambiguous Domonap transport/API failure consumes the call because the relay command may already have reached Domonap;
- Yandex ID authorization requires both an allow-listed numeric Yandex user ID and the expected OAuth application client ID;
- raw OAuth tokens are never logged;
- the Smart Home HTTP listener is published by Docker only on host loopback. Public TLS must terminate in a reverse proxy.

## 1. Domonap -> Yandex Stations

### 1.1 Create a Yandex OAuth application for Smart Home API access

In Yandex OAuth create an application of type **For API access or debugging**. Grant:

- `iot:control` — required to run scenarios;
- `iot:view` — recommended during setup so you can list scenarios and their IDs.

For this application type Yandex uses the fixed verification-code redirect URI. Obtain a token for the Yandex account that owns the Stations and scenarios.

Store the token only in the deployment `.env`:

```env
YANDEX_ANNOUNCEMENTS_ENABLED=true
YANDEX_IOT_OAUTH_TOKEN=<secret OAuth token>
```

Do not commit the token.

### 1.2 Create one Yandex scenario per Domonap door

Create the scenarios in `Дом с Алисой`. The phrase and target Stations live in the Yandex scenario itself; the bot only starts the scenario by ID.

Examples:

- `Domonap — Подъезд` -> selected Stations say `К вам пришли. Домофон Подъезд.`
- `Domonap — Калитка` -> selected Stations say `К вам пришли. Звонят у калитки.`

The stable runtime mapping is `Domonap door_id -> Yandex scenario_id`, not a name-to-name mapping.

Yandex exposes scenario IDs through:

```http
GET https://api.iot.yandex.net/v1.0/user/info
Authorization: Bearer <token>
```

The response contains a `scenarios` array. The same token needs `iot:view` for this setup request.

Configure the map as one JSON object:

```env
YANDEX_SCENARIO_MAP={"domonap-door-id-1":"yandex-scenario-id-1","domonap-door-id-2":"yandex-scenario-id-2"}
```

A live call for an unmapped door is still delivered to Telegram but is not announced on Stations.

### 1.3 Delivery semantics

The announcement channel is at-most-once per Domonap `call_id`.

The bot marks the call as attempted before it sends:

```http
POST https://api.iot.yandex.net/v1.0/scenarios/{scenario_id}/actions
Authorization: Bearer <token>
```

There is intentionally no automatic retry after a timeout or transport error. If Yandex executed the request but its response was lost, retrying could make every selected Station repeat the phrase.

The Yandex HTTP request runs in a detached bounded task and never blocks the Telegram notification path.

## 2. Yandex Stations -> active Domonap call

### 2.1 Public HTTPS endpoint

The provider adapter listens inside the container on `YANDEX_SMART_HOME_PORT` (default `8081`). Docker publishes it on host loopback only:

```text
127.0.0.1:8081 -> container:8081
```

Yandex must reach the Provider Adapter via public HTTPS. Terminate TLS in an existing reverse proxy and proxy a dedicated hostname to the loopback listener.

For example, with Caddy:

```caddy
alice.example.com {
    reverse_proxy 127.0.0.1:8081
}
```

Do **not** publish port 8081 directly to the Internet as plain HTTP.

The adapter implements:

```text
HEAD /v1.0/
POST /v1.0/user/unlink
GET  /v1.0/user/devices
POST /v1.0/user/devices/query
POST /v1.0/user/devices/action
```

### 2.2 Create a Yandex ID OAuth application for account linking

This is a **separate OAuth application** from the API-access application used for scenario control.

Create an application for **user authorization** and grant the minimum Yandex ID permission required to identify the account (`login:info`). Configure it as a web service using the redirect URI required by the Yandex Smart Home account-linking console.

Record its client ID. The bot pins incoming tokens to this exact application:

```env
YANDEX_ID_OAUTH_CLIENT_ID=<client id>
```

The Provider Adapter validates the bearer token against `https://login.yandex.ru/info`, and accepts it only when both conditions hold:

- the returned `client_id` equals `YANDEX_ID_OAUTH_CLIENT_ID`;
- the returned numeric Yandex account `id` is in `YANDEX_ALLOWED_USER_IDS`.

Configure the allow-list:

```env
YANDEX_ALLOWED_USER_IDS=["123456789"]
```

Keep the list as small as possible. For one apartment owner, use one account ID.

### 2.3 Create the private Smart Home skill

In Yandex Dialogs create a Smart Home skill and keep it **Private**.

Set the Provider Adapter Endpoint URL to the public HTTPS hostname, for example:

```text
https://alice.example.com
```

For account linking, use the Yandex ID OAuth application from the previous step as the authorization server. Configure its application ID/secret, Yandex OAuth authorization/token endpoints, and the minimal `login:info` permission.

The provider exposes exactly one device:

```text
id:   domonap-active-intercom
name: Домофон
type: devices.types.openable
capability: devices.capabilities.on_off
retrievable: false
```

After publishing the private skill, link it in `Дом с Алисой`. The expected UX to verify is:

```text
Алиса, открой домофон
```

Do not assume the exact phrase is accepted until it has been tested on the real private skill and Stations; voice interpretation belongs to Yandex.

### 2.4 Start in dry-run

Initial configuration:

```env
CALL_WATCHER_ENABLED=true
YANDEX_SMART_HOME_ENABLED=true
YANDEX_SMART_HOME_DRY_RUN=true
YANDEX_SMART_HOME_PORT=8081
YANDEX_ACTIVE_CALL_TTL_SECONDS=60
YANDEX_ID_OAUTH_CLIENT_ID=<client id>
YANDEX_ALLOWED_USER_IDS=["123456789"]
```

When dry-run is enabled, a valid Alice action exercises authorization, request parsing, `X-Request-Id` deduplication and active-call claim/consume logic, but **does not call** `DomonapClient.open_door()`.

The log line for a successful dry-run is intentionally limited to call/door identifiers and contains no bearer token or voice text.

## 3. End-to-end test sequence

Perform the following before disabling dry-run:

1. With no incoming call, say `Алиса, открой домофон`. No Domonap relay operation must occur.
2. Start one real Domonap call. Confirm Telegram receives the live card without waiting for the Yandex announcement request.
3. Confirm the correct Station scenario is launched at most once for that `call_id`.
4. During the same live call, say `Алиса, открой домофон`. In dry-run the provider must return success without touching the relay.
5. Repeat the phrase. The same call must no longer be openable.
6. Start a new call, then end it before the voice command. Opening must fail closed.
7. Start a new call and break the SignalR session. Opening must fail closed even if polling later sees the call in history.
8. Let a call exceed `YANDEX_ACTIVE_CALL_TTL_SECONDS`. Opening must fail closed.
9. Simulate or test two simultaneous active calls. Opening must fail closed as ambiguous.
10. Verify an unauthorized Yandex account and a token from another OAuth client are rejected.

Only after all checks pass, enable the physical action explicitly:

```env
YANDEX_SMART_HOME_DRY_RUN=false
```

Then repeat the same test sequence with one controlled real call.

## 4. Full configuration reference

```env
# Existing live call source; required for both Yandex features.
CALL_WATCHER_ENABLED=true

# Domonap -> Stations
YANDEX_ANNOUNCEMENTS_ENABLED=false
YANDEX_IOT_OAUTH_TOKEN=
YANDEX_SCENARIO_MAP={}

# Stations -> Domonap
YANDEX_SMART_HOME_ENABLED=false
YANDEX_SMART_HOME_DRY_RUN=true
YANDEX_SMART_HOME_PORT=8081
YANDEX_ACTIVE_CALL_TTL_SECONDS=60
YANDEX_ID_OAUTH_CLIENT_ID=
YANDEX_ALLOWED_USER_IDS=[]
```

Application startup fails closed when a Yandex feature is enabled without the live call watcher or without its required authentication/mapping configuration.

## 5. Cost model

The runtime does not use SpeechKit, Home Assistant, Yandex Cloud Functions, or undocumented Station APIs.

The implementation uses:

- the existing Domonap bot server;
- Yandex Smart Home user API for scenario execution;
- a private Smart Home skill and Yandex ID for account linking;
- the existing HTTPS reverse-proxy infrastructure (or another free TLS termination option).

No paid TTS component is introduced by the bot.
