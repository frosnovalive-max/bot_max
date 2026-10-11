"""Состояния FSM многошагового диалога создания тикета (ТЗ, п.8.1)."""

from __future__ import annotations

from enum import Enum


class TicketCreateState(str, Enum):
    WAITING_FOR_TYPE = "waiting_for_type"
    WAITING_FOR_ADDRESS = "waiting_for_address"
    WAITING_FOR_CABINET = "waiting_for_cabinet"
    WAITING_FOR_TITLE = "waiting_for_title"
    WAITING_FOR_DESCRIPTION = "waiting_for_description"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"


class TicketMessageState(str, Enum):
    """Диалог «написать сообщение в тикет»: ждём текст сообщения."""

    WAITING_FOR_TICKET = "waiting_for_ticket"      # выбор тикета кнопкой/номером
    WAITING_FOR_MESSAGE = "waiting_for_message"    # ввод текста сообщения
