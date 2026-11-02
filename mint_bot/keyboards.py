"""Кнопки и данные, которые в них зашиты.

Весь выбор клиента (услуга, день, время, мастер) едет в callback_data, а не в памяти бота:
после перезапуска любая кнопка в чате продолжает работать.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import texts
from .config import Salon
from .domain import Booking, Slot


class Svc(CallbackData, prefix="svc"):
    s: str  # услуга


class Day(CallbackData, prefix="day"):
    s: str
    d: str  # ГГГГММДД
    b: int = 0  # запись, которую переносим (0 — новая)


class Time(CallbackData, prefix="time"):
    s: str
    d: str
    t: str  # ЧЧММ
    m: str  # мастер
    b: int = 0


class Confirm(CallbackData, prefix="ok"):
    s: str
    d: str
    t: str
    m: str
    b: int = 0


class Edit(CallbackData, prefix="edit"):
    s: str
    b: int = 0


class Back(CallbackData, prefix="back"):
    to: str  # services | days
    s: str = ""
    b: int = 0


class Menu(CallbackData, prefix="menu"):
    a: str  # my | new


class Act(CallbackData, prefix="bk"):
    a: str  # come | move | cancel | cancel_yes | cancel_no
    b: int


def pack_day(d: date) -> str:
    return d.strftime("%Y%m%d")


def unpack_start(salon: Salon, d: str, t: str) -> datetime:
    return datetime.strptime(d + t, "%Y%m%d%H%M").replace(tzinfo=salon.tz)


def _btn(text: str, data: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def _rows(buttons: Sequence[InlineKeyboardButton], width: int) -> list[list[InlineKeyboardButton]]:
    return [list(buttons[i:i + width]) for i in range(0, len(buttons), width)]


def services(salon: Salon) -> InlineKeyboardMarkup:
    rows = [[_btn(texts.service_button(s), Svc(s=s.id))] for s in salon.services.values()]
    rows.append([_btn(texts.BTN_MY, Menu(a="my"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def days(service_id: str, items: Iterable[date], booking_id: int = 0) -> InlineKeyboardMarkup:
    buttons = [_btn(texts.day_button(d), Day(s=service_id, d=pack_day(d), b=booking_id)) for d in items]
    back = Back(to="services") if not booking_id else Act(a="cancel_no", b=booking_id)
    return InlineKeyboardMarkup(inline_keyboard=[*_rows(buttons, 3), [_btn(texts.BTN_BACK, back)]])


def times(service_id: str, slots: Iterable[Slot], booking_id: int = 0) -> InlineKeyboardMarkup:
    buttons = [
        _btn(f"{s.start:%H:%M}", Time(s=service_id, d=pack_day(s.start.date()), t=f"{s.start:%H%M}",
                                    m=s.master_id, b=booking_id))
        for s in slots
    ]
    back = Back(to="days", s=service_id, b=booking_id)
    return InlineKeyboardMarkup(inline_keyboard=[*_rows(buttons, 3), [_btn(texts.BTN_BACK, back)]])


def confirm(data: Time) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn(texts.BTN_CONFIRM, Confirm(s=data.s, d=data.d, t=data.t, m=data.m, b=data.b)),
        _btn(texts.BTN_EDIT, Edit(s=data.s, b=data.b)),
    ]])


def reminder(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn(texts.BTN_COME, Act(a="come", b=booking_id)),
        _btn(texts.BTN_MOVE, Act(a="move", b=booking_id)),
    ]])


def manage(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn(texts.BTN_MOVE, Act(a="move", b=booking_id)),
        _btn(texts.BTN_CANCEL, Act(a="cancel", b=booking_id)),
    ]])


def cancel_question(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn(texts.BTN_CANCEL_YES, Act(a="cancel_yes", b=booking_id)),
        _btn(texts.BTN_CANCEL_NO, Act(a="cancel_no", b=booking_id)),
    ]])


def my_bookings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(texts.BTN_MY, Menu(a="my"))]])


def new_booking() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(texts.BTN_NEW, Menu(a="new"))]])


def contact(b: Booking) -> InlineKeyboardMarkup:
    url = f"https://t.me/{b.username}" if b.username else f"tg://user?id={b.user_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=texts.BTN_CONTACT, url=url)]])
