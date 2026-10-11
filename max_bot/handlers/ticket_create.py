"""Многошаговый FSM-диалог создания тикета (ТЗ, п.9.3 — 6 шагов).

Поток:
  тип -> адрес -> кабинет (текст/пропуск) -> тема (текст) ->
  описание (текст) -> сводка + подтверждение -> POST /tickets в Core API.

Бот НЕ проверяет лимиты/баллы — это делает Core API; бот лишь транслирует
ошибки 402/403/429/5xx понятными пользователю сообщениями.
"""

from __future__ import annotations

import logging

from max_bot.context import AppContext
from max_bot.core.exceptions import CoreApiError
from max_bot.formatters import messages as M
from max_bot.fsm.states import TicketCreateState as S
from max_bot.keyboards.confirmation import confirm_keyboard
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.keyboards.ticket_menu import (
    addresses_keyboard,
    skip_cabinet_keyboard,
    types_keyboard,
)
from max_bot.schemas.events import BotEvent

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Работа с состоянием
# --------------------------------------------------------------------- #
async def get_state(ctx: AppContext, user_id: int) -> dict:
    return await ctx.storage.get_state(user_id)


async def set_state(ctx: AppContext, user_id: int, state: str, data: dict) -> None:
    await ctx.storage.set_state(user_id, state, data)


async def clear_state(ctx: AppContext, user_id: int) -> None:
    await ctx.storage.clear_state(user_id)


def is_active(st: dict) -> bool:
    """Состояние принадлежит именно диалогу создания тикета?"""
    state = st.get("state") or ""
    return any(state == s.value for s in S)


async def try_cancel(ctx: AppContext, event: BotEvent) -> bool:
    """/cancel внутри диалога создания заявки."""
    st = await ctx.storage.get_state(event.user_id)
    if is_active(st):
        await clear_state(ctx, event.user_id)
        return True
    return False


# --------------------------------------------------------------------- #
# Шаг 1: старт диалога (по кнопке «🆕 Создать заявку» или /new)
# --------------------------------------------------------------------- #
async def start_dialog(ctx: AppContext, event: BotEvent) -> None:
    user_id = event.user_id
    try:
        types = await ctx.api.get_ticket_types()
    except CoreApiError as e:
        logger.error("get_ticket_types failed: %s", e)
        await ctx.reply(user_id, M.service_unavailable_message())
        return
    if not types:
        await ctx.reply(
            user_id,
            "❌ Справочник типов заявок пуст. Обратитесь к администратору.",
            inline_keyboard=main_menu_keyboard(),
        )
        return
    await set_state(ctx, user_id, S.WAITING_FOR_TYPE.value, {})
    await ctx.reply(
        user_id, M.ask_type_message(), inline_keyboard=types_keyboard(types)
    )


# --------------------------------------------------------------------- #
# Обработка нажатий кнопок диалога (вызывается из callbacks.py)
# Возвращает True, если callback относится к этому FSM.
# --------------------------------------------------------------------- #
async def handle_callback(ctx: AppContext, event: BotEvent) -> bool:
    user_id = event.user_id
    st = await ctx.storage.get_state(user_id)
    if not is_active(st):
        return False
    state, data = st["state"], dict(st.get("data") or {})
    cb = event.callback_data

    # Универсальная отмена
    if cb == "cancel" or cb == "confirm_no":
        await clear_state(ctx, user_id)
        await ctx.reply(
            user_id, M.cancel_message(), inline_keyboard=main_menu_keyboard()
        )
        return True

    # Шаг 1 -> 2: выбран тип
    if state == S.WAITING_FOR_TYPE.value and cb.startswith("tt:"):
        payload = cb[3:]
        type_id, _, type_name = payload.partition("|")
        data.update({"type_id": type_id, "type_name": type_name or "—"})
        try:
            addresses = await ctx.api.get_addresses()
        except CoreApiError as e:
            logger.error("get_addresses failed: %s", e)
            await ctx.reply(user_id, M.service_unavailable_message())
            await set_state(ctx, user_id, state, data)
            return True
        if not addresses:
            await ctx.reply(
                user_id,
                "❌ Справочник адресов пуст. Обратитесь к администратору.",
                inline_keyboard=main_menu_keyboard(),
            )
            await clear_state(ctx, user_id)
            return True
        await set_state(ctx, user_id, S.WAITING_FOR_ADDRESS.value, data)
        await ctx.reply(
            user_id,
            M.ask_address_message(data["type_name"]),
            inline_keyboard=addresses_keyboard(addresses),
        )
        return True

    # Шаг 2 -> 3: выбран адрес
    if state == S.WAITING_FOR_ADDRESS.value and cb.startswith("ad:"):
        payload = cb[3:]
        address_id, _, address_name = payload.partition("|")
        data.update({"address_id": address_id, "address_name": address_name or "—"})
        await set_state(ctx, user_id, S.WAITING_FOR_CABINET.value, data)
        await ctx.reply(
            user_id,
            M.ask_cabinet_message(data["address_name"]),
            inline_keyboard=skip_cabinet_keyboard(),
        )
        return True

    # Шаг 3: «пропустить кабинет» сразу темой не является — идём к шагу 4 текстом
    if state == S.WAITING_FOR_CABINET.value and cb == "cab_skip":
        data["cabinet"] = None
        await set_state(ctx, user_id, S.WAITING_FOR_TITLE.value, data)
        await ctx.reply(user_id, M.ask_title_message())
        return True

    # Шаг 6: подтверждение
    if state == S.WAITING_FOR_CONFIRMATION.value and cb == "confirm_yes":
        await _finalize(ctx, event, data)
        return True

    return False


# --------------------------------------------------------------------- #
# Обработка текстовых сообщений внутри диалога (шаги 3, 4, 5)
# Возвращает True, если текст потреблен FSM.
# --------------------------------------------------------------------- #
async def handle_text(ctx: AppContext, event: BotEvent) -> bool:
    user_id = event.user_id
    st = await ctx.storage.get_state(user_id)
    if not is_active(st):
        return False
    state, data = st["state"], dict(st.get("data") or {})
    text = event.text.strip()

    if state == S.WAITING_FOR_CABINET.value:
        data["cabinet"] = text[:100]
        await set_state(ctx, user_id, S.WAITING_FOR_TITLE.value, data)
        await ctx.reply(user_id, M.ask_title_message())
        return True

    if state == S.WAITING_FOR_TITLE.value:
        if len(text) < 3:
            await ctx.reply(
                user_id,
                "⚠️ Тема слишком короткая (минимум 3 символа). Попробуйте ещё раз "
                "или отправьте /cancel.",
            )
            return True
        data["title"] = text[:200]
        await set_state(ctx, user_id, S.WAITING_FOR_DESCRIPTION.value, data)
        await ctx.reply(user_id, M.ask_description_message())
        return True

    if state == S.WAITING_FOR_DESCRIPTION.value:
        if len(text) < 5:
            await ctx.reply(
                user_id,
                "⚠️ Описание слишком короткое (минимум 5 символов). "
                "Попробуйте ещё раз или отправьте /cancel.",
            )
            return True
        data["description"] = text[:2000]
        await set_state(ctx, user_id, S.WAITING_FOR_CONFIRMATION.value, data)
        await ctx.reply(
            user_id,
            M.ticket_summary_message(
                type_name=data.get("type_name", "—"),
                address_name=data.get("address_name", "—"),
                cabinet=data.get("cabinet"),
                title=data.get("title", "—"),
                description=data.get("description", "—"),
            ),
            inline_keyboard=confirm_keyboard(),
        )
        return True

    # На шагах с кнопками текст игнорируем вежливо
    if state in (S.WAITING_FOR_TYPE.value, S.WAITING_FOR_ADDRESS.value):
        await ctx.reply(
            user_id, "☝️ Пожалуйста, выберите вариант кнопкой из меню ниже."
        )
        return True

    return False


# --------------------------------------------------------------------- #
# Финал: создание тикета через Core API + трансляция ошибок
# --------------------------------------------------------------------- #
async def _finalize(ctx: AppContext, event: BotEvent, data: dict) -> None:
    user_id = event.user_id
    try:
        ticket = await ctx.api.create_ticket(
            author_max_user_id=user_id,
            type_id=data["type_id"],
            address_id=data["address_id"],
            cabinet=data.get("cabinet"),
            title=data["title"],
            description=data["description"],
        )
    except CoreApiError as e:
        await _handle_create_error(ctx, user_id, e)
        return

    await clear_state(ctx, user_id)
    number = ticket.get("number") or ticket.get("ticket_number") or ticket.get("id")
    balance = None
    points = ticket.get("balance_after") or ticket.get("user_balance")
    if points is not None:
        balance = points
    else:
        try:
            p = await ctx.api.get_user_points(user_id)
            balance = p.get("points", p.get("balance"))
        except CoreApiError:
            balance = None
    await ctx.reply(
        user_id,
        M.ticket_created_message(number, balance),
        inline_keyboard=main_menu_keyboard(),
    )


async def _handle_create_error(ctx: AppContext, user_id: int, e: CoreApiError) -> None:
    """402/403/429/5xx -> понятные сообщения (ТЗ, п.9.3). Диалог сохраняется,
    чтобы пользователь мог скорректировать данные (например, дождаться баллов)."""
    logger.warning("create_ticket error for %s: %s", user_id, e)
    if e.status_code == 402:
        balance = "?"
        detail = e.detail.lower()
        # Пытаемся вытащить баланс из detail вида "Insufficient points: 3 < 10"
        import re

        m = re.search(r"(\d+)", detail)
        if "current" in detail and m:
            balance = m.group(1)
        else:
            try:
                p = await ctx.api.get_user_points(user_id)
                balance = p.get("points", p.get("balance", "?"))
            except CoreApiError:
                pass
        await ctx.reply(user_id, M.insufficient_points_message(balance))
    elif e.status_code == 403:
        await ctx.reply(user_id, M.user_blocked_message())
        await clear_state(ctx, user_id)
    elif e.status_code == 429:
        await ctx.reply(user_id, M.rate_limited_message())
    elif e.status_code >= 500 or e.status_code == 0:
        await ctx.reply(user_id, M.service_unavailable_message())
    else:
        await ctx.reply(user_id, M.ticket_create_error_message(e.detail))
