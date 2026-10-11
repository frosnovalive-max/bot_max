"""Добавление сообщения в тикет (мини-FSM: выбор заявки -> текст).

callback_data:
  tm:<ticket_id>       — «написать в заявку №N» (из карточки тикета)
  ticket_message_start — начать с выбора активной заявки
Текстовое сообщение в состоянии WAITING_FOR_MESSAGE -> POST /tickets/{id}/messages.
"""

from __future__ import annotations

import logging

from max_bot.context import AppContext
from max_bot.core.exceptions import CoreApiError
from max_bot.formatters import messages as M
from max_bot.fsm.states import TicketMessageState as MS
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.keyboards.ticket_menu import tickets_list_keyboard
from max_bot.schemas.events import BotEvent

logger = logging.getLogger(__name__)


def is_active(st: dict) -> bool:
    state = st.get("state") or ""
    return any(state == s.value for s in MS)


async def try_cancel(ctx: AppContext, event: BotEvent) -> bool:
    st = await ctx.storage.get_state(event.user_id)
    if is_active(st):
        await ctx.storage.clear_state(event.user_id)
        return True
    return False


# --------------------------------------------------------------------- #
# Вход в диалог
# --------------------------------------------------------------------- #
async def start_for_ticket(ctx: AppContext, user_id: int, ticket_id: str) -> None:
    """Из карточки тикета: сразу просим текст сообщения."""
    number = ticket_id
    try:
        ticket = await ctx.api.get_ticket(ticket_id)
        number = ticket.get("number") or ticket.get("ticket_number") or ticket_id
    except CoreApiError as e:
        logger.warning("get_ticket(%s) failed in message dialog: %s", ticket_id, e)
    await ctx.storage.set_state(
        user_id,
        MS.WAITING_FOR_MESSAGE.value,
        {"ticket_id": ticket_id, "ticket_number": number},
    )
    await ctx.reply(user_id, M.ask_ticket_message_text(number, ticket_id))


async def start_from_list(ctx: AppContext, event: BotEvent) -> None:
    """«💬 Написать в заявку» из главного меню: сначала выбор заявки."""
    user_id = event.user_id
    try:
        tickets = await ctx.api.get_user_tickets(user_id, status_filter="active")
    except CoreApiError as e:
        if e.status_code == 403:
            await ctx.reply(user_id, M.user_blocked_message())
        else:
            await ctx.reply(user_id, M.service_unavailable_message())
        return
    if not tickets:
        await ctx.reply(
            user_id,
            M.tickets_list_empty_message(),
            inline_keyboard=main_menu_keyboard(),
        )
        return
    await ctx.storage.set_state(
        user_id, MS.WAITING_FOR_TICKET.value, {}
    )
    await ctx.reply(
        user_id,
        "💬 Выберите заявку, в которую хотите написать (кнопкой):",
        inline_keyboard=_select_keyboard(tickets),
    )


def _select_keyboard(tickets: list[dict]) -> list[list[dict]]:
    """Как tickets_list_keyboard, но callback_data=tm:<id> (написать, не смотреть)."""
    rows = []
    for tk in tickets[:20]:
        tid = tk.get("id") or tk.get("uuid")
        num = tk.get("number") or tk.get("ticket_number") or tid
        title = (tk.get("title") or "")[:30]
        rows.append([{"text": f"№{num} {title}", "callback_data": f"tm:{tid}"}])
    rows.append([{"text": "❌ Отменить", "callback_data": "cancel"}])
    return rows


# --------------------------------------------------------------------- #
# Callback-хук (вызывается из callbacks.py ДО FSM создания тикета)
# --------------------------------------------------------------------- #
async def handle_callback(ctx: AppContext, event: BotEvent) -> bool:
    st = await ctx.storage.get_state(event.user_id)
    state = st.get("state") or ""
    cb = event.callback_data

    if cb == "cancel" and is_active(st):
        await ctx.storage.clear_state(event.user_id)
        await ctx.reply(
            event.user_id, M.cancel_message(), inline_keyboard=main_menu_keyboard()
        )
        return True

    # Нажатие кнопки tm:<id> — в любом контексте (из карточки или из выбора)
    if cb.startswith("tm:"):
        ticket_id = cb[3:]
        if state == MS.WAITING_FOR_TICKET.value or not is_active(st):
            await start_for_ticket(ctx, event.user_id, ticket_id)
            return True

    return False


# --------------------------------------------------------------------- #
# Текст сообщения в диалоге
# --------------------------------------------------------------------- #
async def handle_text(ctx: AppContext, event: BotEvent) -> bool:
    st = await ctx.storage.get_state(event.user_id)
    if st.get("state") != MS.WAITING_FOR_MESSAGE.value:
        return False
    data = st.get("data") or {}
    ticket_id = data.get("ticket_id")
    text = event.text.strip()
    if not ticket_id or not text:
        await ctx.storage.clear_state(event.user_id)
        await ctx.reply(
            event.user_id,
            M.nothing_to_cancel_message(),
            inline_keyboard=main_menu_keyboard(),
        )
        return True

    try:
        await ctx.api.add_ticket_message(
            ticket_id=ticket_id,
            author_max_user_id=event.user_id,
            text=text[:4000],
        )
    except CoreApiError as e:
        if e.status_code == 403:
            await ctx.reply(event.user_id, M.user_blocked_message())
        elif e.status_code == 404:
            await ctx.reply(event.user_id, "❌ Заявка не найдена.")
        else:
            await ctx.reply(event.user_id, M.service_unavailable_message())
        return True

    await ctx.storage.clear_state(event.user_id)
    await ctx.reply(
        event.user_id,
        M.message_added_message(data.get("ticket_number", ticket_id)),
        inline_keyboard=main_menu_keyboard(),
    )
    return True
