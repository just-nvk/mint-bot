"""Сетка времени, выходные, запас до начала и план напоминаний — чистые функции."""
from dataclasses import replace

from mint_bot import domain, texts
from mint_bot.config import Master

from .conftest import at


def hhmm(slots):
    return [f"{s.start:%H:%M}" for s in slots]


def test_grid_matches_video(salon):
    manicure = salon.services["manicure"]
    slots = domain.free_slots(salon, manicure, at(12, 0).date(), {}, at(9, 10, 42))
    assert hhmm(slots) == ["10:00", "11:30", "14:00", "15:30", "17:00", "18:30"]


def test_grid_depends_on_duration_and_break(salon):
    day, now = at(12, 0).date(), at(9, 10)
    assert hhmm(domain.free_slots(salon, salon.services["haircut"], day, {}, now)) == [
        "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
    assert hhmm(domain.free_slots(salon, salon.services["coloring"], day, {}, now)) == ["10:00", "14:00", "16:30"]


def test_sunday_is_day_off(salon):
    assert domain.free_slots(salon, salon.services["manicure"], at(15, 0).date(), {}, at(9, 10)) == []


def test_no_booking_less_than_hour_before_start(salon):
    slots = domain.free_slots(salon, salon.services["manicure"], at(9, 0).date(), {}, at(9, 10, 41))
    assert hhmm(slots)[0] == "14:00"  # 11:30 — меньше чем через час


def test_bookable_days_skip_sunday_and_full_days(salon):
    manicure = salon.services["manicure"]
    days = domain.bookable_days(salon, manicure, {}, at(9, 10, 41))
    assert [texts.day_button(d) for d in days] == [
        "Пн, 9 нояб.", "Вт, 10 нояб.", "Ср, 11 нояб.", "Чт, 12 нояб.", "Пт, 13 нояб.", "Сб, 14 нояб."]
    # Суббота, 19:00: на сегодня времени уже нет, воскресенье — выходной
    days = domain.bookable_days(salon, manicure, {}, at(14, 19))
    assert texts.day_button(days[0]) == "Пн, 16 нояб."


def test_busy_master_hides_slot_and_second_master_takes_it(salon):
    manicure = salon.services["manicure"]
    busy = {"vera": [(at(12, 14), at(12, 15, 30))]}
    slots = domain.free_slots(salon, manicure, at(12, 0).date(), busy, at(9, 10))
    assert "14:00" not in hhmm(slots)

    two = replace(
        salon,
        masters={**salon.masters, "nina": Master("nina", "Нина")},
        services={**salon.services, "manicure": replace(manicure, masters=("vera", "nina"))},
    )
    slot = domain.find_slot(two, two.services["manicure"], at(12, 14), busy, at(9, 10))
    assert slot is not None and slot.master_id == "nina"


def test_reminders_evening_before_and_two_hours_before(salon):
    assert domain.plan_reminders(salon, at(12, 14), at(9, 10, 42)) == [
        ("day_before", at(11, 18)), ("before", at(12, 12))]
    # Записались накануне вечером — напоминание «накануне» уже не нужно
    assert domain.plan_reminders(salon, at(12, 14), at(11, 19)) == [("before", at(12, 12))]
    # Записались за полтора часа — напоминать некогда
    assert domain.plan_reminders(salon, at(12, 14), at(12, 12, 30)) == []


def test_russian_formatting(salon):
    assert texts.duration(90) == "1,5 часа"
    assert texts.duration(60) == "1 час"
    assert texts.duration(150) == "2,5 часа"
    assert texts.duration(300) == "5 часов"
    assert texts.duration(45) == "45 минут"
    assert texts.lead(120) == "за 2 часа"
    assert texts.lead(60) == "за час"
    assert texts.price(salon.services["coloring"]) == "от 3 500 ₽"
    assert texts.money(15000) == "15 000 ₽"
    assert texts.when(at(12, 14)) == "чт, 12 ноября, 14:00"
    assert texts.too_many(3) == ("У вас уже 3 записи — больше пока нельзя. "
                                 "Перенести или отменить запись можно в «Мои записи».")
    assert [texts.plural(n, "запись", "записи", "записей") for n in (1, 2, 5, 11, 21)] == [
        "запись", "записи", "записей", "записей", "запись"]
