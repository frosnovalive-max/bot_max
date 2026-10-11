"""Подключение к Redis с graceful fallback (урок №2 из ТЗ).

Redis используется для FSM-состояний многошаговых диалогов.
Если Redis недоступен — НЕ падать, а переключиться на MemoryStorage
(dict в памяти процесса) и записать warning.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def create_redis_client(redis_url: str):
    """Пытается создать и проверить redis.asyncio клиент.

    Возвращает клиент либо None (тогда FSM использует MemoryStorage).
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.ping()
        logger.info("✅ Redis подключен: %s", redis_url)
        return client
    except Exception as e:  # noqa: BLE001 — fallback покрываем намеренно широко
        logger.warning(
            "⚠️ Redis недоступен (%s): %s — продолжаем без него "
            "(FSM будет использовать MemoryStorage)",
            redis_url,
            e,
        )
        return None
