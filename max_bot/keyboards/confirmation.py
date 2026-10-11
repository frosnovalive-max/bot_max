"""Клавиатура подтверждения (Да/Нет) — финальный шаг FSM создания тикета."""

from __future__ import annotations


def confirm_keyboard() -> list[list[dict]]:
    return [
        [
            {"text": "✅ Подтвердить", "callback_data": "confirm_yes"},
            {"text": "❌ Отменить", "callback_data": "confirm_no"},
        ],
    ]
