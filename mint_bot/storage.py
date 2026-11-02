"""Хранение в SQLite: записи и запланированные напоминания.

Время в базе — в UTC (ISO 8601), наружу отдаётся в часовом поясе салона.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

from .domain import Booking, Interval, SlotTaken, TooManyBookings

SCHEMA = [
    # v1
    """
    CREATE TABLE bookings (
        id           INTEGER PRIMARY KEY,
        user_id      INTEGER NOT NULL,
        chat_id      INTEGER NOT NULL,
        client_name  TEXT    NOT NULL,
        username     TEXT,
        service_id   TEXT    NOT NULL,
        master_id    TEXT    NOT NULL,
        starts_at    TEXT    NOT NULL,
        ends_at      TEXT    NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'active',
        confirmed_at TEXT,
        created_at   TEXT    NOT NULL
    );
    CREATE INDEX bookings_master_time ON bookings (master_id, starts_at) WHERE status = 'active';
    CREATE INDEX bookings_user ON bookings (user_id, starts_at) WHERE status = 'active';
    CREATE TABLE reminders (
        id         INTEGER PRIMARY KEY,
        booking_id INTEGER NOT NULL REFERENCES bookings (id),
        kind       TEXT    NOT NULL,
        due_at     TEXT    NOT NULL,
        status     TEXT    NOT NULL DEFAULT 'pending',
        done_at    TEXT,
        UNIQUE (booking_id, kind)
    );
    CREATE INDEX reminders_due ON reminders (due_at) WHERE status = 'pending';
    """,
]


@dataclass(frozen=True)
class Reminder:
    id: int
    booking_id: int
    kind: str
    due_at: datetime


def _enc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("ожидается время с часовым поясом")
    return dt.astimezone(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db: aiosqlite.Connection, tz: ZoneInfo):
        self._db = db
        self._tz = tz
        # Одно соединение на процесс: записи идут по очереди, проверка и вставка — одна транзакция.
        self._write = asyncio.Lock()

    @classmethod
    async def open(cls, path: str | Path, tz: ZoneInfo) -> Storage:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(path, isolation_level=None)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            await db.execute("PRAGMA journal_mode = WAL")
        storage = cls(db, tz)
        await storage._migrate()
        return storage

    async def close(self) -> None:
        await self._db.close()

    async def _migrate(self) -> None:
        async with self._db.execute("PRAGMA user_version") as cur:
            (version,) = await cur.fetchone()
        for number, script in enumerate(SCHEMA[version:], start=version + 1):
            await self._db.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")

    # ---------- преобразования ----------

    def _dec(self, value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).astimezone(self._tz) if value else None

    def _booking(self, row: aiosqlite.Row) -> Booking:
        return Booking(
            id=row["id"], user_id=row["user_id"], chat_id=row["chat_id"],
            client_name=row["client_name"], username=row["username"],
            service_id=row["service_id"], master_id=row["master_id"],
            starts_at=self._dec(row["starts_at"]), ends_at=self._dec(row["ends_at"]),
            status=row["status"], confirmed_at=self._dec(row["confirmed_at"]),
            created_at=self._dec(row["created_at"]),
        )

    async def _transaction(self):
        await self._db.execute("BEGIN IMMEDIATE")

    async def _overlap(self, master_id: str, start: datetime, end: datetime, exclude: int | None) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM bookings WHERE status = 'active' AND master_id = ? "
            "AND starts_at < ? AND ends_at > ? AND id IS NOT ? LIMIT 1",
            (master_id, _enc(end), _enc(start), exclude),
        ) as cur:
            return await cur.fetchone() is not None

    async def _insert_reminders(self, booking_id: int, reminders: Iterable[tuple[str, datetime]]) -> None:
        await self._db.executemany(
            "INSERT INTO reminders (booking_id, kind, due_at) VALUES (?, ?, ?)",
            [(booking_id, kind, _enc(due)) for kind, due in reminders],
        )

    # ---------- чтение ----------

    async def get(self, booking_id: int) -> Booking | None:
        async with self._db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)) as cur:
            row = await cur.fetchone()
        return self._booking(row) if row else None

    async def busy(self, master_ids: Sequence[str], start: datetime, end: datetime) -> dict[str, list[Interval]]:
        marks = ",".join("?" * len(master_ids))
        async with self._db.execute(
            f"SELECT master_id, starts_at, ends_at FROM bookings WHERE status = 'active' "
            f"AND master_id IN ({marks}) AND starts_at < ? AND ends_at > ?",
            (*master_ids, _enc(end), _enc(start)),
        ) as cur:
            rows = await cur.fetchall()
        busy: dict[str, list[Interval]] = {m: [] for m in master_ids}
        for row in rows:
            busy[row["master_id"]].append((self._dec(row["starts_at"]), self._dec(row["ends_at"])))
        return busy

    async def upcoming_for_user(self, user_id: int, now: datetime) -> list[Booking]:
        async with self._db.execute(
            "SELECT * FROM bookings WHERE status = 'active' AND user_id = ? AND starts_at > ? ORDER BY starts_at",
            (user_id, _enc(now)),
        ) as cur:
            return [self._booking(r) for r in await cur.fetchall()]

    async def between(self, start: datetime, end: datetime) -> list[Booking]:
        async with self._db.execute(
            "SELECT * FROM bookings WHERE status = 'active' AND starts_at >= ? AND starts_at < ? ORDER BY starts_at",
            (_enc(start), _enc(end)),
        ) as cur:
            return [self._booking(r) for r in await cur.fetchall()]

    async def due_reminders(self, now: datetime) -> list[tuple[Reminder, Booking]]:
        async with self._db.execute(
            "SELECT r.id AS r_id, r.kind AS r_kind, r.due_at AS r_due, b.* FROM reminders r "
            "JOIN bookings b ON b.id = r.booking_id "
            "WHERE r.status = 'pending' AND r.due_at <= ? AND b.status = 'active' ORDER BY r.due_at",
            (_enc(now),),
        ) as cur:
            rows = await cur.fetchall()
        return [
            (Reminder(id=r["r_id"], booking_id=r["id"], kind=r["r_kind"], due_at=self._dec(r["r_due"])),
             self._booking(r))
            for r in rows
        ]

    async def reminders_of(self, booking_id: int) -> list[tuple[str, datetime, str]]:
        async with self._db.execute(
            "SELECT kind, due_at, status FROM reminders WHERE booking_id = ? ORDER BY due_at", (booking_id,)
        ) as cur:
            return [(r["kind"], self._dec(r["due_at"]), r["status"]) for r in await cur.fetchall()]

    # ---------- запись ----------

    async def create(
        self, *, user_id: int, chat_id: int, client_name: str, username: str | None,
        service_id: str, master_id: str, starts_at: datetime, ends_at: datetime,
        now: datetime, max_active: int, reminders: Iterable[tuple[str, datetime]],
    ) -> Booking:
        async with self._write:
            await self._transaction()
            try:
                if await self._overlap(master_id, starts_at, ends_at, None):
                    raise SlotTaken
                async with self._db.execute(
                    "SELECT COUNT(*) FROM bookings WHERE status = 'active' AND user_id = ? AND starts_at > ?",
                    (user_id, _enc(now)),
                ) as cur:
                    (active,) = await cur.fetchone()
                if max_active and active >= max_active:
                    raise TooManyBookings(max_active)
                cur = await self._db.execute(
                    "INSERT INTO bookings (user_id, chat_id, client_name, username, service_id, master_id, "
                    "starts_at, ends_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, chat_id, client_name, username, service_id, master_id,
                     _enc(starts_at), _enc(ends_at), _enc(now)),
                )
                booking_id = cur.lastrowid
                await self._insert_reminders(booking_id, reminders)
                await self._db.execute("COMMIT")
            except BaseException:
                await self._db.execute("ROLLBACK")
                raise
        return await self.get(booking_id)

    async def reschedule(
        self, booking_id: int, *, master_id: str, starts_at: datetime, ends_at: datetime,
        reminders: Iterable[tuple[str, datetime]],
    ) -> Booking:
        async with self._write:
            await self._transaction()
            try:
                if await self._overlap(master_id, starts_at, ends_at, booking_id):
                    raise SlotTaken
                await self._db.execute(
                    "UPDATE bookings SET master_id = ?, starts_at = ?, ends_at = ?, confirmed_at = NULL "
                    "WHERE id = ? AND status = 'active'",
                    (master_id, _enc(starts_at), _enc(ends_at), booking_id),
                )
                await self._db.execute("DELETE FROM reminders WHERE booking_id = ?", (booking_id,))
                await self._insert_reminders(booking_id, reminders)
                await self._db.execute("COMMIT")
            except BaseException:
                await self._db.execute("ROLLBACK")
                raise
        return await self.get(booking_id)

    async def cancel(self, booking_id: int) -> Booking:
        async with self._write:
            await self._transaction()
            try:
                await self._db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
                await self._db.execute(
                    "DELETE FROM reminders WHERE booking_id = ? AND status = 'pending'", (booking_id,)
                )
                await self._db.execute("COMMIT")
            except BaseException:
                await self._db.execute("ROLLBACK")
                raise
        return await self.get(booking_id)

    async def confirm_visit(self, booking_id: int, at: datetime) -> None:
        async with self._write:
            await self._db.execute("UPDATE bookings SET confirmed_at = ? WHERE id = ?", (_enc(at), booking_id))

    async def mark_reminders(self, ids: Sequence[int], status: str, at: datetime) -> None:
        async with self._write:
            await self._db.executemany(
                "UPDATE reminders SET status = ?, done_at = ? WHERE id = ?",
                [(status, _enc(at), i) for i in ids],
            )
