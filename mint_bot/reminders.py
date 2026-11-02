"""Напоминания клиентам.

Напоминание — строка в таблице reminders: оно переживает перезапуск бота.
Раз в полминуты воркер забирает наступившие и отправляет их.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from . import keyboards as kb
from . import texts
from .booking import Clock
from .config import Salon
from .storage import Storage

log = logging.getLogger(__name__)


class ReminderWorker:
    def __init__(self, bot: Bot, salon: Salon, storage: Storage, clock: Clock, interval: float = 30):
        self.bot = bot
        self.salon = salon
        self.storage = storage
        self.clock = clock
        self.interval = interval

    async def tick(self) -> int:
        """Отправить наступившие напоминания. Возвращает, сколько сообщений ушло."""
        now = self.clock().astimezone(self.salon.tz)
        grouped = defaultdict(list)
        bookings = {}
        for reminder, booking in await self.storage.due_reminders(now):
            grouped[booking.id].append(reminder.id)
            bookings[booking.id] = booking

        sent = 0
        for booking_id, ids in grouped.items():
            booking = bookings[booking_id]
            if booking.starts_at <= now:
                # Бот лежал дольше, чем до визита: напоминать уже поздно.
                await self.storage.mark_reminders(ids, "skipped", now)
                continue
            try:
                # Если наступило сразу несколько напоминаний (например, после простоя), шлём одно.
                await self.bot.send_message(
                    booking.chat_id, texts.reminder(self.salon, booking, now), reply_markup=kb.reminder(booking.id)
                )
            except (TelegramForbiddenError, TelegramBadRequest):
                # Клиент заблокировал бота или чат недоступен — повторять бессмысленно.
                log.warning("Напоминание по записи %s не доставлено", booking_id, exc_info=True)
                await self.storage.mark_reminders(ids, "failed", now)
                continue
            except TelegramAPIError:
                # Сеть, лимиты, сбой Telegram: напоминание остаётся в очереди до следующего тика.
                log.warning("Напоминание по записи %s отложено", booking_id, exc_info=True)
                continue
            await self.storage.mark_reminders(ids, "sent", now)
            sent += 1
        return sent

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Ошибка при отправке напоминаний — повторю через %s с", self.interval)
            await asyncio.sleep(self.interval)
