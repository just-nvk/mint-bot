"""Запись, перенос и отмена на уровне сервиса и базы."""
import asyncio

import pytest

from mint_bot.booking import Client
from mint_bot.domain import BookingNotFound, SlotTaken, TooManyBookings

from .conftest import at

MARIA = Client(user_id=1001, chat_id=1001, name="Мария")
ANNA = Client(user_id=1002, chat_id=1002, name="Анна")


async def test_booked_time_disappears_for_others(service, salon):
    manicure = salon.services["manicure"]
    await service.book(MARIA, manicure, at(12, 14), "vera")
    times = [f"{s.start:%H:%M}" for s in await service.slots(manicure, at(12, 0).date())]
    assert times == ["10:00", "11:30", "15:30", "17:00", "18:30"]


async def test_two_clients_same_time_only_one_wins(service, salon):
    manicure = salon.services["manicure"]
    results = await asyncio.gather(
        service.book(MARIA, manicure, at(12, 14), "vera"),
        service.book(ANNA, manicure, at(12, 14), "vera"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, SlotTaken) for r in results) == 1
    assert len(await service.day(at(12, 0).date())) == 1


async def test_overlap_between_services_of_one_master(service, salon):
    # Ольга красит с 10:00 до 12:30 — стрижки в 10, 11 и 12 недоступны
    await service.book(MARIA, salon.services["coloring"], at(12, 10), "olga")
    times = [f"{s.start:%H:%M}" for s in await service.slots(salon.services["haircut"], at(12, 0).date())]
    assert times[0] == "14:00"


async def test_limit_of_active_bookings(service, salon):
    haircut = salon.services["haircut"]
    for hour in (10, 11, 12):
        await service.book(MARIA, haircut, at(12, hour), "olga")
    with pytest.raises(TooManyBookings):
        await service.book(MARIA, haircut, at(12, 14), "olga")


async def test_tampered_button_cannot_book_wrong_master_or_time(service, salon):
    manicure = salon.services["manicure"]
    with pytest.raises(SlotTaken):
        await service.book(MARIA, manicure, at(12, 14), "olga")  # Ольга не делает маникюр
    with pytest.raises(SlotTaken):
        await service.book(MARIA, manicure, at(12, 13), "vera")  # 13:00 — перерыв, не в сетке
    with pytest.raises(SlotTaken):
        await service.book(MARIA, manicure, at(15, 14), "vera")  # воскресенье


async def test_reschedule_moves_time_and_reminders(service, salon, storage):
    manicure = salon.services["manicure"]
    b = await service.book(MARIA, manicure, at(12, 14), "vera")
    old, new = await service.reschedule(b.id, MARIA.user_id, at(13, 11, 30), "vera")
    assert old.starts_at == at(12, 14) and new.starts_at == at(13, 11, 30)
    assert await storage.reminders_of(b.id) == [
        ("day_before", at(12, 18), "pending"), ("before", at(13, 9, 30), "pending")]
    times = [f"{s.start:%H:%M}" for s in await service.slots(manicure, at(12, 0).date())]
    assert "14:00" in times  # старое время освободилось


async def test_cancel_frees_time_and_drops_reminders(service, salon, storage):
    manicure = salon.services["manicure"]
    b = await service.book(MARIA, manicure, at(12, 14), "vera")
    await service.cancel(b.id, MARIA.user_id)
    assert await storage.reminders_of(b.id) == []
    assert await service.upcoming(MARIA.user_id) == []
    assert "14:00" in [f"{s.start:%H:%M}" for s in await service.slots(manicure, at(12, 0).date())]


async def test_only_owner_can_manage_future_booking(service, salon, clock):
    b = await service.book(MARIA, salon.services["manicure"], at(12, 14), "vera")
    with pytest.raises(BookingNotFound):
        await service.cancel(b.id, ANNA.user_id)
    clock.set(at(12, 15))  # визит уже начался
    with pytest.raises(BookingNotFound):
        await service.own(b.id, MARIA.user_id)
