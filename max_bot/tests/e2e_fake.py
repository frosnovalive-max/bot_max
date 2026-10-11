"""E2E-проверка бота на фейковых ASGI-серверах (запуск вручную).

Не поднимает реальные сокеты: все три приложения (бот, фейк Core API,
фейк MAX API) работают через httpx.ASGITransport в одном процессе.

Прогоняемые сценарии:
  1. /start -> приветствие + меню; профиль синхронизирован.
  2. Полный FSM создания тикета (6 шагов) -> заявка №101.
  3. Ошибки 402/429 при создании -> понятные сообщения.
  4. /my_tickets -> список; tv:<id> -> детали; tm:<id> -> текст -> сообщение.
  5. notification_worker доставляет pending-уведомление.

Запуск:  python -m max_bot.tests.e2e_fake   (из корня репозитория, рядом с max_bot/)
"""

from __future__ import annotations

import asyncio
import os
import sys

# --- окружение ДО импорта config (fail-fast!) ---
os.environ["MAX_BOT_TOKEN"] = "test_token_123"
os.environ["MAX_WEBHOOK_SECRET"] = ""
os.environ["BOT_BASE_URL"] = "https://fake.example.com"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # недоступен -> MemoryStorage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

# --------------------------- фейк Core API --------------------------- #
core = FastAPI()
TICKETS: dict[str, dict] = {}
NOTIFS: list[dict] = []
FAIL_NEXT_CREATE: dict[str, int | None] = {"code": None}


@core.post("/api/v1/users/sync")
async def sync(req: Request):
    body = await req.json()
    return {"id": "u1", **body}


@core.get("/api/v1/users/by-max/{uid}")
async def get_user(uid: int):
    return {"max_user_id": uid, "name": "Иван Петров", "username": "ivan", "role": "student"}


@core.get("/api/v1/users/by-max/{uid}/points")
async def points(uid: int):
    return {"points": 42, "rating": 5, "tickets_total": len(TICKETS)}


@core.get("/api/v1/references/ticket-types")
async def types():
    return [{"id": "t1", "name": "Не работает ПК"}, {"id": "t2", "name": "Принтер"}]


@core.get("/api/v1/references/addresses")
async def addresses():
    return [{"id": "a1", "street": "Ленина, 5"}, {"id": "a2", "street": "Мира, 12"}]


@core.post("/api/v1/tickets")
async def create_ticket(req: Request):
    if FAIL_NEXT_CREATE["code"]:
        code = FAIL_NEXT_CREATE["code"]
        FAIL_NEXT_CREATE["code"] = None
        return JSONResponse(status_code=code, content={"detail": "Insufficient points: current 5"})
    body = await req.json()
    tid = f"tk{len(TICKETS) + 1}"
    ticket = {
        "id": tid,
        "number": 100 + len(TICKETS),
        "status": "new",
        "author_max_user_id": body["author_max_user_id"],
        **body,
    }
    TICKETS[tid] = ticket
    return ticket


@core.get("/api/v1/tickets")
async def list_tickets(author_max_user_id: int, status: str | None = None):
    return [t for t in TICKETS.values() if t["author_max_user_id"] == author_max_user_id]


@core.get("/api/v1/tickets/{tid}")
async def get_ticket(tid: str):
    if tid not in TICKETS:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return TICKETS[tid]


@core.post("/api/v1/tickets/{tid}/messages")
async def add_msg(tid: str, req: Request):
    if tid not in TICKETS:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    body = await req.json()
    TICKETS[tid].setdefault("messages", []).append(body)
    return {"ok": True}


@core.get("/api/v1/notifications/pending")
async def pending_notifs():
    out, NOTIFS[:] = NOTIFS[:], []
    return out


@core.post("/api/v1/notifications/{nid}/sent")
async def notif_sent(nid: str):
    return {"ok": True, "id": nid}


@core.post("/api/v1/notifications/{nid}/failed")
async def notif_failed(nid: str, req: Request):
    return {"ok": False, "id": nid}


# --------------------------- фейк MAX API ---------------------------- #
sent_messages: list[dict] = []
webhook_registrations: list[str] = []

mx = FastAPI()


@mx.get("/v3/users/get")
async def mx_user(user_id: int):
    return {
        "user": {
            "user_id": user_id, "first_name": "Иван", "last_name": "Петров",
            "name": "Иван Петров", "username": "ivan",
        }
    }


@mx.get("/v3/chats/list")
async def mx_chats():
    return {"chats": [{"chat_id": 555, "members": [{"user_id": 42}]}]}


@mx.post("/v3/chats/send-message")
async def mx_send(chat_id: int, req: Request):
    body = await req.json()
    sent_messages.append({"chat_id": chat_id, **body})
    return {"message_id": len(sent_messages)}


@mx.post("/v3/subscriptions/set")
async def mx_sub(req: Request):
    body = await req.json()
    webhook_registrations.append(body["url"])
    return {"ok": True}


# ------------------------------ утилиты ------------------------------ #
def last_reply() -> dict:
    return sent_messages[-1]


def mk_event(text=None, callback=None, user_id=42, chat_id=555):
    ev: dict = {"update_type": "message_created", "message": {"chat_id": chat_id, "text": text or "", "sender": {"user_id": user_id, "name": "Иван Петров"}}}
    if callback is not None:
        ev["callback"] = {"code": callback, "user_id": user_id, "chat_id": chat_id}
        ev["update_type"] = "message_callback"
    return ev


async def main() -> None:
    from contextlib import asynccontextmanager

    from max_bot.core.api_client import ApiClient
    from max_bot.core.max_client import MaxClient
    from max_bot.context import AppContext
    from max_bot.fsm.storage import create_storage
    from max_bot.main import app as bot_app

    storage = await create_storage(os.environ["REDIS_URL"])
    assert type(storage).__name__ == "MemoryStorage", "fallback не сработал!"

    api = ApiClient(base_url="http://fake/api/v1", api_key="k")
    max_api = MaxClient(base_url="http://fake/v3", token="test_token_123")
    # подключаем транспорты фейков к клиентам бота
    api._client = httpx.AsyncClient(
        base_url="http://fake/api/v1", headers={"X-API-Key": "k"},
        transport=httpx.ASGITransport(app=core), timeout=10,
    )
    max_api._client = httpx.AsyncClient(
        base_url="http://fake/v3", params={"token": "test_token_123"},
        transport=httpx.ASGITransport(app=mx), timeout=10,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = AppContext(api=api, max_api=max_api, storage=storage)
        yield

    bot_app.router.lifespan_context = lifespan

    ctx_http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=bot_app), base_url="http://bot"
    )

    async with ctx_http:
        # старт lifespan вручную через first request? FastAPI TestClient делает это сам;
        # воспользуемся тем, что lifespan запускается ASGITransport'ом при запросе
        # только вместе с lifespan — ASGITransport НЕ выполняет lifespan, поэтому
        # инициализируем state явно:
        await lifespan(bot_app).__aenter__()

        async def hook(event: dict):
            r = await ctx_http.post("/webhook/max", json=event)
            assert r.status_code == 200 and r.json() == {"status": "ok"}, r.text

        checks = []

        # ---- healthz ----
        r = await ctx_http.get("/healthz")
        checks.append(("healthz", r.json() == {"status": "ok"}))

        # ---- 1. /start ----
        await hook(mk_event(text="/start"))
        rep = last_reply()
        checks.append(("start greeting", "Здравствуйте, Иван" in rep["text"]))
        checks.append(("start keyboard", bool(rep.get("attachments"))))

        # ---- 2. FSM: кнопка «Создать заявку» ----
        await hook(mk_event(callback="ticket_create"))
        checks.append(("step1 types", "Шаг 1/6" in last_reply()["text"]))

        await hook(mk_event(callback="tt:t1|Не работает ПК"))
        checks.append(("step2 address", "Шаг 2/6" in last_reply()["text"]))

        await hook(mk_event(callback="ad:a1|Ленина, 5"))
        checks.append(("step3 cabinet", "Шаг 3/6" in last_reply()["text"]))

        await hook(mk_event(text="каб 305"))
        checks.append(("step4 title", "Шаг 4/6" in last_reply()["text"]))

        await hook(mk_event(text="Не включается компьютер в классе 305"))
        checks.append(("step5 description", "Шаг 5/6" in last_reply()["text"]))

        await hook(mk_event(text="Компьютер не включается, индикаторы не горят, вчера работал"))
        rep = last_reply()
        checks.append(("step6 summary", "Проверьте вашу заявку" in rep["text"] and "каб 305" in rep["text"]))

        await hook(mk_event(callback="confirm_yes"))
        rep = last_reply()
        checks.append(("ticket created", "Успешно создана" in rep["text"] and "№100" in rep["text"]))
        checks.append(("balance shown", "баланс баллов: 42" in rep["text"]))
        checks.append(("ticket stored", len(TICKETS) == 1))

        # ---- 3. Ошибка 402 ----
        await hook(mk_event(callback="ticket_create"))
        await hook(mk_event(callback="tt:t2|Принтер"))
        await hook(mk_event(callback="ad:a2|Мира, 12"))
        await hook(mk_event(callback="cab_skip"))
        await hook(mk_event(text="Принтер молчит"))
        await hook(mk_event(text="Отправляю документ, принтер не печатает вовсе"))
        FAIL_NEXT_CREATE["code"] = 402
        await hook(mk_event(callback="confirm_yes"))
        rep = last_reply()
        checks.append(("402 message", "Недостаточно баллов" in rep["text"]))

        # отмена диалога
        await hook(mk_event(callback="cancel"))
        checks.append(("cancel message", "отменён" in last_reply()["text"].lower()))

        # ---- 4. Просмотр и сообщение ----
        await hook(mk_event(text="/my_tickets"))
        rep = last_reply()
        checks.append(("tickets list", "активные заявки" in rep["text"]))

        await hook(mk_event(callback="tv:tk1"))
        rep = last_reply()
        checks.append(("ticket details", "Заявка №100" in rep["text"] and "Не включается" in rep["text"]))

        await hook(mk_event(callback="tm:tk1"))
        checks.append(("ask message text", "Введите текст сообщения" in last_reply()["text"]))

        await hook(mk_event(text="Добавьте, пожалуйста, уточнение"))
        rep = last_reply()
        checks.append(("message added", "Сообщение добавлено" in rep["text"]))
        checks.append(("message stored", TICKETS["tk1"]["messages"][-1]["text"] == "Добавьте, пожалуйста, уточнение"))

        # ---- 5. profile/balance/help ----
        await hook(mk_event(text="/profile"))
        checks.append(("profile", "Баланс баллов: 42" in last_reply()["text"]))
        await hook(mk_event(text="/balance"))
        checks.append(("balance", "42" in last_reply()["text"]))
        await hook(mk_event(text="/help"))
        checks.append(("help", "/my_tickets" in last_reply()["text"]))
        await hook(mk_event(text="/bogus"))
        checks.append(("unknown cmd", "неизвестна" in last_reply()["text"]))

        # ---- 6. notification worker ----
        NOTIFS.append({"id": "n1", "user_max_id": 42, "message": "Ваша заявка №100 взята в работу"})
        from max_bot.notification_worker import _process_one

        before = len(sent_messages)
        await _process_one(api, max_api, NOTIFS[0])
        checks.append(
            ("worker delivered",
             len(sent_messages) == before + 1 and "взята в работу" in sent_messages[-1]["text"])
        )

    ok = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        ok = ok and passed
    print("\nWEBHOOK REGISTRATIONS:", webhook_registrations)
    if not ok:
        sys.exit(1)
    print("E2E: ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
