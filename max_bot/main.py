"""Точка входа: FastAPI app + lifespan + роутеры.

Запуск:
    python -m max_bot.main            (модуль, как в Dockerfile CMD)
    uvicorn max_bot.main:app          (для разработки)

Lifespan:
  1. настраивает structlog;
  2. создаёт FSM-хранилище (Redis -> fallback MemoryStorage);
  3. создаёт httpx-клиенты (MAX + Core API);
  4. best-effort регистрирует вебхук в MAX (не крэшит при недоступности);
  5. при остановке корректно закрывает соединения.

Важно: config уже выполнен fail-fast на MAX_BOT_TOKEN при импорте —
без токена процесс не стартует вообще (урок №6 из ТЗ).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from max_bot.core.api_client import ApiClient
from max_bot.core.config import settings
from max_bot.core.exceptions import MaxApiError
from max_bot.core.max_client import MaxClient
from max_bot.context import AppContext
from max_bot.fsm.storage import create_storage
from max_bot.handlers.webhook import router as webhook_router
from max_bot.middleware.logging import LoggingMiddleware, setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("🚀 Запуск бота MAX «IT-служба колледжа»")
    logger.info("Webhook будет доступен по: %s", settings.full_webhook_url)

    storage = await create_storage(settings.redis_url)
    api = ApiClient()
    max_api = MaxClient()
    app.state.ctx = AppContext(api=api, max_api=max_api, storage=storage)

    # Регистрация вебхука — best effort: если MAX API недоступен прямо сейчас,
    # логируем предупреждение и продолжаем работать (вебхук можно зарегистрировать
    # вручную через POST /webhook/register или повторить позже).
    try:
        await max_api.set_webhook()
        logger.info("✅ Вебхук зарегистрирован: %s", settings.full_webhook_url)
    except MaxApiError as e:
        logger.warning(
            "⚠️ Не удалось автоматически зарегистрировать вебхук (%s). "
            "Проверьте BOT_BASE_URL и зарегистрируйте вручную: %s",
            e,
            settings.full_webhook_url,
        )
    except Exception:  # noqa: BLE001
        logger.exception("⚠️ Unexpected error during webhook registration")

    yield

    logger.info("🛑 Остановка бота, закрытие соединений")
    await max_api.close()
    await api.close()
    await storage.close()


app = FastAPI(
    title="MAX Bot — IT-служба колледжа",
    description="Тонкий клиент MAX: вебхуки -> Core API -> ответы в MAX.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


@app.get("/healthz")
async def healthz():
    """Healthcheck для Docker/мониторинга."""
    return {"status": "ok"}


@app.post("/webhook/register")
async def register_webhook_manually():
    """Ручая перерегистрация вебхука (например, после смены туннельного URL)."""
    ctx: AppContext = app.state.ctx
    try:
        result = await ctx.max_api.set_webhook()
        return {"status": "ok", "webhook_url": settings.full_webhook_url, "result": result}
    except MaxApiError as e:
        return {
            "status": "error",
            "webhook_url": settings.full_webhook_url,
            "detail": str(e),
        }


def run() -> None:
    uvicorn.run(
        "max_bot.main:app",
        host="0.0.0.0",
        port=settings.bot_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
