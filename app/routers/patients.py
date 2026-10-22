from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_now
from app.errors import Conflict
from app.models import Patient
from app.schemas import AppointmentOut, PatientCreate, PatientOut
from app.services import booking

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientCreate, db: Session = Depends(get_db)):
    patient = Patient(**body.model_dump())
    db.add(patient)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"A patient with email {body.email} already exists") from exc
    db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    return booking.get_patient(db, patient_id)


@router.get("/{patient_id}/appointments", response_model=list[AppointmentOut])
def list_upcoming_appointments(
    patient_id: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
):
    """Upcoming (booked, not yet started) appointments, soonest first."""
    return booking.upcoming_for_patient(db, patient_id, now)
