"""Воркер уведомлений: standalone-процесс (ТЗ, раздел 12).

Периодически (каждые POLL_INTERVAL секунд) опрашивает Core API на наличие
pending-уведомлений и отправляет их в MAX. Каждое уведомление помечается
sent или failed — бизнес-логика дедупликации/повторов живёт в Core API.

Запуск:
    python -m max_bot.notification_worker
(в docker-compose — сервис notification-worker с тем же image/requirements).
"""

from __future__ import annotations

import asyncio
import logging

import structlog

from max_bot.core.api_client import ApiClient
from max_bot.core.config import settings
from max_bot.core.exceptions import CoreApiError, MaxApiError
from max_bot.core.max_client import MaxClient

logger = structlog.get_logger("max_bot.notifier")

POLL_INTERVAL_SECONDS = 10


async def run_worker() -> None:
    # stdlib logging тоже настроим, чтобы сообщения клиентов были видны
    logging.basicConfig(level=settings.log_level, format="%(message)s")

    api = ApiClient()
    max_api = MaxClient()

    logger.info("🔔 Notification worker запущен (poll every %ss)", POLL_INTERVAL_SECONDS)

    try:
        while True:
            try:
                notifications = await api.get_pending_notifications()
                for notif in notifications:
                    await _process_one(api, max_api, notif)
            except CoreApiError as e:
                logger.error("❌ Ошибка опроса уведомлений: %s", e)
            except Exception as e:  # noqa: BLE001 — worker must never die
                logger.exception("❌ Неожиданная ошибка цикла воркера: %s", e)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await api.close()
        await max_api.close()


async def _process_one(api: ApiClient, max_api: MaxClient, notif: dict) -> None:
    """Отправка одного уведомления + отметка результата в Core API."""
    notif_id = str(notif.get("id") or notif.get("uuid") or "")
    user_max_id = notif.get("user_max_id") or notif.get("max_user_id")
    text = notif.get("message") or notif.get("text") or ""

    if not notif_id or not user_max_id or not text:
        logger.warning("⚠️ Пропущено некорректное уведомление: %r", notif)
        return

    try:
        await max_api.send_message(user_id=int(user_max_id), text=text)
        await api.mark_notification_sent(notif_id)
        logger.info("📨 Уведомление %s отправлено пользователю %s", notif_id, user_max_id)
    except MaxApiError as e:
        error_text = f"MAX delivery failed: {e}"
        logger.error("❌ Ошибка отправки %s: %s", notif_id, error_text)
        try:
            await api.mark_notification_failed(notif_id, error_text)
        except CoreApiError as ce:
            logger.error("❌ Не удалось пометить %s как failed: %s", notif_id, ce)
    except CoreApiError as e:
        # Не смогли отметить sent — следующее голосование повторит доставку;
        # дедупликация на стороне Core API.
        logger.error("❌ Core API отметка для %s не удалась: %s", notif_id, e)
    except Exception as e:  # noqa: BLE001
        logger.exception("❌ Неожиданная ошибка доставки %s: %s", notif_id, e)
        try:
            await api.mark_notification_failed(notif_id, str(e))
        except CoreApiError:
            pass


if __name__ == "__main__":
    asyncio.run(run_worker())
