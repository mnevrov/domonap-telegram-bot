# Call Diagnostics Design

## Goal

Capture enough safe runtime evidence to locate a missed Domonap call at one of
four boundaries: SignalR delivery, payload parsing, call-log polling, or
Telegram delivery.

## Scope

The bot runs in a test mode, so diagnostics use INFO and WARNING logs. They
must never include access or refresh tokens, phone numbers, media URLs, or
message bodies.

## SignalR Evidence

Log successful negotiation and WebSocket connection. For each `ReceivePush`
record, log only its event type and the presence of call and door identifiers.
Log warnings for a malformed `ReceivePush` record or an incoming-call payload
that fails validation. This distinguishes an absent event from an unsupported
event shape.

## Watcher Evidence

Log receipt of each incoming call with its call and door identifiers. During
fallback polling, log the first observed and each changed newest call-log ID,
with the returned count. This avoids one log entry per five-second poll while
showing whether the API advances.

## Telegram Evidence

Log notification delivery success or failure by recipient count. Existing
per-recipient error logs remain in place.

## Validation

Unit tests cover the added diagnostics without exposing sensitive data. After
deployment, a fresh test call must produce an evidence chain that identifies
the first missing boundary.
