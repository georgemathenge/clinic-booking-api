from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

from app.config import get_settings
from app.models import AppointmentStatus


def _to_clinic_tz(dt: datetime | None) -> datetime | None:
    # Stored as UTC; presented in clinic time so "09:00" means 9am at the clinic.
    return dt.astimezone(get_settings().tz) if dt else None


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Doctors ---------------------------------------------------------------

class WorkingHoursOut(ORMModel):
    weekday: int = Field(description="0 = Monday ... 6 = Sunday")
    start_time: time
    end_time: time


class DoctorOut(ORMModel):
    id: int
    name: str
    specialty: str | None
    working_hours: list[WorkingHoursOut]


class SlotOut(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    timezone: str
    slot_minutes: int
    slots: list[SlotOut]


# --- Patients --------------------------------------------------------------

class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)


class PatientOut(ORMModel):
    id: int
    name: str
    email: str
    phone: str | None


# --- Appointments ----------------------------------------------------------

class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    start_time: datetime = Field(
        description="Slot start. ISO 8601; if no offset is given it's read as clinic-local time.",
        examples=["2026-10-26T09:30:00+03:00"],
    )


class AppointmentCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AppointmentReschedule(BaseModel):
    start_time: datetime = Field(
        description="New slot start, same rules as booking.",
        examples=["2026-10-26T10:00:00+03:00"],
    )


class AppointmentOut(ORMModel):
    id: int
    doctor_id: int
    patient_id: int
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    cancellation_reason: str | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("start_time", "end_time", "cancelled_at", "created_at", "updated_at")
    def _serialize_dt(self, dt: datetime | None) -> datetime | None:
        return _to_clinic_tz(dt)
