"""Конфигурация бота: все переменные читаются из .env / окружения.

Ключевые принципы (см. ТЗ, раздел 5):
1. FAIL-FAST: при отсутствии/заглушечном MAX_BOT_TOKEN приложение
   немедленно падает с понятным сообщением (а не через 10 стеков вызовов).
2. ЧЕТКОЕ РАЗДЕЛЕНИЕ URL:
   - MAX_API_URL  — КУДА МЫ шлём запросы (API платформы MAX);
   - BOT_BASE_URL — КУДА НАМ шлют вебхуки (публичный URL нашего сервера);
   - API_URL      — адрес нашего Core API (внутри Docker — имя сервиса,
     НЕ localhost!).
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Токен MAX (fail-fast проверяется ниже) ---
    max_bot_token: str = ""

    # --- MAX API: КУДА МЫ шлём (сообщения, профили) ---
    max_api_url: str = "https://api.max.ru/v3"

    # --- Core API: наш бэкенд (в Docker — http://it_support_api:8000/api/v1) ---
    api_url: str = "http://it_support_api:8000/api/v1"
    api_key: str = ""

    # --- Вебхук: КУДА НАМ шлют (публичный URL без слэша на конце) ---
    bot_base_url: str = "http://localhost:8080"
    webhook_path: str = "/webhook/max"

    # Секретная строка проверки вебхуков MAX (заголовок X-Webhook-Secret)
    max_webhook_secret: str = ""

    # --- Redis для FSM; при недоступности — fallback на MemoryStorage ---
    redis_url: str = "redis://max_bot_redis:6379/0"

    # --- Прочее ---
    log_level: str = "INFO"
    bot_port: int = 8080

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def full_webhook_url(self) -> str:
        """Итоговый URL вебхука для регистрации в панели MAX.

        Пример: https://my-tunnel.trycloudflare.com/webhook/max
        ⚠️ Сюда НЕ входит MAX_API_URL — это разные направления (ТЗ п.15).
        """
        return f"{self.bot_base_url.rstrip('/')}{self.webhook_path}"


def _load_settings() -> Settings:
    """Загружает настройки и выполняет fail-fast проверку токена."""
    # Ищем .env рядом с пакетом / в cwd — чтобы не зависеть от WORKDIR
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ]
    env_file = next((p for p in candidates if os.path.isfile(p)), None)
    if env_file:
        settings_ = Settings(_env_file=env_file)
    else:
        settings_ = Settings()

    # ============ FAIL-FAST: Немедленный выход, если токен не указан ============
    placeholder = "your_max_bot_token_here"
    if not settings_.max_bot_token or settings_.max_bot_token == placeholder:
        raise ValueError(
            "❌ MAX_BOT_TOKEN не задан! "
            "Получите токен в панели разработчика MAX и укажите его в .env "
            "(см. max_bot/.env.example). Бот НЕ может работать без токена."
        )
    return settings_


settings = _load_settings()
