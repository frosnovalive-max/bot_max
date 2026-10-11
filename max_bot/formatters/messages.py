"""Шаблоны всех текстовых сообщений бота (ТЗ, раздел 11).

Все тексты в одном месте — чтобы править формулировки, не трогая логику.
"""

from __future__ import annotations

STATUS_LABELS = {
    "new": "🆕 Новая",
    "in_progress": "⚙️ В работе",
    "waiting_answer": "⏳ Ожидает ответа",
    "resolved": "✅ Решена",
    "closed": "🔒 Закрыта",
    "rejected": "↩️ Отклонена",
}


def _status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "—")


# ------------------------------ Общие ------------------------------ #
def welcome_message(first_name: str) -> str:
    return (
        f"👋 Здравствуйте, {first_name}!\n\n"
        "Я бот IT-службы колледжа. Выберите действие из меню ниже:"
    )


def help_message() -> str:
    return (
        "ℹ️ *Доступные команды:*\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/my_tickets — список активных заявок\n"
        "/profile — профиль, рейтинг и баланс баллов\n"
        "/balance — баланс баллов\n"
        "/cancel — отменить текущий диалог\n\n"
        "Также доступны кнопки меню: создание заявки, просмотр заявок,\n"
        "написание сообщения в заявку."
    )


def unknown_command_message() -> str:
    return (
        "🤔 Такая команда мне неизвестна.\n\n"
        "Введите /help, чтобы увидеть список команд, или воспользуйтесь кнопками меню."
    )


def service_unavailable_message() -> str:
    return "❌ Сервис временно недоступен. Попробуйте позже."


# ------------------------------ Профиль ---------------------------- #
def profile_message(
    name: str,
    username: str,
    points: int | float,
    rating: int | float | None = None,
    tickets_total: int | None = None,
    role: str | None = None,
) -> str:
    lines = [
        "👤 *Ваш профиль:*",
        "",
        f"Имя: {name}",
        f"Username: @{username}" if username else "Username: —",
    ]
    if role:
        lines.append(f"Роль: {role}")
    lines += [
        f"💰 Баланс баллов: {points}",
    ]
    if rating is not None:
        lines.append(f"⭐ Рейтинг: {rating}")
    if tickets_total is not None:
        lines.append(f"📋 Всего заявок: {tickets_total}")
    return "\n".join(lines)


def balance_message(points: int | float) -> str:
    return f"💰 Ваш текущий баланс баллов: *{points}*"


def profile_sync_failed_message() -> str:
    return (
        "⚠️ Не удалось синхронизировать ваш профиль с Core API.\n"
        "Попробуйте ещё раз через минуту или обратитесь к администратору."
    )


def user_blocked_message() -> str:
    return "🚫 Ваш аккаунт заблокирован. Обратитесь к администратору."


# ------------------------- Создание тикета (FSM) -------------------- #
def ask_type_message() -> str:
    return "🆕 *Создание заявки*\n\nШаг 1/6. Выберите тип обращения:"


def ask_address_message(type_name: str) -> str:
    return (
        f"Тип: 📌 {type_name}\n\n"
        "Шаг 2/6. Выберите адрес (корпус), где нужна помощь:"
    )


def ask_cabinet_message(address_name: str) -> str:
    return (
        f"Адрес: 🏢 {address_name}\n\n"
        "Шаг 3/6. Введите номер кабинета текстом\n"
        "(или нажмите «⏭ Пропустить»):"
    )


def ask_title_message() -> str:
    return "Шаг 4/6. Введите *краткую тему* обращения (одна-две строки):"


def ask_description_message() -> str:
    return (
        "Шаг 5/6. *Опишите проблему подробно:*\n"
        "что сломалось, когда произошло, что уже пробовали сделать."
    )


def ticket_summary_message(
    type_name: str,
    address_name: str,
    cabinet: str | None,
    title: str,
    description: str,
) -> str:
    desc = description if len(description) <= 500 else description[:500] + "…"
    return (
        "📝 *Проверьте вашу заявку (шаг 6/6):*\n\n"
        f"📌 Тип: {type_name}\n"
        f"🏢 Адрес: {address_name}\n"
        f"🚪 Кабинет: {cabinet or '—'}\n"
        f"💡 Тема: {title}\n"
        f"📄 Описание: {desc}\n\n"
        "Отправить эту заявку?"
    )


def ticket_created_message(ticket_number, balance=None) -> str:
    text = f"✅ Заявка №{ticket_number} успешно создана!"
    if balance is not None:
        text += f"\n💰 Ваш баланс баллов: {balance}"
    return text


def ticket_create_error_message(detail: str) -> str:
    return f"❌ Не удалось создать заявку: {detail}"


# --------------------------- Ошибки Core API ------------------------ #
def insufficient_points_message(balance) -> str:
    return (
        "❌ Недостаточно баллов для создания заявки.\n"
        f"💰 Текущий баланс: {balance}\n"
        "Баллы возвращаются при успешном закрытии заявки."
    )


def rate_limited_message() -> str:
    return "⏳ Превышен лимит заявок. Попробуйте позже."


# ----------------------------- Просмотр ----------------------------- #
def tickets_list_empty_message() -> str:
    return "📋 У вас пока нет активных заявок.\nСоздать новую — кнопка «🆕 Создать заявку»."


def tickets_list_message(count: int) ->str:
    word = "заявку" if count == 1 else ("заявки" if count < 5 else "заявок")
    return f"📋 Ваши активные заявки ({count} {word}):"


def ticket_details_message(ticket: dict) -> str:
    tid = ticket.get("id") or ticket.get("uuid") or "—"
    num = ticket.get("number") or ticket.get("ticket_number") or tid
    created = ticket.get("created_at") or ""
    if isinstance(created, str) and "T" in created:
        created = created.split("T")[0]
    return (
        f"🎫 *Заявка №{num}*\n\n"
        f"💡 Тема: {ticket.get('title', '—')}\n"
        f"📌 Тип: {(ticket.get('type') or {}).get('name') if isinstance(ticket.get('type'), dict) else ticket.get('type_name', '—')}\n"
        f"🏢 Адрес: {(ticket.get('address') or {}).get('street') if isinstance(ticket.get('address'), dict) else ticket.get('address_name', '—')}\n"
        f"🚪 Кабинет: {ticket.get('cabinet') or '—'}\n"
        f"📊 Статус: {_status_label(ticket.get('status'))}\n"
        f"📅 Создана: {created or '—'}\n\n"
        f"📄 Описание:\n{ticket.get('description', '—')}"
    )


def message_added_message(ticket_number) -> str:
    return f"💬 Сообщение добавлено в заявку №{ticket_number}."


def ask_ticket_message_text(ticket_number, ticket_id: str) -> str:
    return (
        f"💬 Введите текст сообщения для заявки *№{ticket_number}*:\n\n"
        "_Для отмены отправьте /cancel_"
    )


def cancel_message() -> str:
    return "🚫 Диалог отменён."


def nothing_to_cancel_message() -> str:
    return "Сейчас нечего отменять 🙂 Вернитесь в меню: /start"


def free_text_hint_message() -> str:
    return (
        "🤖 Я могу принять заявку или показать её статус.\n"
        "Выберите действие кнопкой или отправьте команду:"
    )
