"""Команды в рабочем чате администраторов и помощь с настройкой."""
from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from .. import texts
from ..booking import BookingService
from ..config import Salon


async def _day_list(message: Message, booking: BookingService, salon: Salon, offset: int) -> None:
    today = booking.now().date()
    day = today + timedelta(days=offset)
    await message.answer(texts.admin_day(salon, day, today, await booking.day(day)))


async def today(message: Message, booking: BookingService, salon: Salon) -> None:
    await _day_list(message, booking, salon, 0)


async def tomorrow(message: Message, booking: BookingService, salon: Salon) -> None:
    await _day_list(message, booking, salon, 1)


async def chat_id(message: Message) -> None:
    await message.answer(texts.chat_id(message.chat.id))


def router(admin_chat_id: int | None) -> Router:
    r = Router(name="admin")
    # /chatid работает в любой группе: так проще узнать ADMIN_CHAT_ID при настройке.
    r.message.register(chat_id, Command("chatid"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
    if admin_chat_id is not None:
        r.message.register(today, Command("today"), F.chat.id == admin_chat_id)
        r.message.register(tomorrow, Command("tomorrow"), F.chat.id == admin_chat_id)
    return r
