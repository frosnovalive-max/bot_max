"""HTTP-клиент для Core API (наш бэкенд IT-службы колледжа).

Бот — тонкий клиент: ВСЯ бизнес-логика (лимиты, баллы, статусы) живёт
в Core API. Здесь только HTTP-методы + единая обработка ошибок.

Авторизация: заголовок ``X-API-Key: {API_KEY}``.
Адрес: ``settings.api_url`` (внутри Docker — имя сервиса it_support_api,
НЕ localhost! — урок №3 из ТЗ).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from max_bot.core.config import settings
from max_bot.core.exceptions import CoreApiError

logger = logging.getLogger(__name__)


class ApiClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or settings.api_url).rstrip("/")
        self.api_key = api_key or settings.api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=httpx.Timeout(20.0),
        )

    # ------------------------------------------------------------------ #
    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            logger.error("Core API network error %s %s: %s", method, path, e)
            raise CoreApiError(status_code=0, detail=f"network error: {e}") from e

        if resp.status_code >= 400:
            detail = self._extract_detail(resp)
            logger.warning(
                "Core API HTTP %s on %s %s: %s", resp.status_code, method, path, detail
            )
            raise CoreApiError(status_code=resp.status_code, detail=detail)

        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _extract_detail(resp: httpx.Response) -> str:
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                d = payload.get("detail") or payload.get("message") or payload
                # FastAPI может вернуть detail как список ошибок валидации
                return str(d)[:500]
        except ValueError:
            pass
        return resp.text[:500]

    # ------------------------------------------------------------------ #
    # Пользователи
    # ------------------------------------------------------------------ #
    async def upsert_user(
        self,
        max_user_id: int,
        first_name: str,
        name: str,
        username: str,
        raw_profile: dict,
    ) -> dict:
        """Синхронизация профиля MAX -> Core API (POST /users/sync)."""
        return await self._request(
            "POST",
            "/users/sync",
            json={
                "max_user_id": max_user_id,
                "first_name": first_name,
                "name": name,
                "username": username,
                "raw_profile": raw_profile,
            },
        )

    async def get_user_by_max_id(self, max_user_id: int) -> dict:
        """GET /users/by-max/{max_user_id} — профиль из Core API."""
        return await self._request("GET", f"/users/by-max/{max_user_id}")

    async def get_user_points(self, max_user_id: int) -> dict:
        """GET /users/by-max/{max_user_id}/points — баланс/рейтинг."""
        return await self._request("GET", f"/users/by-max/{max_user_id}/points")

    # ------------------------------------------------------------------ #
    # Справочники
    # ------------------------------------------------------------------ #
    async def get_ticket_types(self) -> list[dict]:
        """GET /references/ticket-types — типы заявок."""
        data = await self._request("GET", "/references/ticket-types")
        return self._as_list(data)

    async def get_addresses(self) -> list[dict]:
        """GET /references/addresses — адреса корпусов."""
        data = await self._request("GET", "/references/addresses")
        return self._as_list(data)

    @staticmethod
    def _as_list(data: Any) -> list[dict]:
        """Core API может вернуть список или {"items": [...]} — нормализуем."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "results"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    # ------------------------------------------------------------------ #
    # Тикеты
    # ------------------------------------------------------------------ #
    async def create_ticket(
        self,
        author_max_user_id: int,
        type_id: str,
        address_id: str,
        cabinet: str | None,
        title: str,
        description: str,
    ) -> dict:
        """POST /tickets — создание заявки.

        Возможные ошибки: 402 (мало баллов), 403 (заблокирован),
        429 (лимит заявок) — обрабатываются в handlers/ticket_create.py.
        """
        return await self._request(
            "POST",
            "/tickets",
            json={
                "author_max_user_id": author_max_user_id,
                "type_id": type_id,
                "address_id": address_id,
                "cabinet": cabinet,
                "title": title,
                "description": description,
            },
        )

    async def get_user_tickets(
        self, max_user_id: int, status_filter: str | None = None
    ) -> list[dict]:
        """GET /tickets?author_max_user_id=...&status=... — список заявок."""
        params: dict[str, Any] = {"author_max_user_id": max_user_id}
        if status_filter:
            params["status"] = status_filter
        data = await self._request("GET", "/tickets", params=params)
        return self._as_list(data)

    async def get_ticket(self, ticket_id: str) -> dict:
        """GET /tickets/{ticket_id} — детали заявки."""
        return await self._request("GET", f"/tickets/{ticket_id}")

    async def add_ticket_message(
        self, ticket_id: str, author_max_user_id: int, text: str
    ) -> dict:
        """POST /tickets/{ticket_id}/messages — сообщение в тикет."""
        return await self._request(
            "POST",
            f"/tickets/{ticket_id}/messages",
            json={"author_max_user_id": author_max_user_id, "text": text},
        )

    # ------------------------------------------------------------------ #
    # Уведомления (для notification_worker)
    # ------------------------------------------------------------------ #
    async def get_pending_notifications(self) -> list[dict]:
        """GET /notifications/pending — неотправленные уведомления."""
        data = await self._request("GET", "/notifications/pending")
        return self._as_list(data)

    async def mark_notification_sent(self, notification_id: str) -> dict:
        """POST /notifications/{id}/sent — отметить доставленным."""
        return await self._request("POST", f"/notifications/{notification_id}/sent")

    async def mark_notification_failed(self, notification_id: str, error: str) -> dict:
        """POST /notifications/{id}/failed — отметить ошибкой доставки."""
        return await self._request(
            "POST",
            f"/notifications/{notification_id}/failed",
            json={"error": error[:1000]},
        )

    async def close(self) -> None:
        await self._client.aclose()
