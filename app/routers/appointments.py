from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_now
from app.schemas import AppointmentCancel, AppointmentCreate, AppointmentOut, AppointmentReschedule
from app.services import booking

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(
    body: AppointmentCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
):
    return booking.book(
        db, settings, doctor_id=body.doctor_id, patient_id=body.patient_id, start_time=body.start_time, now=now
    )


@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    return booking.get_appointment(db, appointment_id)


@router.patch("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int,
    body: AppointmentCancel,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
):
    return booking.cancel(db, appointment_id, body.reason, now)


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(
    appointment_id: int,
    body: AppointmentReschedule,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
):
    return booking.reschedule(db, settings, appointment_id, body.start_time, now)
