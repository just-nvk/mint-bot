"""Расписание и свободное время. Чистые функции без Telegram и базы — их легко тестировать."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .config import Salon, Schedule, Service

# Как далеко вперёд искать дни со свободным временем.
SCAN_DAYS = 30

Interval = tuple[datetime, datetime]
Busy = Mapping[str, Sequence[Interval]]  # master_id → занятые интервалы


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    master_id: str


@dataclass(frozen=True)
class Booking:
    id: int
    user_id: int
    chat_id: int
    client_name: str
    username: str | None
    service_id: str
    master_id: str
    starts_at: datetime
    ends_at: datetime
    status: str  # active | cancelled
    confirmed_at: datetime | None
    created_at: datetime


class BookingError(Exception):
    pass


class SlotTaken(BookingError):
    """Время заняли или оно уже недоступно."""


class TooManyBookings(BookingError):
    def __init__(self, limit: int):
        super().__init__(limit)
        self.limit = limit


class BookingNotFound(BookingError):
    """Записи нет, она чужая, отменена или уже прошла."""


def working_segments(schedule: Schedule, day: date) -> list[tuple[time, time]]:
    """Рабочие отрезки дня без перерывов. Выходной — пустой список."""
    if day.isoweekday() not in schedule.workdays:
        return []
    segments = [(schedule.opens, schedule.closes)]
    for b_start, b_end in sorted(schedule.breaks):
        cut: list[tuple[time, time]] = []
        for s, e in segments:
            if b_end <= s or b_start >= e:
                cut.append((s, e))
                continue
            if s < b_start:
                cut.append((s, b_start))
            if b_end < e:
                cut.append((b_end, e))
        segments = cut
    return segments


def slot_grid(salon: Salon, service: Service, day: date) -> list[datetime]:
    """Сетка начала услуги: от начала каждого рабочего отрезка с шагом в длительность услуги."""
    step = timedelta(minutes=service.duration_minutes)
    starts: list[datetime] = []
    for seg_start, seg_end in working_segments(salon.schedule, day):
        t = datetime.combine(day, seg_start, tzinfo=salon.tz)
        end = datetime.combine(day, seg_end, tzinfo=salon.tz)
        while t + step <= end:
            starts.append(t)
            t += step
    return starts


def overlaps(start: datetime, end: datetime, intervals: Iterable[Interval]) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in intervals)


def free_slots(salon: Salon, service: Service, day: date, busy: Busy, now: datetime) -> list[Slot]:
    """Свободное время на день. Мастер — первый свободный по порядку из salon.toml."""
    earliest = now + timedelta(minutes=salon.schedule.min_lead_minutes)
    duration = timedelta(minutes=service.duration_minutes)
    slots: list[Slot] = []
    for start in slot_grid(salon, service, day):
        if start < earliest:
            continue
        end = start + duration
        for master_id in service.masters:
            if not overlaps(start, end, busy.get(master_id, ())):
                slots.append(Slot(start=start, end=end, master_id=master_id))
                break
    return slots


def bookable_days(salon: Salon, service: Service, busy: Busy, now: datetime) -> list[date]:
    """Ближайшие дни, где есть хотя бы одно свободное время."""
    today = now.astimezone(salon.tz).date()
    days: list[date] = []
    for offset in range(SCAN_DAYS):
        day = today + timedelta(days=offset)
        if free_slots(salon, service, day, busy, now):
            days.append(day)
            if len(days) == salon.schedule.days_ahead:
                break
    return days


def find_slot(salon: Salon, service: Service, start: datetime, busy: Busy, now: datetime) -> Slot | None:
    for slot in free_slots(salon, service, start.astimezone(salon.tz).date(), busy, now):
        if slot.start == start:
            return slot
    return None


def plan_reminders(salon: Salon, start: datetime, now: datetime) -> list[tuple[str, datetime]]:
    """Когда напомнить: накануне в заданное время и за N минут до начала. Прошедшие моменты пропускаем."""
    local = start.astimezone(salon.tz)
    policy = salon.reminders
    planned = [
        ("day_before", datetime.combine(local.date() - timedelta(days=1), policy.day_before_at, tzinfo=salon.tz)),
        ("before", local - timedelta(minutes=policy.before_minutes)),
    ]
    return [(kind, due) for kind, due in planned if now < due < local]
