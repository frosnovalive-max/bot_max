"""Обработчики команд: /start, /help, /my_tickets, /profile, /balance, /cancel.

Бот — тонкий клиент: за данными обращаемся в Core API (ctx.api),
за профилем MAX — в MaxClient. Никакой бизнес-логики здесь нет.
"""

from __future__ import annotations

import logging

from max_bot.context import AppContext
from max_bot.core.exceptions import CoreApiError, MaxApiError
from max_bot.formatters import messages as M
from max_bot.keyboards.main_menu import main_menu_keyboard
from max_bot.keyboards.ticket_menu import tickets_list_keyboard
from max_bot.schemas.events import BotEvent

logger = logging.getLogger(__name__)


async def _ensure_user_synced(ctx: AppContext, event: BotEvent) -> dict | None:
    """Синхронизирует профиль MAX -> Core API. Возвращает профиль из Core API."""
    try:
        profile = await ctx.max_api.get_user_profile(event.user_id)
    except MaxApiError as e:
        logger.error("MAX profile fetch failed for %s: %s", event.user_id, e)
        # Не блокируем работу бота: используем данные из события вебхука
        sender = (event.raw.get("message") or {}).get("sender") or {}
        profile = {
            "user_id": event.user_id,
            "name": sender.get("name") or "",
            "first_name": (sender.get("name") or "").split(" ")[0],
            "last_name": "",
            "username": "",
            "phone": "",
            "raw": sender,
        }

    core_user: dict | None = None
    try:
        core_user = await ctx.api.upsert_user(
            max_user_id=profile["user_id"] or event.user_id,
            first_name=profile.get("first_name") or "",
            name=profile.get("name") or "",
            username=profile.get("username") or "",
            raw_profile=profile.get("raw") or {},
        )
    except CoreApiError as e:
        logger.error("Core API upsert_user failed for %s: %s", event.user_id, e)
        if e.status_code == 403:
            await ctx.reply(event.user_id, M.user_blocked_message())
            return None
        await ctx.reply(event.user_id, M.profile_sync_failed_message())
        return None
    return core_user or profile


# --------------------------------------------------------------------- #
# /start
# --------------------------------------------------------------------- #
async def cmd_start(ctx: AppContext, event: BotEvent) -> None:
    core_user = await _ensure_user_synced(ctx, event)
    if core_user is None:
        return
    first_name = (
        core_user.get("first_name")
        or core_user.get("name")
        or ""
    ).split(" ")[0] or "гость"
    await ctx.reply(
        event.user_id,
        M.welcome_message(first_name),
        inline_keyboard=main_menu_keyboard(),
    )


# --------------------------------------------------------------------- #
# /help
# --------------------------------------------------------------------- #
async def cmd_help(ctx: AppContext, event: BotEvent) -> None:
    await ctx.reply(
        event.user_id,
        M.help_message(),
        inline_keyboard=main_menu_keyboard(),
    )


# --------------------------------------------------------------------- #
# /my_tickets
# --------------------------------------------------------------------- #
async def cmd_my_tickets(ctx: AppContext, event: BotEvent) -> None:
    from max_bot.handlers import ticket_view  # локальный импорт против цикла

    await ticket_view.show_user_tickets(ctx, event.user_id)


# --------------------------------------------------------------------- #
# /profile и /balance
# --------------------------------------------------------------------- #
async def cmd_profile(ctx: AppContext, event: BotEvent) -> None:
    try:
        points = await ctx.api.get_user_points(event.user_id)
    except CoreApiError as e:
        if e.status_code == 403:
            await ctx.reply(event.user_id, M.user_blocked_message())
        elif e.status_code >= 500 or e.status_code == 0:
            await ctx.reply(event.user_id, M.service_unavailable_message())
        else:
            await ctx.reply(event.user_id, M.service_unavailable_message())
        return

    user = await _get_core_user_quietly(ctx, event.user_id)
    name = (user.get("name") or user.get("first_name") or "").strip()
    username = user.get("username") or ""
    await ctx.reply(
        event.user_id,
        M.profile_message(
            name=name or f"Пользователь {event.user_id}",
            username=username,
            points=points.get("points", points.get("balance", 0)),
            rating=points.get("rating"),
            tickets_total=points.get("tickets_total"),
            role=user.get("role"),
        ),
        inline_keyboard=main_menu_keyboard(),
    )


async def cmd_balance(ctx: AppContext, event: BotEvent) -> None:
    try:
        points = await ctx.api.get_user_points(event.user_id)
    except CoreApiError as e:
        if e.status_code == 403:
            await ctx.reply(event.user_id, M.user_blocked_message())
        else:
            await ctx.reply(event.user_id, M.service_unavailable_message())
        return
    await ctx.reply(
        event.user_id,
        M.balance_message(points.get("points", points.get("balance", 0))),
        inline_keyboard=main_menu_keyboard(),
    )


async def _get_core_user_quietly(ctx: AppContext, max_user_id: int) -> dict:
    try:
        return await ctx.api.get_user_by_max_id(max_user_id)
    except CoreApiError:
        return {}


# --------------------------------------------------------------------- #
# Диспетчер текстовых сообщений (вызывается из webhook/FSM-роутера)
# --------------------------------------------------------------------- #
COMMANDS = {
    "start": cmd_start,
    "help": cmd_help,
    "my_tickets": cmd_my_tickets,
    "tickets": cmd_my_tickets,
    "profile": cmd_profile,
    "balance": cmd_balance,
}


async def handle_text_message(ctx: AppContext, event: BotEvent) -> bool:
    """Обрабатывает команду. Возвращает True, если сообщение распознано."""
    cmd = event.command
    if cmd is None:
        return False  # обычный текст — решение за FSM-роутером
    if cmd == "cancel":
        from max_bot.handlers import ticket_create, ticket_message

        cancelled = await ticket_create.try_cancel(ctx, event)
        cancelled = await ticket_message.try_cancel(ctx, event) or cancelled
        await ctx.reply(
            event.user_id,
            M.cancel_message() if cancelled else M.nothing_to_cancel_message(),
            inline_keyboard=main_menu_keyboard() if not cancelled else None,
        )
        return True
    handler = COMMANDS.get(cmd)
    if handler is None:
        await ctx.reply(
            event.user_id,
            M.unknown_command_message(),
            inline_keyboard=main_menu_keyboard(),
        )
        return True
    await handler(ctx, event)
    return True
