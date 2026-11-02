"""Бот проходит сценарий из видео слово в слово.

tests/scenario.json — тот же файл, по которому собрано демо-видео. Если поменять текст в боте
и забыть про видео (или наоборот), этот тест упадёт.
"""
from aiogram.methods import EditMessageReplyMarkup

from mint_bot import texts

from .conftest import ADMIN_CHAT, MARIA, at
from .fakes import labels, sent


def bot_said(methods, step, chat_id=MARIA.id):
    messages = sent(methods, chat_id)
    assert messages, f"бот промолчал на шаге {step['id']}"
    message = messages[-1]
    assert message.text == step["bot"], step["id"]
    assert labels(message.reply_markup) == step.get("keyboard"), step["id"]


async def test_description_matches_video(salon, scenario):
    assert texts.description(salon) == scenario["bot"]["description"]


async def test_video_scenario(app, clock, scenario):
    step = scenario["by_id"]
    chat = app.chat

    # 10:41 — клиент нажимает «Запустить»
    out = await chat.send(step["start"]["user"])
    bot_said(out, step["services"])
    greeting = chat.last()

    # Услуга → дни. Кнопки предыдущего шага исчезают, как в видео.
    out = await chat.tap(step["days"]["tap"])
    assert any(isinstance(m, EditMessageReplyMarkup) and m.message_id == greeting.message_id for m in out)
    bot_said(out, step["days"])

    clock.set(at(9, 10, 42))
    out = await chat.tap(step["times"]["tap"])
    bot_said(out, step["times"])

    out = await chat.tap(step["summary"]["tap"])
    bot_said(out, step["summary"])

    out = await chat.tap(step["done"]["tap"])
    bot_said(out, step["done"])

    # Администраторам — уведомление с кнопкой «Написать клиенту»
    bot_said(out, step["admin"], chat_id=ADMIN_CHAT)
    admin_message = sent(out, ADMIN_CHAT)[-1]
    assert admin_message.reply_markup.inline_keyboard[0][0].url == f"tg://user?id={MARIA.id}"

    # Среда, 11 ноября, 18:00 — напоминание накануне
    clock.set(at(11, 18, 0))
    assert await app.worker.tick() == 1
    bot_said(chat.sync(), step["reminder"])

    clock.set(at(11, 18, 1))
    out = await chat.tap(step["confirmed"]["tap"])
    bot_said(out, step["confirmed"])

    (booking,) = await app.booking.upcoming(MARIA.id)
    assert booking.confirmed_at == at(11, 18, 1)
