# Operations runbook

This document covers the operational procedures that protect the bot's persisted state and keep its pinned dependencies maintainable.

## Storage layout and secrets

The default SQLite database is `data/storage.db`. It contains:

- the runtime allow/admin ACL;
- Domonap session metadata;
- Domonap access/refresh tokens encrypted with `STORAGE_ENCRYPTION_KEY`.

The database file is private (`0600` on POSIX) and its parent directory is created private (`0700`) when the application creates it. Treat database backups as sensitive even though session values are encrypted.

`STORAGE_ENCRYPTION_KEY` is **not** stored in the database. Keep it in a secret manager or another backup location that is separate from SQLite backups and from the Git repository. A database backup without the matching key cannot restore an encrypted Domonap session.

Do not use a copy of the complete `.env` file as the normal database-key backup: it also contains the Telegram bot token and may contain other deployment-specific secrets.

## Consistent SQLite backup

The built-in backup command uses SQLite's online backup API, validates the resulting database with `PRAGMA integrity_check`, writes through a temporary file and atomically replaces the requested destination.

From a configured virtual environment:

```bash
mkdir -p backups
python -m domonap_bot.storage_tools backup \
  data/storage.db \
  backups/storage-$(date +%Y%m%d-%H%M%S).db
```

The bot may remain running during a backup. Copy the resulting backup to the actual backup destination after the command succeeds.

For every backup set, verify that you also have access to the corresponding `STORAGE_ENCRYPTION_KEY`. Store the key separately from the database archive.

## Restore

A restore replaces the destination database atomically after verifying the backup. **Stop the bot before restoring.**

```bash
docker compose down

# Optional but strongly recommended: preserve the current database first.
python -m domonap_bot.storage_tools backup \
  data/storage.db \
  backups/pre-restore-$(date +%Y%m%d-%H%M%S).db

python -m domonap_bot.storage_tools restore \
  backups/storage-YYYYMMDD-HHMMSS.db \
  data/storage.db
```

Restore the matching `STORAGE_ENCRYPTION_KEY` in the deployment environment before starting the bot again, then:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
```

After startup, verify `/status`, the visible door list and the effective admin/user ACL. A wrong encryption key causes startup to fail closed instead of silently discarding the saved session.

## Storage encryption key rotation

The current storage format intentionally does not guess or silently re-encrypt data with an unknown key. To rotate the key without retaining ciphertext under the old key:

1. while the old key is still configured and the bot is running, execute `/logout` to clear the persisted Domonap session;
2. stop the bot;
3. generate a new Fernet key;
4. replace `STORAGE_ENCRYPTION_KEY` in the deployment secret store;
5. start the bot and authenticate to Domonap again with `/auth` and `/code`;
6. create a fresh database backup and separately back up the new encryption key.

Generate a key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If the old key is lost before the session is cleared, do not overwrite the only database backup. Preserve the database and key material you still have before attempting recovery.

## Deployment checks

The container runs as an unprivileged user with a read-only root filesystem, dropped Linux capabilities and `no-new-privileges`. The writable locations are the persistent `/app/data` bind mount and the bounded `/tmp` tmpfs.

Useful checks after a deployment:

```bash
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
```

The Docker health check is based on the application's asyncio heartbeat rather than process existence alone. An unhealthy container therefore indicates that the event loop has stopped advancing or the heartbeat is missing/stale.

## Dependency maintenance

Runtime and development dependencies are resolved through `constraints.txt`; the Docker base image is pinned by digest. Dependabot checks Python, GitHub Actions and Docker weekly and opens normal pull requests. It does **not** auto-merge updates.

Accept dependency/update PRs only after the same gates used for normal code changes are green:

- Ruff;
- strict mypy;
- pytest;
- `pip-audit` for runtime dependencies;
- Docker image build;
- Docker Compose validation;
- full-history secret scan;
- automated/reviewer feedback resolved.

For a manual dependency update, change the direct dependency requirement only when needed, deliberately update the exact resolved versions in `constraints.txt`, and require a complete CI run plus Docker build before merging. Do not remove exact constraints merely to make a dependency resolver succeed.

For a Docker base-image update, retain digest pinning. Review the new digest/base tag combination through a PR and require the full Docker/Compose validation before merge.

## Incident notes

Never paste Telegram tokens, Domonap access/refresh tokens, SMS confirmation codes or `STORAGE_ENCRYPTION_KEY` into issues, CI logs or troubleshooting screenshots. If a credential is exposed, rotate/revoke it rather than relying on log deletion alone.

When investigating notification failures, remember that SignalR is primary and call-log polling is the fallback. A transient SignalR failure is expected to switch to bounded polling before reconnecting; repeated failures should be investigated from sanitized application logs without enabling dependency-level DEBUG logging.
