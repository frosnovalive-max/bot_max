FROM python:3.11-slim

# Non-root пользователь (безопасность)
RUN useradd --create-home --shell /usr/sbin/nologin botuser

WORKDIR /app

# Зависимости (кэширование слоев: requirements меняются реже кода)
COPY max_bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY max_bot/ ./max_bot/

USER botuser

# Порт вебхук-сервера (должен совпадать с BOT_PORT в .env и ports в compose)
EXPOSE 8080

# По умолчанию запускаем бота (вебхук-сервер).
# notification-worker переопределяет command в docker-compose.yml.
CMD ["python", "-m", "max_bot.main"]
