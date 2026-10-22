from tests.conftest import MONDAY, SATURDAY, TUESDAY, at


def slot_times(resp):
    return [s["start_time"][11:16] for s in resp.json()["slots"]]


def test_full_day_availability(client, doctor):
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": TUESDAY.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["slot_minutes"] == 30
    assert body["timezone"] == "Africa/Nairobi"
    assert slot_times(resp) == [
        "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
        "13:00", "13:30", "14:00", "14:30",
    ]


def test_booked_slot_is_hidden(client, doctor, book):
    assert book(at(TUESDAY, 10)).status_code == 201
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": TUESDAY.isoformat()})
    assert "10:00" not in slot_times(resp)
    assert "10:30" in slot_times(resp)


def test_today_hides_slots_within_lead_time(client, doctor):
    # NOW is Monday 08:00 with a 60-minute lead, so 09:00 is the first bookable slot.
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": MONDAY.isoformat()})
    assert slot_times(resp)[0] == "09:00"


def test_day_off_returns_empty(client, doctor):
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": SATURDAY.isoformat()})
    assert resp.status_code == 200
    assert resp.json()["slots"] == []


def test_past_date_returns_empty(client, doctor):
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": "2029-12-31"})
    assert resp.json()["slots"] == []


def test_unknown_doctor_404(client):
    resp = client.get("/doctors/999/availability", params={"date": TUESDAY.isoformat()})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_bad_date_422(client, doctor):
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": "not-a-date"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
