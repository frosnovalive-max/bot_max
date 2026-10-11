"""Кастомные исключения HTTP-клиентов (ТЗ, раздел 7)."""


class MaxApiError(Exception):
    """Ошибка платформы MAX API (4xx/5xx, сетевые сбои)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"MAX API error {status_code}: {detail}")


class CoreApiError(Exception):
    """Ошибка нашего Core API.

    Особые коды, которые обрабатывают хендлеры:
      402 — недостаточно баллов
      403 — пользователь заблокирован
      429 — превышен лимит заявок
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Core API error {status_code}: {detail}")
