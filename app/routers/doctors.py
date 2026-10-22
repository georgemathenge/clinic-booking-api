from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_now
from app.models import Doctor
from app.schemas import AvailabilityOut, DoctorOut, SlotOut
from app.services import booking

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db)):
    return db.scalars(select(Doctor).options(selectinload(Doctor.working_hours)).order_by(Doctor.id)).all()


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    return booking.get_doctor(db, doctor_id)


@router.get("/{doctor_id}/availability", response_model=AvailabilityOut)
def get_availability(
    doctor_id: int,
    date: Annotated[date, Query(description="Day to check, YYYY-MM-DD (clinic-local)")],
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime = Depends(get_now),
):
    slots = booking.available_slots(db, settings, doctor_id, date, now)
    length = timedelta(minutes=settings.slot_minutes)
    return AvailabilityOut(
        doctor_id=doctor_id,
        date=date,
        timezone=settings.clinic_timezone,
        slot_minutes=settings.slot_minutes,
        slots=[SlotOut(start_time=s, end_time=s + length) for s in slots],
    )

