"""Уведомления в рабочий чат администраторов."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from . import keyboards as kb
from . import texts
from .config import Salon
from .domain import Booking

log = logging.getLogger(__name__)


class AdminNotifier:
    def __init__(self, bot: Bot, chat_id: int | None, salon: Salon):
        self.bot = bot
        self.chat_id = chat_id
        self.salon = salon

    async def new_booking(self, b: Booking) -> None:
        await self._send(lambda html: texts.admin_new(self.salon, b, html), b)

    async def moved(self, b: Booking, old_start: datetime) -> None:
        await self._send(lambda html: texts.admin_moved(self.salon, b, old_start, html), b)

    async def cancelled(self, b: Booking) -> None:
        await self._send(lambda html: texts.admin_cancelled(self.salon, b, html), b)

    async def _send(self, render: Callable[[bool], str], b: Booking) -> None:
        """Сбой уведомления не должен ломать запись клиента: ошибки только пишем в лог."""
        if self.chat_id is None:
            log.warning("ADMIN_CHAT_ID не задан — уведомление о записи %s не отправлено", b.id)
            return
        try:
            try:
                await self.bot.send_message(self.chat_id, render(False), reply_markup=kb.contact(b))
            except TelegramBadRequest as e:
                # Если профиль клиента закрыт, Telegram не пропускает сообщение с кнопкой-ссылкой на него.
                # Тогда шлём без кнопки, а имя клиента делаем упоминанием.
                if "PRIVACY" not in str(e).upper():
                    raise
                await self.bot.send_message(self.chat_id, render(True), parse_mode="HTML")
        except TelegramAPIError:
            log.exception("Не удалось уведомить администраторов о записи %s", b.id)
