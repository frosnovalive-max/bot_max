"""Обработка нажатий inline-кнопок (callback_data) — центральный роутер.

Формат callback_data, используемый клавиатурами:
  menu                 — главное меню
  help                 — справка
  profile / balance    — команды как кнопками
  ticket_create        — старт FSM создания заявки
  ticket_list          — список заявок
  ticket_message_start — старт диалога «написать в заявку»
  tt:<id>|<name>       — выбор типа (шаг 1 FSM)
  ad:<id>|<name>       — выбор адреса (шаг 2 FSM)
  cab_skip             — пропустить кабинет (шаг 3 FSM)
  confirm_yes/no       — подтверждение отправки (шаг 6 FSM)
  cancel               — отмена текущего диалога
  tv:<ticket_id>       — детали заявки
  tm:<ticket_id>       — написать сообщение в заявку
"""

from __future__ import annotations

import logging

from max_bot.context import AppContext
from max_bot.formatters import messages as M
from max_bot.handlers import commands, ticket_create, ticket_message, ticket_view
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.schemas.events import BotEvent

logger = logging.getLogger(__name__)


async def handle_callback(ctx: AppContext, event: BotEvent) -> None:
    cb = (event.callback_data or "").strip()
    user_id = event.user_id

    # 0) Отмена — универсальная, чистим любые активные FSM
    if cb == "cancel":
        cancelled = await ticket_create.try_cancel(ctx, event)
        cancelled = await ticket_message.try_cancel(ctx, event) or cancelled
        await ctx.reply(
            user_id,
            M.cancel_message() if cancelled else M.nothing_to_cancel_message(),
            inline_keyboard=main_menu_keyboard(),
        )
        return

    # 1) Сначала отдаём управление активным FSM-диалогам
    if await ticket_message.handle_callback(ctx, event):
        return
    if await ticket_create.handle_callback(ctx, event):
        return

    # 2) Глобальные кнопки меню
    if cb == "menu":
        await ctx.reply(
            user_id, M.welcome_message(await _first_name(ctx, event)),
            inline_keyboard=main_menu_keyboard(),
        )
    elif cb == "help":
        await commands.cmd_help(ctx, event)
    elif cb == "profile":
        await commands.cmd_profile(ctx, event)
    elif cb == "balance":
        await commands.cmd_balance(ctx, event)
    elif cb == "ticket_create":
        await ticket_create.start_dialog(ctx, event)
    elif cb == "ticket_list":
        await ticket_view.show_user_tickets(ctx, user_id)
    elif cb == "ticket_message_start":
        await ticket_message.start_from_list(ctx, event)
    elif cb.startswith("tv:"):
        await ticket_view.show_ticket_details(ctx, user_id, cb[3:])
    elif cb.startswith("tm:"):
        # Если FSM сообщения не подхватил выше (нет активного состояния) —
        # стартуем диалог для этой заявки.
        await ticket_message.start_for_ticket(ctx, user_id, cb[3:])
    else:
        logger.info("Unknown callback_data from user %s: %r", user_id, cb)
        await ctx.reply(
            user_id,
            "🤔 Кнопка мне неизвестна. Вернитесь в меню:",
            inline_keyboard=main_menu_keyboard(),
        )


async def _first_name(ctx: AppContext, event: BotEvent) -> str:
    try:
        profile = await ctx.max_api.get_user_profile(event.user_id)
        name = (profile.get("first_name") or profile.get("name") or "").split(" ")[0]
        if name:
            return name
    except Exception as e:  # noqa: BLE001 — decorative data, never block UI
        logger.debug("profile fetch for greeting failed: %s", e)
    sender = (event.raw.get("message") or {}).get("sender") or {}
    return (sender.get("name") or "").split(" ")[0] or "гость"
