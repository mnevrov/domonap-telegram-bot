# Инструкция: установка, запуск и использование Domonap Telegram Bot

Бот управляет домофоном Domonap через Telegram — открывает двери, показывает список домофонов и присылает уведомления о входящих звонках. Работает автономно, без Home Assistant.

## 1. Требования

- Python **3.12+** для запуска без Docker;
- Docker и Docker Compose для рекомендуемого контейнерного запуска;
- токен Telegram-бота от [@BotFather](https://t.me/BotFather);
- номер телефона, привязанный к аккаунту Domonap;
- Telegram user ID хотя бы одного разрешённого пользователя.

## 2. Получение кода

```bash
git clone <repo-url> domonap-telegram-bot
cd domonap-telegram-bot
```

## 3. Настройка `.env`

```bash
cp .env.example .env
```

Откройте `.env` и заполните переменные:

| Переменная | Что указать |
|---|---|
| `TELEGRAM_BOT_TOKEN` | **Обязательно.** Токен, выданный @BotFather |
| `ALLOWED_TELEGRAM_USER_IDS` | **Обязательно.** Telegram user ID разрешённых пользователей через запятую |
| `ADMIN_TELEGRAM_USER_IDS` | Telegram user ID администраторов; каждый admin обязан также быть разрешённым пользователем |
| `DOMONAP_PHONE` | Номер телефона аккаунта Domonap в международном формате |
| `DOMONAP_REGISTER_DEVICE_TOKEN` | `false` по умолчанию: не вызывать `UpdateDeviceToken` и не перехватывать push-маршрут официального приложения; `true` — явно зарегистрировать deviceToken бота |
| `STORAGE_PATH` | Путь к SQLite, по умолчанию `data/storage.db` |
| `LOG_LEVEL` | `INFO` по умолчанию, `DEBUG` для отладки |
| `CALL_WATCHER_ENABLED` | `true`, чтобы получать уведомления о входящих звонках |

⚠️ **Доступ работает fail-closed.** Если `ALLOWED_TELEGRAM_USER_IDS` пуст, приложение **откажется запускаться**. Пустой список никогда не означает публичный доступ.

Администратор должен одновременно входить в effective allow-list. Пользователи и права, добавленные через admin UI, сохраняются в SQLite и восстанавливаются при следующем запуске.

Для совместной работы с официальным приложением рекомендуется оставить `DOMONAP_REGISTER_DEVICE_TOKEN=false`. При SMS-авторизации `deviceToken` по-прежнему передаётся в `ConfirmAuthorization`, но отдельный запрос `UpdateDeviceToken` не выполняется. Real-time уведомления бота при этом могут приходить через SignalR, не меняя push-маршрут мобильного приложения.

Пример `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:AAExampleTokenFromBotFather
ALLOWED_TELEGRAM_USER_IDS=111111111,222222222
ADMIN_TELEGRAM_USER_IDS=111111111
DOMONAP_PHONE=+79991234567
DOMONAP_REGISTER_DEVICE_TOKEN=false
STORAGE_PATH=data/storage.db
LOG_LEVEL=INFO
CALL_WATCHER_ENABLED=true
```

## 4. Запуск

### Вариант A — Docker

```bash
docker compose up --build -d
```

Проверить работу:

```bash
docker compose logs -f
```

Остановить:

```bash
docker compose down
```

SQLite и токены сохраняются в `./data`, которая смонтирована в контейнер как volume.

### Вариант B — без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m domonap_bot.main
```

Для остановки — `Ctrl+C`. Для постоянной работы рекомендуется Docker или systemd.

## 5. Первая авторизация в Domonap

Авторизация происходит через SMS-код и доступна только действующему администратору.

1. Откройте диалог с ботом и отправьте `/start`.
2. Отправьте `/auth` — на `DOMONAP_PHONE` придёт SMS-код.
3. Отправьте `/code <код>`, например `/code 4821`. Бот пытается удалить сообщение с кодом после обработки.
4. Отправьте `/status`, чтобы проверить соединение. Номер телефона в статусе отображается в маскированном виде.

Токены сохраняются в SQLite и автоматически обновляются. `/logout` очищает сохранённую Domonap-сессию.

## 6. Команды

| Команда | Кто может использовать | Что делает |
|---|---|---|
| `/start` | разрешённые | Главное меню |
| `/status` | разрешённые | Статус авторизации без полного номера телефона |
| `/doors` | разрешённые | Список доступных дверей |
| `/open` | разрешённые | Выбор и открытие двери |
| `/auth` | admin | Запрос SMS-кода |
| `/code <code>` | admin | Подтверждение SMS-кода |
| `/logout` | admin | Сброс Domonap-сессии |

Последнего действующего администратора удалить через admin UI нельзя.

## 7. Уведомления о входящих звонках

Если `CALL_WATCHER_ENABLED=true`, watcher отправляет уведомления текущим разрешённым пользователям.

Основной механизм:

1. real-time SignalR WebSocket к Domonap Notification Hub;
2. при завершении или сбое SignalR — временный fallback на polling журнала звонков;
3. затем новая попытка SignalR;
4. call ID дедуплицируются ограниченным упорядоченным кэшем;
5. карта `doorId → дверь` периодически обновляется и принудительно перечитывается при неизвестном `doorId`.

Уведомление может содержать:

- название/адрес двери;
- время звонка;
- фото/preview;
- кнопку «Открыть»;
- кнопку «Видео», если URL доступен.

Отключить watcher:

```env
CALL_WATCHER_ENABLED=false
```

## 8. Обновление и обслуживание

```bash
git pull
docker compose up --build -d
```

Логи:

```bash
docker compose logs -f --tail=100
```

Для повторной авторизации выполните `/logout`, затем `/auth` и `/code <code>`.

## 9. Частые проблемы

- **Бот не запускается** — проверьте `TELEGRAM_BOT_TOKEN` и убедитесь, что `ALLOWED_TELEGRAM_USER_IDS` не пуст.
- **«Access denied»** — ваш Telegram ID отсутствует в effective allow-list.
- **Админ-команды недоступны** — admin ID должен одновременно входить в allow-list.
- **Не приходят звонки** — проверьте `CALL_WATCHER_ENABLED=true`, авторизацию и логи SignalR/polling.
- **`/open` не показывает двери** — проверьте `/status` и действительность Domonap-сессии.
