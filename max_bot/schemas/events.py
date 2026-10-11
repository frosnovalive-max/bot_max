"""Слой «MAX webhook payload -> нормализованное событие».

Формат вебхуков MAX (https://dev.max.ru/docs, раздел «Bot API / Webhook»):

  {
    "update_type": "message_created",          # тип события
    "message": {
        "text": "...",
        "msg_id": ..., "chat_id": ..., "seq": ...,
        "sender": {"user_id": ..., "name": "...", "is_bot": false},
        "attachments": [ ... ]                 # файлы/кнопки
    },
    "callback": {                              # только для message_callback
        "code": "<callback_data с кнопки>",
        "message_id": ..., "user_id": ..., "chat_id": ...
    }
  }

⚠️ Исторически в разных версиях платформы поле могло называться
``type`` вместо ``update_type``, а sender — лежать в ``from.user``.
Поэтому извлечение полей ниже сделано толерантным к обоим вариантам:
если структура не изменится — менять что-либо в коде НЕ потребуется;
при смене схемы правка локализована в этом одном файле.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotEvent:
    """Нормализованное событие, пригодное для хендлеров."""

    event_type: str                      # "message_new" | "message_callback" | "other"
    user_id: int = 0
    chat_id: int = 0
    text: str = ""
    callback_data: str = ""
    is_service_message: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def command(self) -> str | None:
        """'/start' -> 'start'; '/help arg' -> 'help'; обычный текст -> None."""
        t = self.text.strip()
        if t.startswith("/"):
            head = t.split(maxsplit=1)[0]
            name = head[1:].split("@", 1)[0].lower()  # снять @botname mention
            return name or None
        return None


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def parse_event(payload: dict) -> BotEvent:
    """Разбирает сырой JSON вебхука MAX в BotEvent."""
    if not isinstance(payload, dict):
        return BotEvent(event_type="other", raw={})

    update_type = str(
        _first(payload, "update_type", "type", "event_type", default="") or ""
    )

    message: dict = payload.get("message") or {}
    callback: dict = payload.get("callback") or {}
    sender: dict = _first(message, "sender", "from", default={}) or {}
    if isinstance(sender, dict) and isinstance(sender.get("user"), dict):
        # вариант {"from": {"user": {...}}}
        sender = sender["user"]

    user_id = int(
        _first(callback, "user_id", default=None)
        or _first(sender, "user_id", "id", default=0)
        or 0
    )
    chat_id = int(
        _first(callback, "chat_id", default=None)
        or _first(message, "chat_id", default=0)
        or 0
    )
    text = str(_first(message, "text", default="") or "")
    callback_data = str(_first(callback, "code", "data", default="") or "")

    # Служебные сообщения платформы (например, «пользователь нажал старт»)
    attachments = message.get("attachments") or []
    is_service = any(
        isinstance(a, dict) and a.get("type") == "service_subscribed"
        for a in attachments
    )

    if update_type in ("message_created", "message_new"):
        if callback_data:
            event_type = "message_callback"
        else:
            event_type = "message_new"
    elif update_type in ("message_callback", "callback"):
        event_type = "message_callback"
    else:
        event_type = "other"

    return BotEvent(
        event_type=event_type,
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        callback_data=callback_data,
        is_service_message=is_service,
        raw=payload,
    )
