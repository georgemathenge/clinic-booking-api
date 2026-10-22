import threading
from datetime import datetime

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.errors import SlotTaken
from app.services import booking
from tests.conftest import MONDAY, NOW, SATURDAY, TUESDAY, at


def error_code(resp):
    return resp.json()["error"]["code"]


def test_book_valid_slot(book, doctor, patient):
    resp = book(at(TUESDAY, 9, 30))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "booked"
    assert body["start_time"] == "2030-01-08T09:30:00+03:00"
    assert body["end_time"] == "2030-01-08T10:00:00+03:00"


def test_naive_time_is_treated_as_clinic_local(book):
    resp = book("2030-01-08T09:30:00")
    assert resp.status_code == 201
    assert resp.json()["start_time"] == "2030-01-08T09:30:00+03:00"


def test_utc_input_is_converted(book):
    # 06:30Z == 09:30 Nairobi
    resp = book("2030-01-08T06:30:00Z")
    assert resp.status_code == 201
    assert resp.json()["start_time"] == "2030-01-08T09:30:00+03:00"


def test_double_booking_rejected(book, other_patient):
    assert book(at(TUESDAY, 10)).status_code == 201
    resp = book(at(TUESDAY, 10), patient_id=other_patient.id)
    assert resp.status_code == 409
    assert error_code(resp) == "SLOT_TAKEN"


def test_patient_cannot_be_in_two_places(client, book, patient, db):
    from datetime import time

    from app.models import Doctor, WorkingHours

    other_doc = Doctor(name="Dr. Other", working_hours=[WorkingHours(weekday=1, start_time=time(9), end_time=time(12))])
    db.add(other_doc)
    db.commit()

    assert book(at(TUESDAY, 10)).status_code == 201
    resp = book(at(TUESDAY, 10), doctor_id=other_doc.id)
    assert resp.status_code == 409
    assert error_code(resp) == "PATIENT_DOUBLE_BOOKED"


@pytest.mark.parametrize(
    "start, fragment",
    [
        (at(TUESDAY, 8), "not working"),           # before hours
        (at(TUESDAY, 12), "not working"),          # lunch break
        (at(TUESDAY, 15), "not working"),          # end of day is not a start
        (at(SATURDAY, 10), "not working"),         # day off
        (at(TUESDAY, 9, 15), "align"),             # off the 30-min grid
    ],
)
def test_outside_working_hours_rejected(book, start, fragment):
    resp = book(start)
    assert resp.status_code == 422
    assert error_code(resp) == "INVALID_SLOT"
    assert fragment in resp.json()["error"]["message"]


def test_past_rejected(book):
    resp = book("2030-01-04T10:00:00+03:00")  # previous Friday
    assert resp.status_code == 422
    assert "past" in resp.json()["error"]["message"]


def test_within_one_hour_rejected(book, doctor, db):
    from datetime import time

    from app.models import WorkingHours

    # Give the doctor an early block so there's a slot inside the lead window.
    db.add(WorkingHours(doctor_id=doctor.id, weekday=0, start_time=time(8, 30), end_time=time(9)))
    db.commit()
    resp = book(at(MONDAY, 8, 30))  # NOW is 08:00
    assert resp.status_code == 422
    assert "60 minutes" in resp.json()["error"]["message"]


def test_exactly_one_hour_ahead_allowed(book):
    assert book(at(MONDAY, 9)).status_code == 201


def test_unknown_doctor_or_patient(book):
    assert book(at(TUESDAY, 10), doctor_id=999).status_code == 404
    assert book(at(TUESDAY, 10), patient_id=999).status_code == 404


def test_missing_fields_422(client):
    resp = client.post("/appointments", json={"doctor_id": 1})
    assert resp.status_code == 422
    fields = {d["field"] for d in resp.json()["error"]["details"]}
    assert {"patient_id", "start_time"} <= fields


def test_concurrent_bookings_only_one_wins(doctor, patient, other_patient, monkeypatch):
    """Two requests race for the same slot and both pass the app-level check.

    The pre-check is disabled to force the worst-case interleaving; the partial
    unique index is then the only thing standing between us and a double-booking.
    """
    monkeypatch.setattr(booking, "_ensure_free", lambda *a, **k: None)
    settings = get_settings()
    start = datetime.fromisoformat(at(TUESDAY, 11))
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(patient_id):
        session = SessionLocal()
        try:
            barrier.wait()
            booking.book(session, settings, doctor_id=doctor.id, patient_id=patient_id, start_time=start, now=NOW)
            results.append("ok")
        except SlotTaken:
            results.append("taken")
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(pid,)) for pid in (patient.id, other_patient.id)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "taken"]


def test_cancelled_rows_do_not_block_the_index(client, book, other_patient):
    """Many cancelled bookings for one slot can coexist with one active booking."""
    for _ in range(3):
        appt = book(at(TUESDAY, 11)).json()
        client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "x"})
    assert book(at(TUESDAY, 11), patient_id=other_patient.id).status_code == 201
