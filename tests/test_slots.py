"""Unit tests for pure slot generation - no database."""

from datetime import time

from app.models import WorkingHours
from app.services.slots import generate_slots
from tests.conftest import MONDAY, TZ


def block(start, end, weekday=0):
    return WorkingHours(weekday=weekday, start_time=start, end_time=end)


def test_splits_block_into_30_minute_slots():
    slots = generate_slots([block(time(9), time(11))], MONDAY, 30, TZ)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:00", "10:30"]


def test_drops_trailing_partial_slot():
    slots = generate_slots([block(time(9), time(10, 45))], MONDAY, 30, TZ)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:00"]


def test_multiple_blocks_leave_gap_for_break():
    slots = generate_slots([block(time(13), time(14)), block(time(9), time(10))], MONDAY, 30, TZ)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "13:00", "13:30"]


def test_ignores_other_weekdays():
    assert generate_slots([block(time(9), time(10), weekday=1)], MONDAY, 30, TZ) == []
