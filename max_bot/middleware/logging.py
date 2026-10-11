"""Структурированное логирование всех входящих/исходящих HTTP-операций.

1. setup_logging() — конфигурирует structlog + stdlib logging (уровень из .env).
2. LoggingMiddleware — FastAPI middleware: логирует каждый вебхук/запрос
   (метод, путь, тело для POST, статус ответа, длительность).
3. log_outgoing() — хелпер для явной записи исходящих вызовов клиентов.
"""

from __future__ import annotations

import json
import logging
import time

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from max_bot.core.config import settings


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger("max_bot.http")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Логирует ВХОДЯЩИЕ запросы (вебхуки MAX, healthcheck и т.п.)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        body_excerpt = ""
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                raw = await request.body()
                # кладём обратно, чтобы endpoint тоже смог прочитать тело
                request._body = raw  # type: ignore[attr-defined]
                body_excerpt = raw[:2000].decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body_excerpt = "<unreadable>"

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        logger.info(
            "incoming_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            body=body_excerpt,
        )
        return response


def log_outgoing(direction: str, target: str, payload: dict | None = None) -> None:
    """Явная запись ИСХОДЯЩИХ вызовов (MAX API / Core API)."""
    try:
        snippet = json.dumps(payload, ensure_ascii=False, default=str)[:1500]
    except Exception:  # noqa: BLE001
        snippet = str(payload)[:1500]
    logger.info("outgoing_request", direction=direction, target=target, payload=snippet)
