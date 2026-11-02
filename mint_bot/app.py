"""Сборка бота: настройки → база → диспетчер → напоминания → polling."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from dotenv import load_dotenv

from . import texts
from .booking import BookingService, Clock
from .config import ConfigError, Salon, load_salon, load_settings
from .handlers import admin, client
from .notify import AdminNotifier
from .reminders import ReminderWorker
from .storage import Storage

log = logging.getLogger("mint_bot")


def build_dispatcher(bot: Bot, salon: Salon, storage: Storage, admin_chat_id: int | None, clock: Clock) -> Dispatcher:
    dp = Dispatcher(
        booking=BookingService(salon, storage, clock),
        notifier=AdminNotifier(bot, admin_chat_id, salon),
        salon=salon,
    )
    dp.include_router(admin.router(admin_chat_id))
    dp.include_router(client.router())
    return dp


async def setup_profile(bot: Bot, salon: Salon, admin_chat_id: int | None) -> None:
    """Меню команд и описание «Что умеет этот бот?». Не критично: при ошибке бот всё равно работает."""
    try:
        await bot.set_my_commands(
            [BotCommand(command="start", description="Записаться"),
             BotCommand(command="my", description="Мои записи")],
            scope=BotCommandScopeAllPrivateChats(),
        )
        if admin_chat_id is not None:
            await bot.set_my_commands(
                [BotCommand(command="today", description="Записи на сегодня"),
                 BotCommand(command="tomorrow", description="Записи на завтра")],
                scope=BotCommandScopeChat(chat_id=admin_chat_id),
            )
        await bot.set_my_description(texts.description(salon))
        await bot.set_my_short_description(texts.short_description(salon))
    except TelegramAPIError:
        log.warning("Не удалось обновить команды и описание бота", exc_info=True)


async def main() -> None:
    load_dotenv()
    settings = load_settings()
    salon = load_salon(settings.salon_path)
    if settings.admin_chat_id is None:
        log.warning("ADMIN_CHAT_ID не задан: уведомлений администраторам не будет. "
                    "Добавьте бота в рабочую группу и отправьте там /chatid.")

    storage = await Storage.open(settings.db_path, salon.tz)
    bot = Bot(settings.bot_token)
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            raise ConfigError("Telegram не принял BOT_TOKEN — проверьте токен у @BotFather.") from None

        def clock() -> datetime:
            return datetime.now(salon.tz)

        dp = build_dispatcher(bot, salon, storage, settings.admin_chat_id, clock)
        worker = ReminderWorker(bot, salon, storage, clock)
        await setup_profile(bot, salon, settings.admin_chat_id)

        reminders = asyncio.create_task(worker.run())
        log.info("Бот @%s салона «%s» запущен", me.username, salon.name)
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            reminders.cancel()
            with suppress(asyncio.CancelledError):
                await reminders
    finally:
        await storage.close()
        await bot.session.close()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except ConfigError as e:
        print(f"Ошибка настройки: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        pass
