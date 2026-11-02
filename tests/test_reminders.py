"""Напоминания хранятся в базе: переживают перезапуск и не дублируются."""
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage

from mint_bot.booking import BookingService, Client
from mint_bot.storage import Storage

from .conftest import at, make_app
from .fakes import sent

MARIA = Client(user_id=1001, chat_id=1001, name="Мария")


async def test_reminder_survives_restart(tmp_path, salon, clock):
    db = tmp_path / "mint.db"
    first = await Storage.open(db, salon.tz)
    await BookingService(salon, first, clock).book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    await first.close()  # бот остановили

    second = await Storage.open(db, salon.tz)  # и запустили снова
    app = make_app(salon, second, clock)
    clock.set(at(11, 17, 59))
    assert await app.worker.tick() == 0
    clock.set(at(11, 18))
    assert await app.worker.tick() == 1
    assert await app.worker.tick() == 0  # второй раз не шлём
    (message,) = sent(app.chat.sync(), MARIA.chat_id)
    assert message.text.startswith("Напоминаю о записи: завтра, 12 ноября, в 14:00")
    await second.close()


async def test_after_downtime_one_message_with_right_day(app, salon, clock):
    await app.booking.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    clock.set(at(12, 12, 30))  # бот лежал со среды до четверга: наступили оба напоминания
    assert await app.worker.tick() == 1
    (message,) = sent(app.chat.sync(), MARIA.chat_id)
    assert message.text.startswith("Напоминаю о записи: сегодня, 12 ноября, в 14:00")
    assert await app.worker.tick() == 0


async def test_no_reminder_after_visit_started(app, salon, clock, storage):
    b = await app.booking.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    clock.set(at(12, 14, 5))
    assert await app.worker.tick() == 0
    assert {status for *_, status in await storage.reminders_of(b.id)} == {"skipped"}


async def test_blocked_bot_is_not_retried(app, salon, clock, storage):
    b = await app.booking.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    app.session.fail = lambda m: TelegramForbiddenError(m, "Forbidden: bot was blocked by the user") \
        if isinstance(m, SendMessage) else None
    clock.set(at(11, 18))
    assert await app.worker.tick() == 0
    assert [s for _, _, s in await storage.reminders_of(b.id)] == ["failed", "pending"]


async def test_network_error_keeps_reminder_in_queue(app, salon, clock):
    await app.booking.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    app.session.fail = lambda m: TelegramNetworkError(m, "timeout") if isinstance(m, SendMessage) else None
    clock.set(at(11, 18))
    assert await app.worker.tick() == 0
    app.session.fail = None
    clock.set(at(11, 18, 1))
    assert await app.worker.tick() == 1


async def test_cancelled_booking_is_not_reminded(app, salon, clock):
    b = await app.booking.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    await app.booking.cancel(b.id, MARIA.user_id)
    clock.set(at(11, 18))
    assert await app.worker.tick() == 0
