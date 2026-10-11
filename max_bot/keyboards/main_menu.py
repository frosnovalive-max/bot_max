"""Главное меню бота (inline_keyboard в abstract-формате).

Abstract-формат [[{"text", "callback_data"}]] конвертируется в нативные
attachments MAX в core/max_client.py::build_keyboard_attachment.
"""

from __future__ import annotations


def main_menu_keyboard() -> list[list[dict]]:
    return [
        [
            {"text": "🆕 Создать заявку", "callback_data": "ticket_create"},
            {"text": "📋 Мои заявки", "callback_data": "ticket_list"},
        ],
        [
            {"text": "👤 Профиль", "callback_data": "profile"},
            {"text": "💰 Баланс", "callback_data": "balance"},
        ],
        [
            {"text": "💬 Написать в заявку", "callback_data": "ticket_message_start"},
            {"text": "ℹ️ Помощь", "callback_data": "help"},
        ],
    ]
