"""Сценарии записи: свободное время, запись, перенос, отмена. Без Telegram — только правила салона."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import domain
from .config import Salon, Service
from .domain import Booking, BookingNotFound, Slot, SlotTaken
from .storage import Storage

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Client:
    user_id: int
    chat_id: int
    name: str
    username: str | None = None


class BookingService:
    def __init__(self, salon: Salon, storage: Storage, clock: Clock):
        self.salon = salon
        self.storage = storage
        self._clock = clock

    def now(self) -> datetime:
        return self._clock().astimezone(self.salon.tz)

    def _day_start(self, day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=self.salon.tz)

    async def _busy(self, service: Service, first: date, last: date) -> domain.Busy:
        end = self._day_start(last + timedelta(days=1))
        return await self.storage.busy(service.masters, self._day_start(first), end)

    # ---------- свободное время ----------

    async def days(self, service: Service) -> list[date]:
        now = self.now()
        busy = await self._busy(service, now.date(), now.date() + timedelta(days=domain.SCAN_DAYS))
        return domain.bookable_days(self.salon, service, busy, now)

    async def slots(self, service: Service, day: date) -> list[Slot]:
        busy = await self._busy(service, day, day)
        return domain.free_slots(self.salon, service, day, busy, self.now())

    async def slot(self, service: Service, start: datetime) -> Slot | None:
        """Свободно ли это время сейчас (с учётом сетки, выходных и минимального запаса)."""
        busy = await self._busy(service, start.date(), start.date())
        return domain.find_slot(self.salon, service, start, busy, self.now())

    # ---------- изменения ----------

    async def book(self, client: Client, service: Service, start: datetime, master_id: str) -> Booking:
        now = self.now()
        if master_id not in service.masters or await self.slot(service, start) is None:
            raise SlotTaken
        return await self.storage.create(
            user_id=client.user_id, chat_id=client.chat_id, client_name=client.name, username=client.username,
            service_id=service.id, master_id=master_id, starts_at=start,
            ends_at=start + timedelta(minutes=service.duration_minutes),
            now=now, max_active=self.salon.max_active_bookings,
            reminders=domain.plan_reminders(self.salon, start, now),
        )

    async def own(self, booking_id: int, user_id: int) -> Booking:
        """Будущая активная запись этого клиента — иначе BookingNotFound."""
        b = await self.storage.get(booking_id)
        if b is None or b.user_id != user_id or b.status != "active" or b.starts_at <= self.now():
            raise BookingNotFound
        return b

    async def reschedule(
        self, booking_id: int, user_id: int, start: datetime, master_id: str
    ) -> tuple[Booking, Booking]:
        old = await self.own(booking_id, user_id)
        service = self.salon.services[old.service_id]
        if master_id not in service.masters or (start != old.starts_at and await self.slot(service, start) is None):
            raise SlotTaken
        new = await self.storage.reschedule(
            booking_id, master_id=master_id, starts_at=start,
            ends_at=start + timedelta(minutes=service.duration_minutes),
            reminders=domain.plan_reminders(self.salon, start, self.now()),
        )
        return old, new

    async def cancel(self, booking_id: int, user_id: int) -> Booking:
        await self.own(booking_id, user_id)
        return await self.storage.cancel(booking_id)

    async def confirm_visit(self, booking_id: int, user_id: int) -> Booking:
        b = await self.own(booking_id, user_id)
        await self.storage.confirm_visit(b.id, self.now())
        return b

    # ---------- списки ----------

    async def upcoming(self, user_id: int) -> list[Booking]:
        return await self.storage.upcoming_for_user(user_id, self.now())

    async def day(self, day: date) -> list[Booking]:
        return await self.storage.between(self._day_start(day), self._day_start(day + timedelta(days=1)))
