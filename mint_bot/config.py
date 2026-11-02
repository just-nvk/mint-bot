"""Настройки: секреты — из переменных окружения, данные салона — из salon.toml."""
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """Ошибка в настройках: сообщение объясняет, что поправить."""


@dataclass(frozen=True)
class Master:
    id: str
    name: str


@dataclass(frozen=True)
class Service:
    id: str
    title: str
    price: int
    duration_minutes: int
    masters: tuple[str, ...]
    price_from: bool = False


@dataclass(frozen=True)
class Schedule:
    workdays: frozenset[int]  # isoweekday: 1 — понедельник … 7 — воскресенье
    opens: time
    closes: time
    breaks: tuple[tuple[time, time], ...]
    days_ahead: int
    min_lead_minutes: int


@dataclass(frozen=True)
class ReminderPolicy:
    day_before_at: time
    before_minutes: int


@dataclass(frozen=True)
class Salon:
    name: str
    address: str
    tz: ZoneInfo
    schedule: Schedule
    reminders: ReminderPolicy
    masters: Mapping[str, Master]
    services: Mapping[str, Service]  # порядок — как на кнопках
    max_active_bookings: int

    def master(self, master_id: str) -> Master:
        return self.masters[master_id]


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_chat_id: int | None
    db_path: Path
    salon_path: Path


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    token = env.get("BOT_TOKEN", "").strip()
    if not token or token.endswith("replace-me"):
        raise ConfigError("Не задан BOT_TOKEN: скопируйте .env.example в .env и впишите токен от @BotFather.")
    admin = env.get("ADMIN_CHAT_ID", "").strip()
    try:
        admin_chat_id = int(admin) if admin else None
    except ValueError:
        raise ConfigError(f"ADMIN_CHAT_ID должен быть числом, сейчас: {admin!r}.") from None
    return Settings(
        bot_token=token,
        admin_chat_id=admin_chat_id,
        db_path=Path(env.get("DB_PATH", "data/mint.db")),
        salon_path=Path(env.get("SALON_CONFIG", "salon.toml")),
    )


def _time(value: Any, where: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        raise ConfigError(f"{where}: ожидается время вида 10:00, сейчас: {value!r}.") from None


def parse_salon(data: Mapping[str, Any]) -> Salon:
    try:
        tz = ZoneInfo(data.get("timezone", "Europe/Moscow"))
    except ZoneInfoNotFoundError:
        raise ConfigError(f"Неизвестный часовой пояс: {data.get('timezone')!r}.") from None

    s = data.get("schedule", {})
    schedule = Schedule(
        workdays=frozenset(int(d) for d in s.get("workdays", [1, 2, 3, 4, 5, 6])),
        opens=_time(s.get("opens", "10:00"), "schedule.opens"),
        closes=_time(s.get("closes", "20:00"), "schedule.closes"),
        breaks=tuple(
            (_time(a, "schedule.breaks"), _time(b, "schedule.breaks")) for a, b in s.get("breaks", [])
        ),
        days_ahead=int(s.get("days_ahead", 6)),
        min_lead_minutes=int(s.get("min_lead_minutes", 60)),
    )
    if schedule.opens >= schedule.closes:
        raise ConfigError("schedule: салон должен открываться раньше, чем закрывается.")
    if not schedule.workdays <= set(range(1, 8)):
        raise ConfigError("schedule.workdays: дни недели — числа от 1 до 7.")

    r = data.get("reminders", {})
    reminders = ReminderPolicy(
        day_before_at=_time(r.get("day_before_at", "18:00"), "reminders.day_before_at"),
        before_minutes=int(r.get("before_minutes", 120)),
    )

    masters = {m["id"]: Master(id=m["id"], name=m["name"]) for m in data.get("masters", [])}
    services: dict[str, Service] = {}
    for raw in data.get("services", []):
        service = Service(
            id=raw["id"],
            title=raw["title"],
            price=int(raw["price"]),
            duration_minutes=int(raw["duration_minutes"]),
            masters=tuple(raw["masters"]),
            price_from=bool(raw.get("price_from", False)),
        )
        unknown = [m for m in service.masters if m not in masters]
        if unknown or not service.masters:
            raise ConfigError(f"Услуга {service.id!r}: неизвестные мастера {unknown or '— список пуст'}.")
        if service.duration_minutes <= 0:
            raise ConfigError(f"Услуга {service.id!r}: длительность должна быть больше нуля.")
        services[service.id] = service
    if not services:
        raise ConfigError("В salon.toml нет ни одной услуги.")

    return Salon(
        name=data.get("name", "Мята"),
        address=data.get("address", ""),
        tz=tz,
        schedule=schedule,
        reminders=reminders,
        masters=masters,
        services=services,
        max_active_bookings=int(data.get("max_active_bookings", 3)),
    )


def load_salon(path: Path) -> Salon:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Не найден файл с данными салона: {path}.") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Ошибка в {path}: {e}.") from None
    return parse_salon(data)
