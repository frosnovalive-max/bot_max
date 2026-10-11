"""POST /webhook/max — прием событий от платформы MAX (ТЗ, п.9.1).

Маршрут зарегистрирован на settings.webhook_path, т.е. итоговый URL для
панели MAX: settings.full_webhook_url = BOT_BASE_URL + WEBHOOK_PATH.
⚠️ НЕ путать с MAX_API_URL (куда шлём мы) — урок №8 из ТЗ.

Ответ всегда 200 {"status":"ok"} — чтобы MAX не считал доставку неудачной
и не ретраил штатные ситуации; внутренние ошибки логируются.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from max_bot.core.config import settings
from max_bot.formatters import messages as M
from max_bot.handlers.callbacks import handle_callback
from max_bot.handlers.commands import handle_text_message
from max_bot.handlers.ticket_create import handle_text as ticket_create_handle_text
from max_bot.handlers.ticket_message import handle_text as ticket_message_handle_text
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.schemas.events import BotEvent, parse_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(settings.webhook_path)
async def max_webhook(request: Request):
    """Прием вебхуков от MAX API."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        logger.warning("Webhook received non-JSON body")
        return {"status": "ok"}

    # Проверка секрета вебхука (если задан в .env)
    secret = settings.max_webhook_secret
    if secret and secret != "your_webhook_secret_here":
        got = request.headers.get("X-Webhook-Secret", "")
        if got != secret:
            logger.warning("Webhook rejected: bad X-Webhook-Secret header")
            return {"status": "ok"}  # не даём MAX ретраить мусор

    ctx = request.app.state.ctx
    event = parse_event(payload)

    # Запоминаем chat_id для последующих исходящих сообщений
    if event.user_id and event.chat_id:
        ctx.remember_chat(event.user_id, event.chat_id)

    try:
        if event.event_type == "message_new":
            await handle_new_message(ctx, event)
        elif event.event_type == "message_callback":
            await handle_cb(ctx, event)
        else:
            logger.info(
                "Ignoring unsupported update_type: %r",
                event.raw.get("update_type") or event.raw.get("type"),
            )
    except Exception:  # noqa: BLE001 — webhook MUST answer 200
        logger.exception("Unhandled error while processing event %s", event.event_type)

    return {"status": "ok"}


async def handle_new_message(ctx, event: BotEvent) -> None:
    """Новое текстовое сообщение: команды -> FSM-тексты -> подсказка."""
    if not event.user_id:
        return
    # Служебные сообщения (например, авто-приветствие при подписке) -> /start
    if event.is_service_message or not event.text.strip():
        from max_bot.handlers.commands import cmd_start

        await cmd_start(ctx, event)
        return

    # 1) Команды (/start, /help, /cancel и т.д.)
    if await handle_text_message(ctx, event):
        return
    # 2) Активные FSM ждут текст?
    if await ticket_message_handle_text(ctx, event):
        return
    if await ticket_create_handle_text(ctx, event):
        return
    # 3) Свободный текст вне диалога — подсказка
    await ctx.reply(
        event.user_id,
        M.free_text_hint_message(),
        inline_keyboard=main_menu_keyboard(),
    )


async def handle_cb(ctx, event: BotEvent) -> None:
    """Нажатие кнопки."""
    if not event.user_id:
        return
    await handle_callback(ctx, event)
