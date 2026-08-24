# Operations runbook

This runbook covers persisted state, automatic backup/restore, health recovery, dependency maintenance, API compatibility monitoring, releases and incident handling.

## Storage and secrets

The default SQLite database is `data/storage.db`. It contains runtime allow/admin ACL and Domonap session metadata. Access/refresh tokens and related session fields are encrypted with `STORAGE_ENCRYPTION_KEY`.

The session is stored as one authenticated encrypted record. Refresh-token rotation therefore cannot leave a mixture of independently committed old/new token fields. Legacy per-field storage is migrated automatically on first successful read.

The SQLite file is private (`0600` on POSIX when possible) and its parent is created private (`0700`). Treat backups as sensitive even though Domonap session values are encrypted.

`STORAGE_ENCRYPTION_KEY` is not stored in SQLite and is not passed to the backup sidecar. Keep it separately from database backups and the Git repository.

## Automatic backups

Docker Compose runs a dedicated `backup` service using the same application image but without `.env` secrets. Defaults: every 6 hours (`BACKUP_INTERVAL_SECONDS=21600`), keep 28 copies (`BACKUP_RETENTION_COUNT=28`) in `/app/backups` on a separate Docker volume.

The service uses SQLite online backup, validates the copy with `PRAGMA integrity_check`, writes through a temporary file and atomically replaces the destination.

```bash
docker compose ps backup
docker compose logs --tail=100 backup
docker compose exec backup sh -c 'ls -lh /app/backups'
```

Automatic local backup is not off-site disaster recovery. Periodically copy the backup volume to a different host/storage and keep the matching `STORAGE_ENCRYPTION_KEY` in another protected location.

## Restore drill

The repository test suite performs a backup/restore round-trip in CI. On a deployed host also run a non-destructive drill periodically:

```bash
latest="$(docker compose exec -T backup sh -c 'ls -1t /app/backups/storage-*.db | head -n1')"

docker compose run --rm --no-deps bot \
  python -m domonap_bot.storage_tools restore \
  "$latest" /tmp/restore-drill.db
```

The command verifies both source backup and restored DB with SQLite integrity checks.

## Production restore

Stop both services:

```bash
docker compose stop bot backup
```

Inspect backups:

```bash
docker compose run --rm --no-deps bot sh -c 'ls -1t /app/backups/storage-*.db | head'
```

Restore:

```bash
docker compose run --rm --no-deps bot \
  python -m domonap_bot.storage_tools restore \
  /app/backups/storage-YYYYMMDD-HHMMSS.db \
  /app/data/storage.db
```

Restore the matching `STORAGE_ENCRYPTION_KEY`, then `docker compose up -d` and verify `/status`, doors and effective ACL/admin roles.

For a host deployed with `docker-compose.prod.yml`, use the same commands with `-f docker-compose.prod.yml`.

## Storage encryption key rotation

Execute `/logout`, stop bot + backup, generate and configure a new Fernet key, restart, authenticate through `/auth`, verify `/status`, then create a fresh backup. Preserve the previous key only while old backups must remain recoverable.

## Session invalidation reliability

When Domonap definitively rejects a refresh token, the client emits an empty session transition. The runtime binds that transition to persistent storage cleanup. Pending cleanup tasks are drained during graceful shutdown.

The authoritative session record is deleted last after legacy keys, so interrupted cleanup cannot resurrect an older token set after the atomic record is gone.

## Health and automatic recovery

The container healthcheck is based on application heartbeat rather than PID existence. Heartbeat is emitted only while the asyncio loop progresses and the call watcher task remains alive when enabled.

A daemon watchdog thread monitors heartbeat. Because Docker Compose does not restart a running process merely for `unhealthy`, the watchdog converts stale heartbeat into process exit and `restart: unless-stopped` starts a clean process.

```bash
docker compose ps
docker inspect --format '{{json .State.Health}}' "$(docker compose ps -q bot)"
```

Repeated watchdog restarts are an incident and should be investigated.

## Logging

Compose uses bounded Docker JSON logs: bot 5 × 10 MiB, backup 3 × 10 MiB. Third-party HTTP/Telegram/SQLite loggers stay at INFO or higher even when application `LOG_LEVEL=DEBUG`.

## Domonap API compatibility

The integration is not a documented public API. Production maintenance combines passive runtime monitoring, RuStore release watch + signer-verified APK analysis, optional read-only live canary and community integration watch. See `docs/API_COMPATIBILITY.md`.

Community sources run in partial-observation mode: new markers can raise findings, but missing markers do not imply removal. This prevents false HIGH removal storms from incomplete source snapshots.

The live canary uses `DOMONAP_CANARY_ACCESS_TOKEN` from a dedicated low-privilege account when such a credential is available. If the secret is absent, the workflow reports `skipped` and remains non-blocking; static APK analysis, runtime monitoring and community watch continue to provide compatibility evidence. If credentials are later configured, actual canary degradation remains a blocking failure and opens a dedicated issue. Live verification is currently intentionally deferred because no suitable token is available; enabling it later requires only adding the repository secret.

## Dependency maintenance

Runtime/development versions are resolved through `constraints.txt`; the Docker base is digest-pinned. Dependabot checks Python, GitHub Actions and Docker weekly. Changes must pass Ruff, strict mypy, pytest, `pip-audit`, Docker build/runtime smoke, Compose config and full-history secret scan.

## Release lifecycle

`pyproject.toml` is the source of application version. Production releases use `.github/workflows/release.yml` from `master`.

The workflow validates the requested version, reruns quality/security gates, builds the production image, publishes immutable GHCR tags `vX.Y.Z` and `sha-<commit>`, and creates a GitHub Release.

`docker-compose.prod.yml` is a standalone production manifest and intentionally contains no `build:` directives. CI checks this invariant so a production deployment cannot silently build an unversioned local checkout.

Production deployment:

```bash
export DOMONAP_BOT_IMAGE=ghcr.io/mnevrov/domonap-telegram-bot:v1.0.0

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Rollback by selecting the previous immutable tag and repeating the commands. Do not use `latest` as the rollback contract.

## Repository governance

`master` must be protected by a GitHub branch rule/ruleset requiring PRs, CI, Secret Scan, resolved review conversations and blocked force-push/delete with narrow bypass.

Until that repository setting is enabled, `.github/workflows/master-policy.yml` is a detective fallback: each push to `master` checks association with a PR and opens a policy incident for direct push. It cannot prevent the push; issue #49 remains the authoritative settings task.

## Post-deploy smoke / soak

For each production release verify health, `/status`, doors, one real door-open action, one incoming SignalR call, restart/session+ACL recovery, a generated backup and a restore drill. For a major integration change observe the release for 24–72 hours before treating rollout as fully soaked.

## Incident notes

Never publish Telegram bot token, Domonap tokens, SMS codes or `STORAGE_ENCRYPTION_KEY`. Rotate exposed credentials instead of relying on log deletion. Repeated SignalR fallback, watchdog restarts, API contract mismatch or configured-canary failure should be treated as operational signals.
