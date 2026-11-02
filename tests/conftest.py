from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.types import User

from mint_bot.app import build_dispatcher
from mint_bot.booking import BookingService
from mint_bot.config import Salon, load_salon
from mint_bot.reminders import ReminderWorker
from mint_bot.storage import Storage

from .fakes import Conversation, FakeSession

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Moscow")
ADMIN_CHAT = -100500
MARIA = User(id=1001, is_bot=False, first_name="Мария")


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    """Время салона в ноябре 2026 года — как в видео."""
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


class FakeClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, now: datetime) -> None:
        self.now = now


@pytest.fixture
def salon() -> Salon:
    return load_salon(ROOT / "salon.toml")


@pytest.fixture
def scenario() -> dict:
    data = json.loads((Path(__file__).parent / "scenario.json").read_text("utf-8"))
    data["by_id"] = {step["id"]: step for step in data["steps"]}
    return data


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(at(9, 10, 41))  # понедельник, 9 ноября, 10:41 — начало видео


@pytest.fixture
async def storage(tmp_path, salon):
    st = await Storage.open(tmp_path / "mint.db", salon.tz)
    yield st
    await st.close()


@pytest.fixture
def service(salon, storage, clock) -> BookingService:
    return BookingService(salon, storage, clock)


@dataclass
class App:
    chat: Conversation
    worker: ReminderWorker
    session: FakeSession
    booking: BookingService

    def as_user(self, user: User) -> Conversation:
        """Второй клиент в том же боте."""
        other = Conversation(dp=self.chat.dp, bot=self.chat.bot, session=self.session, user=user)
        other._cursor = len(self.session.log)
        other._update_id = 10_000 + user.id
        return other


def make_app(salon: Salon, storage: Storage, clock: FakeClock, user: User = MARIA) -> App:
    session = FakeSession()
    bot = Bot("42:TEST", session=session)
    dp = build_dispatcher(bot, salon, storage, ADMIN_CHAT, clock)
    booking = dp["booking"]
    return App(
        chat=Conversation(dp=dp, bot=bot, session=session, user=user),
        worker=ReminderWorker(bot, salon, storage, clock),
        session=session,
        booking=booking,
    )


@pytest.fixture
def app(salon, storage, clock) -> App:
    return make_app(salon, storage, clock)
