"""Диалоги в Telegram: «Мои записи», отмена, перенос, гонки и ошибки."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import User

from mint_bot import texts

from .conftest import ADMIN_CHAT, MARIA, at
from .fakes import labels, sent

ANNA = User(id=1002, is_bot=False, first_name="Анна", username="anna_k")


async def book_manicure(chat, day="Чт, 12 нояб.", time="14:00"):
    await chat.send("/start")
    await chat.tap("Маникюр · 1 800 ₽")
    await chat.tap(day)
    await chat.tap(time)
    return await chat.tap("Подтвердить")


async def test_my_bookings_empty_then_list(app):
    chat = app.chat
    await chat.send("/my")
    assert chat.last().text == texts.MY_EMPTY
    assert chat.last().keyboard == [["Записаться"]]

    await book_manicure(chat)
    out = await chat.send("/my")
    assert [m.text for m in sent(out)] == ["Ваши записи:", "Маникюр — чт, 12 ноября, 14:00\nМастер: Вера"]
    assert chat.last().keyboard == [["Перенести", "Отменить"]]


async def test_cancel_with_confirmation(app):
    chat = app.chat
    await book_manicure(chat)
    await chat.send("/my")
    await chat.tap("Отменить")
    assert chat.last().text.startswith("Отменить запись?")
    out = await chat.tap("Да, отменить")
    assert chat.last().text == texts.CANCELLED
    (admin,) = sent(out, ADMIN_CHAT)
    assert admin.text.startswith("Запись отменена\nМаникюр · 1 800 ₽\nЧт, 12 ноября, 14:00")
    assert await app.booking.upcoming(MARIA.id) == []


async def test_reschedule_from_reminder(app, clock):
    chat = app.chat
    await book_manicure(chat)
    clock.set(at(11, 18))
    await app.worker.tick()
    await chat.tap("Перенести")
    assert chat.last().text == "Маникюр · 1 800 ₽ · 1,5 часа\nНа какой день перенести запись?"
    await chat.tap("Пт, 13 нояб.")
    await chat.tap("11:30")
    assert chat.last().text == (
        "Проверьте перенос:\n\nУслуга: Маникюр · 1 800 ₽\nБыло: чт, 12 ноября, 14:00\n"
        "Станет: пт, 13 ноября, 11:30\nМастер: Вера\nАдрес: ул. Садовая, 12")
    out = await chat.tap("Подтвердить")
    assert chat.last().text == texts.moved(app.booking.salon)
    (admin,) = sent(out, ADMIN_CHAT)
    assert "Было: Чт, 12 ноября, 14:00\nСтало: Пт, 13 ноября, 11:30" in admin.text
    (b,) = await app.booking.upcoming(MARIA.id)
    assert b.starts_at == at(13, 11, 30)


async def test_time_taken_while_client_was_thinking(app):
    maria, anna = app.chat, app.as_user(ANNA)
    await maria.send("/start")
    await maria.tap("Маникюр · 1 800 ₽")
    await maria.tap("Чт, 12 нояб.")
    await maria.tap("14:00")  # Мария смотрит на сводку…

    await book_manicure(anna)  # …а Анна успевает записаться на то же время

    await maria.tap("Подтвердить")
    assert maria.last().text == texts.SLOT_TAKEN
    assert maria.last().keyboard == [["10:00", "11:30", "15:30"], ["17:00", "18:30"], ["‹ Назад"]]


async def test_double_tap_on_confirm_books_once(app):
    chat = app.chat
    await chat.send("/start")
    await chat.tap("Маникюр · 1 800 ₽")
    await chat.tap("Чт, 12 нояб.")
    await chat.tap("14:00")
    summary, data = chat.find("Подтвердить")
    await chat.press(summary, data)
    await chat.press(summary, data)  # второе нажатие до того, как кнопки исчезли
    out = chat.sync()
    assert len(sent(out, ADMIN_CHAT)) == 1
    assert [m.text for m in sent(out, MARIA.id)] == [texts.booked(app.booking.salon)]
    assert len(await app.booking.upcoming(MARIA.id)) == 1


async def test_back_buttons_edit_message_in_place(app):
    chat = app.chat
    await chat.send("/start")
    await chat.tap("Маникюр · 1 800 ₽")
    await chat.tap("Чт, 12 нояб.")
    out = await chat.tap("‹ Назад")  # к дням
    assert isinstance(out[0], EditMessageText) and not sent(out)
    assert chat.last().text == "Маникюр · 1 800 ₽ · 1,5 часа\nНа какой день записать?"
    await chat.tap("‹ Назад")  # к услугам
    assert chat.last().text == texts.CHOOSE_SERVICE
    assert labels(chat.last().markup)[-1] == ["Мои записи"]


async def test_edit_on_summary_returns_to_services(app):
    chat = app.chat
    await chat.send("/start")
    await chat.tap("Стрижка · 1 500 ₽")
    await chat.tap("Пт, 13 нояб.")
    await chat.tap("10:00")
    assert "Мастер: Ольга" in chat.last().text
    await chat.tap("Изменить")
    assert chat.last().text == texts.CHOOSE_SERVICE


async def test_limit_message_offers_my_bookings(app):
    chat = app.chat
    for time in ("10:00", "11:30", "15:30"):
        await book_manicure(chat, time=time)
    await book_manicure(chat, time="17:00")
    assert chat.last().text == texts.too_many(3)
    assert chat.last().keyboard == [["Мои записи"]]


async def test_stale_button_after_cancel(app):
    chat = app.chat
    await book_manicure(chat)
    await chat.send("/my")
    card, data = chat.find("Перенести")
    await chat.tap("Отменить")
    await chat.tap("Да, отменить")
    out = []
    await chat.press(card, data)  # старая кнопка из истории чата
    out = chat.sync()
    assert any(getattr(m, "text", None) == texts.STALE and getattr(m, "show_alert", False) for m in out)


async def test_unknown_text_and_group_chat(app):
    chat = app.chat
    await chat.send("привет")
    assert chat.last().text == texts.UNKNOWN
    out = await chat.send("/start", chat_id=ADMIN_CHAT)  # в рабочей группе клиентский сценарий не запускается
    assert sent(out) == []
    out = await chat.send("/chatid", chat_id=-100777)
    assert sent(out)[0].text == texts.chat_id(-100777)


async def test_admin_day_list(app, clock):
    await book_manicure(app.chat)
    await book_manicure(app.as_user(ANNA), time="10:00")
    clock.set(at(12, 9))
    out = await app.chat.send("/today", chat_id=ADMIN_CHAT)
    assert sent(out, ADMIN_CHAT)[0].text == (
        "Записи на сегодня, чт, 12 ноября:\n\n"
        "10:00 — Маникюр, Вера · Анна\n"
        "14:00 — Маникюр, Вера · Мария")
    out = await app.chat.send("/tomorrow", chat_id=ADMIN_CHAT)
    assert sent(out, ADMIN_CHAT)[0].text == "На завтра, пт, 13 ноября, записей нет."
    out = await app.chat.send("/today")  # в личке команда администратора не работает
    assert sent(out)[0].text == texts.UNKNOWN


async def test_admin_button_uses_username_when_present(app):
    out = await book_manicure(app.as_user(ANNA))
    (admin,) = sent(out, ADMIN_CHAT)
    assert admin.reply_markup.inline_keyboard[0][0].url == "https://t.me/anna_k"


async def test_admin_notified_without_button_if_client_profile_is_private(app):
    def privacy(method):
        if isinstance(method, SendMessage) and method.chat_id == ADMIN_CHAT and method.reply_markup:
            return TelegramBadRequest(method, "Bad Request: BUTTON_USER_PRIVACY_RESTRICTED")
        return None

    app.session.fail = privacy
    out = await book_manicure(app.chat)
    assert app.chat.last().text == texts.booked(app.booking.salon)  # клиент записан
    (admin,) = sent(out, ADMIN_CHAT)
    assert admin.reply_markup is None and admin.parse_mode == "HTML"
    assert admin.text.endswith(f'Клиент: <a href="tg://user?id={MARIA.id}">Мария</a>')
