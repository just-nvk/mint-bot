"""Диалог с клиентом: запись, «Мои записи», перенос, отмена и ответ на напоминание.

Хендлеры тонкие: разбирают кнопку, зовут BookingService и показывают результат.
"""
from __future__ import annotations

from contextlib import suppress
from datetime import date, datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .. import keyboards as kb
from .. import texts
from ..booking import BookingService, Client
from ..config import Salon
from ..domain import BookingNotFound, SlotTaken, TooManyBookings
from ..notify import AdminNotifier

# ---------- как показываем шаги ----------

async def _ack(cb: CallbackQuery, text: str | None = None) -> None:
    with suppress(TelegramBadRequest):  # запрос мог устареть — это не ошибка
        await cb.answer(text, show_alert=bool(text))


async def _drop_keyboard(cb: CallbackQuery) -> None:
    if isinstance(cb.message, Message) and cb.message.reply_markup:
        with suppress(TelegramBadRequest):
            await cb.message.edit_reply_markup(reply_markup=None)


async def _next(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Шаг вперёд: у прошлого сообщения убираем кнопки и присылаем новое — выбор остаётся в истории чата."""
    await _drop_keyboard(cb)
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=markup)
    await _ack(cb)


async def _replace(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Шаг назад или уточнение: меняем текущее сообщение, чтобы не засорять чат."""
    if isinstance(cb.message, Message):
        try:
            await cb.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return await _ack(cb)
        else:
            return await _ack(cb)
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=markup)
    await _ack(cb)


async def _stale(cb: CallbackQuery) -> None:
    await _drop_keyboard(cb)
    await _ack(cb, texts.STALE)


def _client(cb: CallbackQuery) -> Client:
    u = cb.from_user
    return Client(user_id=u.id, chat_id=u.id, name=u.full_name, username=u.username)


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


async def _days_or_empty(cb: CallbackQuery, booking: BookingService, salon: Salon, service_id: str,
                         booking_id: int, text: str, step) -> None:
    service = salon.services[service_id]
    days = await booking.days(service)
    if not days:
        return await step(cb, texts.NO_DAYS, kb.services(salon) if not booking_id else None)
    await step(cb, text, kb.days(service.id, days, booking_id))


# ---------- команды ----------

async def start(message: Message, salon: Salon) -> None:
    await message.answer(texts.greeting(salon), reply_markup=kb.services(salon))


async def _send_my(cb_or_msg: Message | CallbackQuery, booking: BookingService, salon: Salon) -> None:
    user_id = cb_or_msg.from_user.id
    bot = cb_or_msg.bot
    items = await booking.upcoming(user_id)
    if not items:
        await bot.send_message(user_id, texts.MY_EMPTY, reply_markup=kb.new_booking())
        return
    await bot.send_message(user_id, texts.MY_HEADER)
    for b in items:
        await bot.send_message(user_id, texts.booking_card(salon, b), reply_markup=kb.manage(b.id))


async def my_command(message: Message, booking: BookingService, salon: Salon) -> None:
    await _send_my(message, booking, salon)


async def unknown(message: Message) -> None:
    await message.answer(texts.UNKNOWN)


# ---------- запись ----------

async def on_menu(cb: CallbackQuery, callback_data: kb.Menu, booking: BookingService, salon: Salon) -> None:
    if callback_data.a == "my":
        await _drop_keyboard(cb)
        await _send_my(cb, booking, salon)
        return await _ack(cb)
    await _next(cb, texts.CHOOSE_SERVICE, kb.services(salon))


async def on_service(cb: CallbackQuery, callback_data: kb.Svc, booking: BookingService, salon: Salon) -> None:
    service = salon.services.get(callback_data.s)
    if service is None:
        return await _stale(cb)
    await _days_or_empty(cb, booking, salon, service.id, 0, texts.choose_day(service), _next)


async def on_day(cb: CallbackQuery, callback_data: kb.Day, booking: BookingService, salon: Salon) -> None:
    service = salon.services.get(callback_data.s)
    if service is None:
        return await _stale(cb)
    day = _day(callback_data.d)
    slots = await booking.slots(service, day)
    if not slots:
        return await _days_or_empty(cb, booking, salon, service.id, callback_data.b, texts.DAY_FULL, _replace)
    await _next(cb, texts.free_time(day), kb.times(service.id, slots, callback_data.b))


async def _show_free_time_again(cb: CallbackQuery, booking: BookingService, salon: Salon,
                                service_id: str, day: date, booking_id: int) -> None:
    """Время заняли, пока клиент думал: показываем, что осталось."""
    service = salon.services[service_id]
    slots = await booking.slots(service, day)
    if slots:
        return await _replace(cb, texts.SLOT_TAKEN, kb.times(service.id, slots, booking_id))
    await _days_or_empty(cb, booking, salon, service.id, booking_id, texts.DAY_FULL, _replace)


async def on_time(cb: CallbackQuery, callback_data: kb.Time, booking: BookingService, salon: Salon) -> None:
    service = salon.services.get(callback_data.s)
    if service is None:
        return await _stale(cb)
    start = kb.unpack_start(salon, callback_data.d, callback_data.t)
    slot = await booking.slot(service, start)
    if slot is None:
        return await _show_free_time_again(cb, booking, salon, service.id, start.date(), callback_data.b)
    data = kb.Time(s=service.id, d=callback_data.d, t=callback_data.t, m=slot.master_id, b=callback_data.b)
    if callback_data.b:
        try:
            old = await booking.own(callback_data.b, cb.from_user.id)
        except BookingNotFound:
            return await _stale(cb)
        text = texts.summary_move(salon, service, old.starts_at, start, slot.master_id)
    else:
        text = texts.summary(salon, service, start, slot.master_id)
    await _next(cb, text, kb.confirm(data))


async def on_confirm(cb: CallbackQuery, callback_data: kb.Confirm, booking: BookingService, salon: Salon,
                     notifier: AdminNotifier) -> None:
    service = salon.services.get(callback_data.s)
    if service is None:
        return await _stale(cb)
    start = kb.unpack_start(salon, callback_data.d, callback_data.t)
    try:
        if callback_data.b:
            old, new = await booking.reschedule(callback_data.b, cb.from_user.id, start, callback_data.m)
        else:
            new = await booking.book(_client(cb), service, start, callback_data.m)
    except SlotTaken:
        mine = [b for b in await booking.upcoming(cb.from_user.id)
                if b.starts_at == start and b.service_id == service.id]
        if mine:  # двойное нажатие «Подтвердить»: запись уже создана первым нажатием
            return await _ack(cb)
        return await _show_free_time_again(cb, booking, salon, service.id, start.date(), callback_data.b)
    except TooManyBookings as e:
        return await _replace(cb, texts.too_many(e.limit), kb.my_bookings())
    except BookingNotFound:
        return await _stale(cb)

    if callback_data.b:
        await _next(cb, texts.moved(salon))
        await notifier.moved(new, old.starts_at)
    else:
        await _next(cb, texts.booked(salon))
        await notifier.new_booking(new)


async def on_edit(cb: CallbackQuery, callback_data: kb.Edit, booking: BookingService, salon: Salon) -> None:
    if callback_data.b and callback_data.s in salon.services:
        service = salon.services[callback_data.s]
        return await _days_or_empty(cb, booking, salon, service.id, callback_data.b,
                                    texts.choose_day(service, moving=True), _replace)
    await _replace(cb, texts.CHOOSE_SERVICE, kb.services(salon))


async def on_back(cb: CallbackQuery, callback_data: kb.Back, booking: BookingService, salon: Salon) -> None:
    if callback_data.to == "days" and callback_data.s in salon.services:
        service = salon.services[callback_data.s]
        return await _days_or_empty(cb, booking, salon, service.id, callback_data.b,
                                    texts.choose_day(service, moving=bool(callback_data.b)), _replace)
    await _replace(cb, texts.CHOOSE_SERVICE, kb.services(salon))


# ---------- действия с записью ----------

async def on_act(cb: CallbackQuery, callback_data: kb.Act, booking: BookingService, salon: Salon,
                 notifier: AdminNotifier) -> None:
    user_id = cb.from_user.id
    try:
        if callback_data.a == "come":
            await booking.confirm_visit(callback_data.b, user_id)
            return await _next(cb, texts.SEE_YOU)
        if callback_data.a == "cancel_yes":
            cancelled = await booking.cancel(callback_data.b, user_id)
            await _replace(cb, texts.CANCELLED, kb.new_booking())
            return await notifier.cancelled(cancelled)
        b = await booking.own(callback_data.b, user_id)
    except BookingNotFound:
        return await _stale(cb)

    if callback_data.a == "move":
        service = salon.services[b.service_id]
        return await _days_or_empty(cb, booking, salon, service.id, b.id,
                                    texts.choose_day(service, moving=True), _next)
    if callback_data.a == "cancel":
        return await _replace(cb, texts.cancel_question(salon, b), kb.cancel_question(b.id))
    # cancel_no и «‹ Назад» при переносе — вернуть карточку записи
    await _replace(cb, texts.booking_card(salon, b), kb.manage(b.id))


def router() -> Router:
    r = Router(name="client")
    r.message.filter(F.chat.type == ChatType.PRIVATE)
    r.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    r.message.register(start, CommandStart())
    r.message.register(my_command, Command("my"))
    r.callback_query.register(on_menu, kb.Menu.filter())
    r.callback_query.register(on_service, kb.Svc.filter())
    r.callback_query.register(on_day, kb.Day.filter())
    r.callback_query.register(on_time, kb.Time.filter())
    r.callback_query.register(on_confirm, kb.Confirm.filter())
    r.callback_query.register(on_edit, kb.Edit.filter())
    r.callback_query.register(on_back, kb.Back.filter())
    r.callback_query.register(on_act, kb.Act.filter())
    r.message.register(unknown)
    return r
