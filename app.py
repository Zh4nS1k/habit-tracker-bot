import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from aiogram import types

from habitbot.bot import bot, dp, reminder_service
from habitbot.config import get_settings
from habitbot.db import ensure_indexes, get_client


settings = get_settings()
app = FastAPI()
log = logging.getLogger("habitbot.app")


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.post(f"/webhook/{settings.bot_token}")
async def telegram_webhook(request: Request):
    data = await request.json()
    try:
        update = types.Update.model_validate(data)
    except Exception as exc:  # pragma: no cover - aiogram validation
        raise HTTPException(400, f"Invalid update payload: {exc}") from exc
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.post("/cron/reminders")
async def trigger_reminders(request: Request):
    secret = request.headers.get("X-CRON-SECRET") or request.query_params.get("secret")
    if settings.cron_secret and secret != settings.cron_secret:
        raise HTTPException(403, "Forbidden")
    await reminder_service.tick()
    return {"ok": True}


@app.on_event("startup")
async def on_startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await ensure_indexes()
    url = f"{settings.webhook_base}/webhook/{settings.bot_token}"
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url, drop_pending_updates=True)
    reminder_service.start()
    log.info("Webhook set to %s", url)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        await reminder_service.stop()
        await bot.delete_webhook(drop_pending_updates=False)
    finally:
        await bot.session.close()
        get_client().close()
