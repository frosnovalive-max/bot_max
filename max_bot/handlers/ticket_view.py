"""Просмотр списка и деталей тикетов (ТЗ, Этап 5).

Все данные — из Core API; здесь только форматирование и клавиатуры.
"""

from __future__ import annotations

import logging

from max_bot.context import AppContext
from max_bot.core.exceptions import CoreApiError
from max_bot.formatters import messages as M
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.keyboards.ticket_menu import (
    back_to_menu_keyboard,
    ticket_actions_keyboard,
    tickets_list_keyboard,
)

logger = logging.getLogger(__name__)

# Статусы, считаемые «активными» (не закрытыми). Конкретный фильтр
# отдан на откуп Core API — бот лишь просит активные.
ACTIVE_STATUSES = ("new", "in_progress", "waiting_answer")


async def show_user_tickets(ctx: AppContext, user_id: int) -> None:
    """Список активных заявок пользователя (кнопки -> детали)."""
    try:
        tickets = await ctx.api.get_user_tickets(user_id, status_filter="active")
    except CoreApiError as e:
        if e.status_code == 403:
            await ctx.reply(user_id, M.user_blocked_message())
        else:
            logger.error("get_user_tickets failed for %s: %s", user_id, e)
            await ctx.reply(user_id, M.service_unavailable_message())
        return

    if not tickets:
        await ctx.reply(
            user_id,
            M.tickets_list_empty_message(),
            inline_keyboard=main_menu_keyboard(),
        )
        return

    await ctx.reply(
        user_id,
        M.tickets_list_message(len(tickets)),
        inline_keyboard=tickets_list_keyboard(tickets),
    )


async def show_ticket_details(ctx: AppContext, user_id: int, ticket_id: str) -> None:
    """Карточка одной заявки + кнопки действий."""
    try:
        ticket = await ctx.api.get_ticket(ticket_id)
    except CoreApiError as e:
        if e.status_code == 404:
            await ctx.reply(
                user_id,
                "❌ Заявка не найдена.",
                inline_keyboard=back_to_menu_keyboard(),
            )
        elif e.status_code == 403:
            await ctx.reply(user_id, M.user_blocked_message())
        else:
            logger.error("get_ticket(%s) failed: %s", ticket_id, e)
            await ctx.reply(user_id, M.service_unavailable_message())
        return

    # Защита от чужих тикетов: сверяем автора, если Core API вернул поле.
    author = ticket.get("author_max_user_id") or (
        (ticket.get("author") or {}).get("max_user_id")
        if isinstance(ticket.get("author"), dict)
        else None
    )
    if author is not None and int(author) != int(user_id):
        await ctx.reply(
            user_id,
            "🚫 Это не ваша заявка.",
            inline_keyboard=back_to_menu_keyboard(),
        )
        return

    await ctx.reply(
        user_id,
        M.ticket_details_message(ticket),
        inline_keyboard=ticket_actions_keyboard(str(ticket.get("id") or ticket_id)),
    )
