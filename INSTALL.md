# Установка и запуск Domonap Telegram Bot

Бот управляет домофоном Domonap через Telegram: показывает двери, открывает их, ведёт журнал звонков и присылает интерактивные уведомления о входящих вызовах.

Рекомендуемый production-вариант — Docker Compose.

## 1. Требования

- Docker Engine и Docker Compose v2;
- Telegram bot token от `@BotFather`;
- номер телефона аккаунта Domonap;
- Telegram user ID хотя бы одного разрешённого пользователя;
- отдельный Fernet-ключ для шифрования сохранённой Domonap-сессии.

Для запуска без Docker нужен Python 3.12+.

## 2. Получение кода

```bash
git clone <repo-url> domonap-telegram-bot
cd domonap-telegram-bot
cp .env.example .env
```

## 3. Настройка `.env`

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | **Обязательно.** Токен Telegram-бота |
| `ALLOWED_TELEGRAM_USER_IDS` | **Обязательно.** Bootstrap allow-list через запятую |
| `ADMIN_TELEGRAM_USER_IDS` | Администраторы; каждый должен также входить в allow-list |
| `DOMONAP_PHONE` | Номер Domonap в международном формате |
| `DOMONAP_REGISTER_DEVICE_TOKEN` | `false` по умолчанию, чтобы не перехватывать push-маршрут официального приложения |
| `STORAGE_PATH` | SQLite; для Docker рекомендуется оставить `data/storage.db` |
| `STORAGE_ENCRYPTION_KEY` | **Обязательно.** Fernet-ключ для шифрования Domonap-сессии |
| `LOG_LEVEL` | `INFO` по умолчанию |
| `CALL_WATCHER_ENABLED` | `true` по умолчанию |
| `BACKUP_INTERVAL_SECONDS` | Интервал автоматических backup; по умолчанию 21600 (6 часов) |
| `BACKUP_RETENTION_COUNT` | Число сохраняемых backup; по умолчанию 28 |

Создайте encryption key один раз:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Сохраните его в `STORAGE_ENCRYPTION_KEY`, но **не** храните вместе с backup SQLite и не коммитьте `.env`.

Пример:

```env
TELEGRAM_BOT_TOKEN=123456789:AAExampleTokenFromBotFather
ALLOWED_TELEGRAM_USER_IDS=111111111
ADMIN_TELEGRAM_USER_IDS=111111111
DOMONAP_PHONE=+79991234567
DOMONAP_REGISTER_DEVICE_TOKEN=false
STORAGE_PATH=data/storage.db
STORAGE_ENCRYPTION_KEY=<FERNET_KEY>
LOG_LEVEL=INFO
CALL_WATCHER_ENABLED=true
BACKUP_INTERVAL_SECONDS=21600
BACKUP_RETENTION_COUNT=28
```

Приложение работает fail-closed: пустой `ALLOWED_TELEGRAM_USER_IDS` или отсутствующий `STORAGE_ENCRYPTION_KEY` останавливают startup.

## 4. Первый запуск

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
docker compose logs --tail=100 backup
```

Compose запускает два процесса:

- `bot` — основной Telegram/Domonap runtime;
- `backup` — отдельный непривилегированный процесс, который делает consistent SQLite backup каждые 6 часов и хранит последние 28 копий.

Backup лежат в отдельном Docker volume `backups`. Контейнер backup не получает Telegram token, Domonap credentials или `STORAGE_ENCRYPTION_KEY`.

Проверить список backup:

```bash
docker compose exec backup sh -c 'ls -lh /app/backups'
```

## 5. Авторизация Domonap

Авторизацию может запускать только администратор.

1. Отправьте `/start`.
2. Отправьте `/auth` или выберите **Управление → Подключить Domonap**.
3. Бот запросит SMS и покажет ForceReply.
4. Ответьте на это сообщение числовым SMS-кодом.
5. Сообщение с кодом будет удалено, если Telegram разрешит удаление.
6. Проверьте `/status`.

`/code <код>` сохранён только как скрытый compatibility fallback. `/cancel` отменяет незавершённый SMS-flow.

Токены автоматически сохраняются в SQLite как один зашифрованный atomic session record. При окончательном отклонении refresh-token сохранённая сессия очищается, чтобы не восстанавливаться после рестарта.

## 6. Основные команды

| Команда | Доступ | Назначение |
|---|---|---|
| `/start` | allowed | Главное меню |
| `/open` | allowed | Быстро открыть дверь |
| `/doors` | allowed | Список дверей |
| `/status` | allowed | Проверить Domonap-сессию |
| `/help` | allowed | Справка |
| `/auth` | admin | Начать SMS-авторизацию |
| `/logout` | admin | Завершить Domonap-сессию |
| `/cancel` | admin | Отменить ожидаемый SMS-код |
| `/code <code>` | admin | Скрытый fallback |

Новых пользователей рекомендуется добавлять через одноразовые invite-ссылки в разделе **Управление → Пользователи**. Последнего администратора удалить или понизить нельзя.

## 7. Входящие звонки

При `CALL_WATCHER_ENABLED=true` основной канал — Domonap SignalR. При сбое бот временно переходит на polling call log и затем повторяет SignalR connection.

Live-карточка может содержать:

- дверь/адрес и время;
- фото/preview;
- **Открыть**;
- **Ответить / Сбросить** для активного звонка;
- **Камера** для безопасного HTTP(S)-URL.

Доставка Telegram-уведомлений имеет bounded retry, а call ID дедуплицируются ограниченным кэшем.

## 8. Health и automatic recovery

Docker healthcheck проверяет heartbeat asyncio runtime. Heartbeat дополнительно зависит от фонового call watcher.

Внутри процесса работает отдельный watchdog thread. Если event loop завис или критическая watcher-задача завершилась, heartbeat пропадает, watchdog завершает process и `restart: unless-stopped` поднимает контейнер заново.

```bash
docker compose ps
docker inspect --format '{{json .State.Health}}' "$(docker compose ps -q bot)"
```

## 9. Restore drill

Периодически проверяйте, что backup реально восстанавливается:

```bash
latest="$(docker compose exec -T backup sh -c 'ls -1t /app/backups/storage-*.db | head -n1')"

docker compose run --rm --no-deps bot \
  python -m domonap_bot.storage_tools restore \
  "$latest" /tmp/restore-drill.db
```

Команда выполняет `PRAGMA integrity_check` до и после восстановления. Это проверочный restore в `/tmp`; production database не меняется.

Полная процедура восстановления описана в `OPERATIONS.md`.

## 10. Production image и rollback

Для production-релизов используется `.github/workflows/release.yml`. Workflow:

1. повторяет Ruff, strict mypy, pytest и `pip-audit`;
2. выполняет full-history secret scan;
3. строит image;
4. публикует immutable tags в GHCR:
   - `vX.Y.Z`;
   - `sha-<commit>`;
5. создаёт GitHub Release.

Version workflow должна совпадать с `pyproject.toml`.

`docker-compose.prod.yml` — самостоятельный production manifest: в нём намеренно нет `build:`, поэтому production host использует только заранее опубликованный immutable image.

Deploy immutable image:

```bash
export DOMONAP_BOT_IMAGE=ghcr.io/mnevrov/domonap-telegram-bot:v1.0.0

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Rollback выполняется заменой `DOMONAP_BOT_IMAGE` на предыдущий immutable release tag и повторным `pull/up -d` с `-f docker-compose.prod.yml`.

## 11. Live Canary

Read-only Live Canary для реального Domonap API поддерживается workflow `.github/workflows/domonap-live-canary.yml`, но пока является необязательным контролем.

Если repository secret `DOMONAP_CANARY_ACCESS_TOKEN` отсутствует, workflow явно показывает `skipped`, но не блокирует CI или production hardening. После добавления secret те же проверки автоматически начнут контролировать реальные user/keys/call-log/SignalR endpoints; обнаруженная деградация будет блокирующей.

## 12. Обновление из исходников

Для dev/local deployment:

```bash
git pull
docker compose up -d --build
docker compose ps
```

Для production предпочтительнее immutable GHCR image из release workflow, а не сборка текущего checkout непосредственно на сервере.

## 13. Диагностика

```bash
docker compose ps
docker compose logs --tail=200 bot
docker compose logs --tail=100 backup
```

Если `/status` сообщает об истёкшей сессии — выполните новую `/auth`.

Если звонки не приходят — проверьте SignalR/fallback записи в логах и состояние healthcheck.

Если backup не создаются — проверьте `backup` service и доступность `/app/data/storage.db`.

Не публикуйте в issues или логах Telegram token, Domonap tokens, SMS-коды и `STORAGE_ENCRYPTION_KEY`.
