"""Pure slot arithmetic: no database, so it's easy to unit-test."""

from collections.abc import Iterable
from datetime import date, datetime, timedelta, tzinfo

from app.models import WorkingHours


def generate_slots(
    working_hours: Iterable[WorkingHours], day: date, slot_minutes: int, tz: tzinfo
) -> list[datetime]:
    """Every slot start for a doctor on `day`, in clinic-local time.

    Slots are laid out from the start of each working block; a trailing
    fragment shorter than a full slot is dropped (e.g. 09:00-10:45 gives
    09:00, 09:30, 10:00 - not 10:30).
    """
    step = timedelta(minutes=slot_minutes)
    slots: list[datetime] = []
    for block in sorted(working_hours, key=lambda b: b.start_time):
        if block.weekday != day.weekday():
            continue
        cursor = datetime.combine(day, block.start_time, tzinfo=tz)
        block_end = datetime.combine(day, block.end_time, tzinfo=tz)
        while cursor + step <= block_end:
            slots.append(cursor)
            cursor += step
    return slots


def earliest_bookable(now: datetime, lead_minutes: int) -> datetime:
    return now + timedelta(minutes=lead_minutes)


def normalize(dt: datetime, tz: tzinfo) -> datetime:
    """Interpret naive datetimes as clinic-local; convert aware ones to clinic tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)
