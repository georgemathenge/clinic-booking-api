import os

# Point the app at the test database before anything imports app.db.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://clinic:clinic@localhost:5432/clinic_test"
)

from datetime import datetime, time  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.deps import get_now  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Doctor, Patient, WorkingHours  # noqa: E402

TZ = get_settings().tz
# Monday 7 Jan 2030, 08:00 at the clinic. Every test runs "at" this moment.
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=TZ)
MONDAY = NOW.date()
TUESDAY = datetime(2030, 1, 8, tzinfo=TZ).date()
SATURDAY = datetime(2030, 1, 12, tzinfo=TZ).date()


def at(day, hh, mm=0) -> str:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ).isoformat()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE appointments, working_hours, patients, doctors RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def doctor(db) -> Doctor:
    """Works Mon-Fri 09:00-12:00 and 13:00-15:00 (lunch break 12-13)."""
    doc = Doctor(name="Dr. Test", specialty="GP")
    for wd in range(5):
        doc.working_hours.append(WorkingHours(weekday=wd, start_time=time(9), end_time=time(12)))
        doc.working_hours.append(WorkingHours(weekday=wd, start_time=time(13), end_time=time(15)))
    db.add(doc)
    db.commit()
    return doc


@pytest.fixture
def patient(db) -> Patient:
    p = Patient(name="Pat One", email="pat1@example.com")
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def other_patient(db) -> Patient:
    p = Patient(name="Pat Two", email="pat2@example.com")
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def book(client, doctor, patient):
    """Helper: book(start_iso, patient_id=...) -> response."""

    def _book(start, patient_id=None, doctor_id=None):
        return client.post(
            "/appointments",
            json={
                "doctor_id": doctor_id or doctor.id,
                "patient_id": patient_id or patient.id,
                "start_time": start,
            },
        )

    return _book
