"""HTTP-клиент для MAX API (dev.max.ru/docs).

MAX Bot API (documented at https://max.im/en/bots/api — «MAX for Bots»):
  * Base URL:            https://botapi.max.ru/1.0
  * Авторизация:         query-параметр ``?token=<MAX_BOT_TOKEN>``
                         (не Bearer! — проверено по официальной документации)
  * Профиль пользователя: GET  /1.0/users/get?user_id=<id>&with_bot_user=true
  * Отправка сообщения:   POST /1.0/chats/send-message?chat_id=<chat_id>
        тело: {"text": str, "attachments": [...]}   (markdown включён по умолчанию)
  * Регистрация вебхука:  POST /1.0/subscriptions/set
        тело: {"url": "<full_webhook_url>", "is_enabled": true}

Клавиатуры (inline_keyboard) передаются как ``attachments`` с типом
``"callback_button"`` — это нативный формат MAX, а не Telegram.

⚠️ Если в config.py указан другой префикс версии (например, api.max.ru/v3),
клиент подстраивает пути под него, но порядок вызовов остаётся тем же.
Актуальные схемы всегда сверяйте с https://dev.max.ru/docs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from max_bot.core.config import settings
from max_bot.core.exceptions import MaxApiError

logger = logging.getLogger(__name__)


class MaxClient:
    """Тонкий асинхронный клиент к MAX API на httpx."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or settings.max_api_url).rstrip("/")
        self.token = token or settings.max_bot_token
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            params={"token": self.token},
            timeout=httpx.Timeout(15.0),
        )

    # ------------------------------------------------------------------ #
    # Низкоуровневый запрос с единой обработкой ошибок
    # ------------------------------------------------------------------ #
    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:  # сеть/таймаут
            logger.error("MAX API network error %s %s: %s", method, path, e)
            raise MaxApiError(status_code=0, detail=f"network error: {e}") from e

        if resp.status_code >= 400:
            detail = self._extract_error(resp)
            logger.error(
                "MAX API HTTP %s on %s %s: %s", resp.status_code, method, path, detail
            )
            raise MaxApiError(status_code=resp.status_code, detail=detail)

        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError:
            return {"raw": resp.text}
        # Платформенный обёрнутый ответ: {"success": false, "error_message": ...}
        if isinstance(data, dict) and data.get("success") is False:
            raise MaxApiError(
                status_code=resp.status_code,
                detail=data.get("error_message") or data.get("error_code") or "unknown",
            )
        return data

    @staticmethod
    def _extract_error(resp: httpx.Response) -> str:
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                return str(
                    payload.get("error_message")
                    or payload.get("detail")
                    or payload
                )
        except ValueError:
            pass
        return resp.text[:500]

    # ------------------------------------------------------------------ #
    # Публичные методы (ТЗ, п.7.1)
    # ------------------------------------------------------------------ #
    async def get_user_profile(self, user_id: int) -> dict:
        """GET /users/{user_id} — профиль пользователя MAX.

        Возвращает нормализованный словарь:
        {user_id, name, first_name, last_name, username, phone, raw}
        """
        data = await self._request(
            "GET", "/users/get", params={"user_id": user_id, "with_bot_user": "true"}
        )
        user = data.get("user", data) if isinstance(data, dict) else {}
        return self._normalize_user(user_id, user)

    @staticmethod
    def _normalize_user(fallback_id: int, user: dict) -> dict:
        """Приводит профиль MAX к единому виду (похоже на Telegram-подобную схему)."""
        first = user.get("first_name") or ""
        last = user.get("last_name") or ""
        full = user.get("name") or " ".join(filter(None, [first, last])) or first
        return {
            "user_id": user.get("user_id") or fallback_id,
            "name": full,
            "first_name": first or full.split(" ")[0],
            "last_name": last,
            "username": user.get("username") or "",
            "phone": user.get("phone") or "",
            "raw": user,
        }

    async def send_message(
        self,
        user_id: int,
        text: str,
        inline_keyboard: list[list[dict]] | None = None,
    ) -> dict:
        """Отправляет пользователю личное сообщение с опциональной клавиатурой.

        MAX требует chat_id для отправки; для личных чатов с ботом он
        получается из события message_created (см. handlers/webhook.py),
        но может быть и найден через GET /chats?chat_id=... .
        Здесь мы используем контракт: chat_id == special direct chat of user.
        Для простоты ядро бота передаёт chat_id явно через send_message_to_chat;
        этот метод резолвит chat_id по user_id автоматически.
        """
        chat_id = await self._resolve_direct_chat_id(user_id)
        return await self.send_message_to_chat(chat_id, text, inline_keyboard)

    async def _resolve_direct_chat_id(self, user_id: int) -> int:
        """Находит chat_id личного диалога пользователя с ботом."""
        data = await self._request(
            "GET", "/chats/list", params={"limit": 100, "exclude_archived": "false"}
        )
        chats = data.get("chats", []) if isinstance(data, dict) else []
        for chat in chats:
            members = chat.get("members") or []
            if any(int(m.get("user_id", -1)) == int(user_id) for m in members):
                return int(chat["chat_id"])
        # Личный чат с ботом в MAX имеет chat_id == user_id
        # (см. dev.max.ru/docs: direct chat создается автоматически).
        # Если резолв по списку чатов не удался — используем это как fallback.
        logger.info(
            "Direct chat not found in chats list for user %s; "
            "falling back to chat_id == user_id",
            user_id,
        )
        return int(user_id)

    async def send_message_to_chat(
        self,
        chat_id: int,
        text: str,
        inline_keyboard: list[list[dict]] | None = None,
    ) -> dict:
        """POST /chats/send-message?chat_id=... — текст + attachments-кнопки."""
        payload: dict[str, Any] = {"text": text}
        if inline_keyboard:
            payload["attachments"] = self.build_keyboard_attachment(inline_keyboard)
        return await self._request(
            "POST", "/chats/send-message", params={"chat_id": chat_id}, json=payload
        )

    @staticmethod
    def build_keyboard_attachment(
        inline_keyboard: list[list[dict]],
    ) -> list[dict]:
        """Конвертирует abstract-клавиатуру [[{text, callback_data}]] в MAX attachments.

        Формат кнопки MAX (dev.max.ru/docs, «Buttons»): один attachment типа
        ``button`` содержит ``payload.buttons`` — список кнопок строки:
            {"type": "button",
             "payload": {"buttons": [
                 {"action": {"type": "callback", "data": "<callback_data>"},
                  "label": "<текст>", "state": "default"}, ...
             ]}}
        Каждая строка нашей клавиатуры = отдельный attachment (ряд кнопок).
        Для URL-кнопок action.type = "open_url" с полем "url".
        """
        attachments: list[dict] = []
        for row in inline_keyboard:
            buttons: list[dict] = []
            for btn in row:
                if btn.get("url"):
                    action = {"type": "open_url", "url": btn["url"]}
                else:
                    action = {"type": "callback", "data": btn.get("callback_data", "")}
                buttons.append(
                    {
                        "action": action,
                        "label": btn["text"],
                        "state": btn.get("state", "default"),
                    }
                )
            if buttons:
                attachments.append({"type": "button", "payload": {"buttons": buttons}})
        return attachments

    async def set_webhook(self, url: str | None = None) -> dict:
        """Регистрирует вебхук (POST /subscriptions/set)."""
        webhook_url = url or settings.full_webhook_url
        logger.info("Registering MAX webhook: %s", webhook_url)
        return await self._request(
            "POST",
            "/subscriptions/set",
            json={"url": webhook_url, "is_enabled": True},
        )

    async def close(self) -> None:
        await self._client.aclose()
