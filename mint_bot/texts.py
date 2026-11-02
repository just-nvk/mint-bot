"""Все тексты бота. Они же — в видео (tests/scenario.json), тесты следят, чтобы не разошлись."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

from .config import Salon, Service
from .domain import Booking

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WD = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")
MONTHS_SHORT = ("янв.", "февр.", "марта", "апр.", "мая", "июня",
                "июля", "авг.", "сент.", "окт.", "нояб.", "дек.")

# Кнопки
BTN_MY = "Мои записи"
BTN_NEW = "Записаться"
BTN_BACK = "‹ Назад"
BTN_CONFIRM = "Подтвердить"
BTN_EDIT = "Изменить"
BTN_COME = "Да, приду"
BTN_MOVE = "Перенести"
BTN_CANCEL = "Отменить"
BTN_CANCEL_YES = "Да, отменить"
BTN_CANCEL_NO = "Нет"
BTN_CONTACT = "Написать клиенту"

CHOOSE_SERVICE = "Выберите услугу:"
SEE_YOU = "Отлично, ждём вас!"
SLOT_TAKEN = "Это время только что заняли. Выберите другое:"
DAY_FULL = "На этот день свободного времени не осталось. Выберите другой день:"
NO_DAYS = "На ближайшие дни свободного времени нет. Загляните позже — расписание обновляется."
MY_EMPTY = "Записей пока нет."
MY_HEADER = "Ваши записи:"
CANCELLED = "Запись отменена. Будем рады видеть вас снова!"
STALE = "Эта запись уже неактуальна."
UNKNOWN = "Чтобы записаться, нажмите /start. Ваши записи — /my."


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def price(service: Service) -> str:
    return ("от " if service.price_from else "") + money(service.price)


def duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if minutes < 60:
        return f"{minutes} {plural(minutes, 'минута', 'минуты', 'минут')}"
    if rest == 0:
        return f"{hours} {plural(hours, 'час', 'часа', 'часов')}"
    if rest == 30:
        return f"{hours},5 часа"
    return f"{hours} ч {rest} мин"


def lead(minutes: int) -> str:
    return "за час" if minutes == 60 else f"за {duration(minutes)}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def day_button(d: date) -> str:
    return f"{_cap(WD[d.weekday()])}, {d.day} {MONTHS_SHORT[d.month - 1]}"


def day_title(d: date) -> str:
    return f"{_cap(WEEKDAYS[d.weekday()])}, {d.day} {MONTHS[d.month - 1]}"


def when(dt: datetime) -> str:
    """чт, 12 ноября, 14:00"""
    return f"{WD[dt.weekday()]}, {dt.day} {MONTHS[dt.month - 1]}, {dt:%H:%M}"


def relative_day(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "сегодня"
    if delta == 1:
        return "завтра"
    return WD[d.weekday()]


# ---------- клиент ----------

def description(salon: Salon) -> str:
    return (f"Запись в салон «{salon.name}» без звонков: выберите услугу, день и время — "
            "бот подтвердит запись и напомнит о визите.")


def short_description(salon: Salon) -> str:
    return f"Запись в салон «{salon.name}» без звонков"


def greeting(salon: Salon) -> str:
    return f"Здравствуйте! Это салон «{salon.name}».\nЗапишу вас к мастеру за минуту — выберите услугу:"


def service_button(service: Service) -> str:
    return f"{service.title} · {price(service)}"


def service_line(service: Service) -> str:
    return f"{service.title} · {price(service)} · {duration(service.duration_minutes)}"


def choose_day(service: Service, moving: bool = False) -> str:
    question = "На какой день перенести запись?" if moving else "На какой день записать?"
    return f"{service_line(service)}\n{question}"


def free_time(d: date) -> str:
    return f"{day_title(d)}. Свободное время:"


def summary(salon: Salon, service: Service, start: datetime, master_id: str) -> str:
    return (
        "Проверьте запись:\n\n"
        f"Услуга: {service.title} · {price(service)}\n"
        f"Когда: {when(start)}\n"
        f"Мастер: {salon.master(master_id).name}\n"
        f"Адрес: {salon.address}"
    )


def summary_move(salon: Salon, service: Service, old: datetime, start: datetime, master_id: str) -> str:
    return (
        "Проверьте перенос:\n\n"
        f"Услуга: {service.title} · {price(service)}\n"
        f"Было: {when(old)}\n"
        f"Станет: {when(start)}\n"
        f"Мастер: {salon.master(master_id).name}\n"
        f"Адрес: {salon.address}"
    )


def booked(salon: Salon) -> str:
    return (f"Готово, вы записаны ✅\nНапомню накануне и {lead(salon.reminders.before_minutes)} до визита. "
            "Перенести или отменить запись можно в «Мои записи».")


def moved(salon: Salon) -> str:
    return f"Готово, запись перенесена ✅\nНапомню накануне и {lead(salon.reminders.before_minutes)} до визита."


def too_many(limit: int) -> str:
    return (f"У вас уже {limit} {plural(limit, 'запись', 'записи', 'записей')} — больше пока нельзя. "
            "Перенести или отменить запись можно в «Мои записи».")


def booking_card(salon: Salon, b: Booking) -> str:
    service = salon.services[b.service_id]
    return f"{service.title} — {when(b.starts_at)}\nМастер: {salon.master(b.master_id).name}"


def cancel_question(salon: Salon, b: Booking) -> str:
    return f"Отменить запись?\n\n{booking_card(salon, b)}"


def reminder(salon: Salon, b: Booking, now: datetime) -> str:
    service = salon.services[b.service_id]
    start = b.starts_at
    day = relative_day(start.date(), now.astimezone(salon.tz).date())
    return (
        f"Напоминаю о записи: {day}, {start.day} {MONTHS[start.month - 1]}, в {start:%H:%M} — "
        f"{service.title[:1].lower()}{service.title[1:]}, мастер {salon.master(b.master_id).name}.\n"
        f"Адрес: {salon.address}. Всё в силе?"
    )


# ---------- администраторы ----------

def _admin(title: str, lines: list[str], b: Booking, html: bool) -> str:
    e = escape if html else (lambda s: s)
    client = f'<a href="tg://user?id={b.user_id}">{escape(b.client_name)}</a>' if html else b.client_name
    return "\n".join([e(title), *map(e, lines), f"Клиент: {client}"])


def admin_new(salon: Salon, b: Booking, html: bool = False) -> str:
    service = salon.services[b.service_id]
    return _admin("Новая запись", [
        f"{service.title} · {price(service)}",
        _cap(when(b.starts_at)),
        f"Мастер: {salon.master(b.master_id).name}",
    ], b, html)


def admin_moved(salon: Salon, b: Booking, old: datetime, html: bool = False) -> str:
    service = salon.services[b.service_id]
    return _admin("Запись перенесена", [
        f"{service.title} · {price(service)}",
        f"Было: {_cap(when(old))}",
        f"Стало: {_cap(when(b.starts_at))}",
        f"Мастер: {salon.master(b.master_id).name}",
    ], b, html)


def admin_cancelled(salon: Salon, b: Booking, html: bool = False) -> str:
    service = salon.services[b.service_id]
    return _admin("Запись отменена", [
        f"{service.title} · {price(service)}",
        _cap(when(b.starts_at)),
        f"Мастер: {salon.master(b.master_id).name}",
    ], b, html)


def admin_day(salon: Salon, day: date, today: date, bookings: list[Booking]) -> str:
    rel = relative_day(day, today)
    head = f"{rel}, {WD[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}" if rel in ("сегодня", "завтра") \
        else f"{WD[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"
    if not bookings:
        return f"На {head}, записей нет."
    lines = [
        f"{b.starts_at:%H:%M} — {salon.services[b.service_id].title}, {salon.master(b.master_id).name}"
        f" · {b.client_name}{' ✅' if b.confirmed_at else ''}"
        for b in bookings
    ]
    return f"Записи на {head}:\n\n" + "\n".join(lines)


def chat_id(chat_id: int) -> str:
    return f"ID этого чата: {chat_id}\nУкажите его в .env: ADMIN_CHAT_ID={chat_id}"
