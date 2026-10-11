"""Контекст приложения (dependency container).

Содержит переиспользуемые клиенты и FSM-хранилище. Инициализируется в
lifespan-хендлере main.py, кладётся в request.app.state; хендлеры получают
его через get_ctx(request).

Ключевые свойства:
- ctx.storage ВСЕГДА существует (RedisStorage или MemoryStorage fallback);
- ctx.chat_ids — кэш chat_id по user_id из входящих событий (нужен для
  исходящих сообщений в MAX, где отправка идёт в чат, а не «пользователю»).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from max_bot.core.api_client import ApiClient
from max_bot.core.max_client import MaxClient


@dataclass
class AppContext:
    api: ApiClient
    max_api: MaxClient
    storage: object  # RedisStorage | MemoryStorage (duck typing, см. fsm/storage.py)
    chat_ids: dict[int, int] = field(default_factory=dict)  # user_id -> chat_id

    def remember_chat(self, user_id: int, chat_id: int) -> None:
        self.chat_ids[int(user_id)] = int(chat_id)

    def chat_for(self, user_id: int) -> int:
        """Возвращает chat_id для пользователя (fallback: chat_id == user_id)."""
        return self.chat_ids.get(int(user_id), int(user_id))

    async def reply(
        self,
        user_id: int,
        text: str,
        inline_keyboard: list[list[dict]] | None = None,
    ) -> dict:
        """Единая точка исходящих сообщений бота."""
        return await self.max_api.send_message_to_chat(
            chat_id=self.chat_for(user_id),
            text=text,
            inline_keyboard=inline_keyboard,
        )


def get_ctx(request) -> AppContext:
    """Достает AppContext из app.state (работает с Request и APIRouter-зависимостями)."""
    return request.app.state.ctx
