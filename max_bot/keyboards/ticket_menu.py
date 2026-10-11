"""Клавиатуры меню тикетов: выбор типа, адреса, списка заявок."""

from __future__ import annotations

MAX_BUTTONS_PER_ROW = 2


def _chunk(rows_source: list[dict], per_row: int = MAX_BUTTONS_PER_ROW):
    """Режет плоский список кнопок на строки по N штук."""
    for i in range(0, len(rows_source), per_row):
        yield rows_source[i : i + per_row]


def types_keyboard(types: list[dict]) -> list[list[dict]]:
    """Кнопки «тип заявки» из GET /references/ticket-types.

    Ожидаемые поля элемента: {"id": ..., "name": ...} (или "title").
    callback_data: tt:<id>
    """
    buttons = []
    for t in types:
        tid = t.get("id") or t.get("uuid") or t.get("code")
        name = t.get("name") or t.get("title") or str(tid)
        buttons.append({"text": f"📌 {name}", "callback_data": f"tt:{tid}|{name}"})
    buttons.append({"text": "❌ Отменить", "callback_data": "cancel"})
    return list(_chunk(buttons))


def addresses_keyboard(addresses: list[dict]) -> list[list[dict]]:
    """Кнопки «адрес/корпус» из GET /references/addresses.

    callback_data: ad:<id>|<название>
    """
    buttons = []
    for a in addresses:
        aid = a.get("id") or a.get("uuid")
        name = a.get("street") or a.get("name") or a.get("title") or str(aid)
        buttons.append({"text": f"🏢 {name}", "callback_data": f"ad:{aid}|{name}"})
    buttons.append({"text": "❌ Отменить", "callback_data": "cancel"})
    return list(_chunk(buttons))


def skip_cabinet_keyboard() -> list[list[dict]]:
    """Для шага «кабинет»: пропустить или назад."""
    return [
        [{"text": "⏭ Пропустить", "callback_data": "cab_skip"}],
        [{"text": "❌ Отменить", "callback_data": "cancel"}],
    ]


def tickets_list_keyboard(tickets: list[dict]) -> list[list[dict]]:
    """Кнопки для списка заявок пользователя.

    callback_data: tv:<ticket_id> — посмотреть детали;
                   tm:<ticket_id> — написать сообщение в заявку.
    """
    buttons = []
    for tk in tickets[:20]:
        tid = tk.get("id") or tk.get("uuid")
        num = tk.get("number") or tk.get("ticket_number") or tid
        title = (tk.get("title") or "")[:30]
        buttons.append(
            {"text": f"№{num} {title}", "callback_data": f"tv:{tid}"}
        )
    if buttons:
        buttons.append({"text": "🏠 Главное меню", "callback_data": "menu"})
    else:
        return [[{"text": "🏠 Главное меню", "callback_data": "menu"}]]
    return list(_chunk(buttons, per_row=1))


def ticket_actions_keyboard(ticket_id: str) -> list[list[dict]]:
    """Действия в карточке конкретной заявки."""
    return [
        [
            {
                "text": "💬 Написать сообщение",
                "callback_data": f"tm:{ticket_id}",
            },
            {"text": "🔄 Обновить", "callback_data": f"tv:{ticket_id}"},
        ],
        [{"text": "📋 Мои заявки", "callback_data": "ticket_list"}],
        [{"text": "🏠 Главное меню", "callback_data": "menu"}],
    ]


def back_to_menu_keyboard() -> list[list[dict]]:
    return [[{"text": "🏠 Главное меню", "callback_data": "menu"}]]
