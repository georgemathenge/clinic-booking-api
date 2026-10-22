from tests.conftest import TUESDAY, at


def availability(client, doctor):
    resp = client.get(f"/doctors/{doctor.id}/availability", params={"date": TUESDAY.isoformat()})
    return [s["start_time"][11:16] for s in resp.json()["slots"]]


# --- cancel ------------------------------------------------------------------

def test_cancel_frees_slot(client, doctor, book, other_patient):
    appt = book(at(TUESDAY, 10)).json()
    resp = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "Feeling better"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "Feeling better"
    assert body["cancelled_at"] is not None

    assert "10:00" in availability(client, doctor)
    # ...and someone else can now take it.
    assert book(at(TUESDAY, 10), patient_id=other_patient.id).status_code == 201


def test_cancel_twice_errors(client, book):
    appt = book(at(TUESDAY, 10)).json()
    client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "x"})
    resp = client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "again"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_STATE"
    assert "already cancelled" in resp.json()["error"]["message"]


def test_cancel_requires_reason(client, book):
    appt = book(at(TUESDAY, 10)).json()
    assert client.patch(f"/appointments/{appt['id']}/cancel", json={}).status_code == 422
    assert client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": ""}).status_code == 422


def test_cancel_unknown_404(client):
    assert client.patch("/appointments/999/cancel", json={"reason": "x"}).status_code == 404


# --- reschedule --------------------------------------------------------------

def test_reschedule_moves_slot(client, doctor, book):
    appt = book(at(TUESDAY, 10)).json()
    resp = client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_time": at(TUESDAY, 14)})
    assert resp.status_code == 200
    assert resp.json()["start_time"] == "2030-01-08T14:00:00+03:00"
    assert resp.json()["id"] == appt["id"]

    slots = availability(client, doctor)
    assert "10:00" in slots      # original freed
    assert "14:00" not in slots  # new one taken


def test_reschedule_to_taken_slot(client, book, other_patient):
    appt = book(at(TUESDAY, 10)).json()
    book(at(TUESDAY, 11), patient_id=other_patient.id)
    resp = client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_time": at(TUESDAY, 11)})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SLOT_TAKEN"
    # Original booking is untouched.
    assert client.get(f"/appointments/{appt['id']}").json()["start_time"].startswith("2030-01-08T10:00")


def test_reschedule_validates_like_new_booking(client, book):
    appt = book(at(TUESDAY, 10)).json()
    for bad in (at(TUESDAY, 12), at(TUESDAY, 9, 15), "2030-01-01T10:00:00+03:00"):
        resp = client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_time": bad})
        assert resp.status_code == 422, bad


def test_reschedule_cancelled_errors(client, book):
    appt = book(at(TUESDAY, 10)).json()
    client.patch(f"/appointments/{appt['id']}/cancel", json={"reason": "x"})
    resp = client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_time": at(TUESDAY, 11)})
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["error"]["message"]


def test_reschedule_to_same_slot_errors(client, book):
    appt = book(at(TUESDAY, 10)).json()
    resp = client.patch(f"/appointments/{appt['id']}/reschedule", json={"start_time": at(TUESDAY, 10)})
    assert resp.status_code == 422


# --- patient appointments (bonus) ---------------------------------------------

def test_patient_upcoming_sorted_and_excludes_cancelled(client, book, patient):
    late = book(at(TUESDAY, 14)).json()
    early = book(at(TUESDAY, 9)).json()
    cancelled = book(at(TUESDAY, 11)).json()
    client.patch(f"/appointments/{cancelled['id']}/cancel", json={"reason": "x"})

    resp = client.get(f"/patients/{patient.id}/appointments")
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()] == [early["id"], late["id"]]
