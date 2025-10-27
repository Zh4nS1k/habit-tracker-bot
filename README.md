## Habit Tracker Telegram Bot

Полноценный трекер привычек с анимациями, напоминаниями, гибким расписанием и статистикой. Бот работает через webhook и MongoDB.

### Быстрый старт локально

1. Скопируйте `.env.example` в `.env` и заполните токен бота, строку MongoDB и домен, который выдаст Render (`WEBHOOK_BASE=https://<render-service>.onrender.com`).
2. Установите зависимости и запустите бота в режиме long polling:

```bash
pip install -r requirements.txt
python bot.py
```

3. Для режима webhook используйте `uvicorn app:app --reload`.

### Деплой на Render (free plan 24/7)

1. Залейте репозиторий в GitHub и подключите его к Render.
2. Render автоматически прочитает `render.yaml` и создаст:
   - Web Service `habit-tracker-bot` (`uvicorn app:app`, нужен публичный URL для webhook).
   - Cron `habit-tracker-keepalive`, который будет пинговать сервис каждые 10 минут, не давая ему «уснуть» на бесплатном тарифе.
3. После первого деплоя зайдите в Dashboard Render и укажите переменные окружения:
   - Для Web Service: `BOT_TOKEN`, `MONGO_URI`, `WEBHOOK_BASE` (например, `https://habit-tracker-bot.onrender.com`), `CRON_SECRET` (любая строка, если хотите дополнительно защищать ручку `/cron/reminders`), `TZ`, `DEFAULT_REMINDER_TIME`.
   - Для Cron: `HEALTH_URL` (например, `https://habit-tracker-bot.onrender.com/health`).
4. Перезапустите оба сервиса. Webhook пропишется автоматически при старте.
5. (Опционально) добавьте Render Cron, который дергает `POST /cron/reminders` с заголовком `X-CRON-SECRET`, чтобы разослать напоминания в фиксированное время (например, 20:00 по Астане).

### GitHub Actions

При каждом push/PR прогоняются `pytest` благодаря workflow `.github/workflows/ci.yml`.

### Структура

- `habitbot/` — ядро бота (обработчики, сервисы, модели).
- `app.py` — FastAPI-приложение для webhook.
- `bot.py` — запуск в режиме polling.
- `scripts/ping_health.py` — keep-alive скрипт для Render Cron.
- `tests/` — юнит-тесты расписания привычек.

### Требования

- Python 3.10+
- MongoDB (например, Atlas)
- Render.com для хостинга / cron

