"""Хранилище FSM-состояний с обязательным fallback на память (ТЗ, п.8.2).

Урок №2 прошлой итерации: жесткая зависимость от Redis роняла бота.
Здесь: RedisStorage (TTL 1 час) → при любой недоступности Redis
автоматически используется MemoryStorage (dict в памяти процесса).
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class MemoryStorage:
    """In-memory fallback. Состояния теряются при перезапуске."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    async def get_state(self, user_id: int) -> dict:
        return self._data.get(str(user_id), {})

    async def set_state(self, user_id: int, state: str, data: dict) -> None:
        self._data[str(user_id)] = {"state": state, "data": data}

    async def clear_state(self, user_id: int) -> None:
        self._data.pop(str(user_id), None)

    async def close(self) -> None:
        self._data.clear()


class RedisStorage:
    """FSM в Redis с TTL 3600 сек (зависший диалог сам сбросится)."""

    def __init__(self, redis_client) -> None:
        self.redis = redis_client
        self.prefix = "fsm:"

    async def get_state(self, user_id: int) -> dict:
        try:
            raw = await self.redis.get(f"{self.prefix}{user_id}")
        except Exception as e:  # сеть могла упасть после старта — не crashим
            logger.warning("⚠️ Redis get_state failed (%s); state lost for run", e)
            return {}
        return json.loads(raw) if raw else {}

    async def set_state(self, user_id: int, state: str, data: dict) -> None:
        try:
            await self.redis.set(
                f"{self.prefix}{user_id}",
                json.dumps({"state": state, "data": data}, ensure_ascii=False),
                ex=3600,  # TTL 1 час
            )
        except Exception as e:
            logger.warning("⚠️ Redis set_state failed: %s", e)

    async def clear_state(self, user_id: int) -> None:
        try:
            await self.redis.delete(f"{self.prefix}{user_id}")
        except Exception as e:
            logger.warning("⚠️ Redis clear_state failed: %s", e)

    async def close(self) -> None:
        try:
            await self.redis.aclose()
        except Exception:
            pass


async def create_storage(redis_url: str):
    """Фабрика: пытается Redis, падает на MemoryStorage (никогда не crash)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.ping()
        logger.info("✅ FSM: Redis подключен")
        return RedisStorage(client)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "⚠️ FSM: Redis недоступен (%s), используем MemoryStorage "
            "(состояния теряются при перезапуске)",
            e,
        )
        return MemoryStorage()
