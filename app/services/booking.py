"""Booking rules. Routers stay thin; everything that decides "can this happen?" lives here.

`now` is passed in rather than read from the clock so tests can pin time.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.errors import (
    Conflict,
    InvalidSlot,
    InvalidState,
    NotFound,
    PatientDoubleBooked,
    SlotTaken,
)
from app.models import Appointment, AppointmentStatus, Doctor, Patient
from app.services.slots import earliest_bookable, generate_slots, normalize


def get_doctor(db: Session, doctor_id: int) -> Doctor:
    doctor = db.scalar(
        select(Doctor).where(Doctor.id == doctor_id).options(selectinload(Doctor.working_hours))
    )
    if doctor is None:
        raise NotFound(f"Doctor {doctor_id} not found")
    return doctor


def get_patient(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise NotFound(f"Patient {patient_id} not found")
    return patient


def get_appointment(db: Session, appointment_id: int, *, for_update: bool = False) -> Appointment:
    stmt = select(Appointment).where(Appointment.id == appointment_id)
    if for_update:
        # Serialises concurrent cancel/reschedule calls on the same appointment.
        stmt = stmt.with_for_update()
    appt = db.scalar(stmt)
    if appt is None:
        raise NotFound(f"Appointment {appointment_id} not found")
    return appt


def _booked_starts(db: Session, doctor_id: int, start: datetime, end: datetime) -> set[datetime]:
    rows = db.scalars(
        select(Appointment.start_time).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.start_time >= start,
            Appointment.start_time < end,
        )
    )
    return set(rows)


def available_slots(
    db: Session, settings: Settings, doctor_id: int, day: date, now: datetime
) -> list[datetime]:
    doctor = get_doctor(db, doctor_id)
    tz = settings.tz
    slots = generate_slots(doctor.working_hours, day, settings.slot_minutes, tz)
    if not slots:
        return []

    cutoff = earliest_bookable(now, settings.min_booking_lead_minutes)
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    taken = _booked_starts(db, doctor_id, day_start, day_start + timedelta(days=1))
    return [s for s in slots if s >= cutoff and s not in taken]


def _validate_slot(
    settings: Settings,
    doctor: Doctor,
    start: datetime,
    now: datetime,
) -> datetime:
    """Check a slot is one the doctor actually offers and is far enough ahead.

    Returns the normalised (clinic-tz) start. Does not check whether it's taken:
    that's left to the database constraint so it's race-free.
    """
    tz = settings.tz
    start = normalize(start, tz)

    if start <= now:
        raise InvalidSlot("Cannot book a slot in the past")

    cutoff = earliest_bookable(now, settings.min_booking_lead_minutes)
    if start < cutoff:
        raise InvalidSlot(
            f"Appointments must be booked at least {settings.min_booking_lead_minutes} minutes in advance"
        )

    slots = generate_slots(doctor.working_hours, start.date(), settings.slot_minutes, tz)
    if start not in slots:
        # Give a more specific message when it's inside hours but off-grid.
        local = start.timetz().replace(tzinfo=None)
        inside_hours = any(
            b.weekday == start.weekday() and b.start_time <= local < b.end_time
            for b in doctor.working_hours
        )
        if inside_hours:
            raise InvalidSlot(
                f"Start time must align to a {settings.slot_minutes}-minute slot",
                details={"valid_slots": [s.isoformat() for s in slots]},
            )
        raise InvalidSlot(f"{doctor.name} is not working at {start.isoformat()}")

    return start


def _commit_or_conflict(db: Session) -> None:
    """Commit, translating unique-index violations into clear 409s.

    The pre-check in the caller gives nice errors in the common case; this
    catches the race where two requests pass the pre-check at the same time.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_appointments_doctor_slot_active":
            raise SlotTaken("This slot has just been booked by someone else") from exc
        if constraint == "uq_appointments_patient_slot_active":
            raise PatientDoubleBooked("Patient already has an appointment at this time") from exc
        raise Conflict("Could not save appointment") from exc


def _ensure_free(db: Session, doctor_id: int, patient_id: int, start: datetime, exclude_id: int | None = None) -> None:
    def active(*conds):
        stmt = select(Appointment.id).where(Appointment.status == AppointmentStatus.BOOKED, *conds)
        if exclude_id is not None:
            stmt = stmt.where(Appointment.id != exclude_id)
        return db.scalar(stmt.limit(1)) is not None

    if active(Appointment.doctor_id == doctor_id, Appointment.start_time == start):
        raise SlotTaken("This slot is already booked")
    if active(Appointment.patient_id == patient_id, Appointment.start_time == start):
        raise PatientDoubleBooked("Patient already has an appointment at this time")


def book(
    db: Session,
    settings: Settings,
    *,
    doctor_id: int,
    patient_id: int,
    start_time: datetime,
    now: datetime,
) -> Appointment:
    doctor = get_doctor(db, doctor_id)
    get_patient(db, patient_id)
    start = _validate_slot(settings, doctor, start_time, now)
    _ensure_free(db, doctor_id, patient_id, start)

    appt = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        start_time=start,
        end_time=start + timedelta(minutes=settings.slot_minutes),
        status=AppointmentStatus.BOOKED,
    )
    db.add(appt)
    _commit_or_conflict(db)
    db.refresh(appt)
    return appt


def cancel(db: Session, appointment_id: int, reason: str, now: datetime) -> Appointment:
    appt = get_appointment(db, appointment_id, for_update=True)
    if appt.status == AppointmentStatus.CANCELLED:
        db.rollback()
        raise InvalidState("Appointment is already cancelled")
    if appt.start_time <= now:
        db.rollback()
        raise InvalidState("Cannot cancel an appointment that has already started")

    appt.status = AppointmentStatus.CANCELLED
    appt.cancellation_reason = reason
    appt.cancelled_at = now
    db.commit()
    db.refresh(appt)
    return appt


def reschedule(
    db: Session, settings: Settings, appointment_id: int, new_start: datetime, now: datetime
) -> Appointment:
    appt = get_appointment(db, appointment_id, for_update=True)
    if appt.status == AppointmentStatus.CANCELLED:
        db.rollback()
        raise InvalidState("Cannot reschedule a cancelled appointment")
    if appt.start_time <= now:
        db.rollback()
        raise InvalidState("Cannot reschedule an appointment that has already started")

    doctor = get_doctor(db, appt.doctor_id)
    start = _validate_slot(settings, doctor, new_start, now)
    if start == appt.start_time:
        db.rollback()
        raise InvalidSlot("Appointment is already booked for this slot")
    _ensure_free(db, appt.doctor_id, appt.patient_id, start, exclude_id=appt.id)

    # Moving the row frees the old slot and claims the new one in one
    # transaction - there's no window where both or neither are held.
    appt.start_time = start
    appt.end_time = start + timedelta(minutes=settings.slot_minutes)
    _commit_or_conflict(db)
    db.refresh(appt)
    return appt


def upcoming_for_patient(db: Session, patient_id: int, now: datetime) -> list[Appointment]:
    get_patient(db, patient_id)
    return list(
        db.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status == AppointmentStatus.BOOKED,
                Appointment.start_time > now,
            )
            .order_by(Appointment.start_time)
        )
    )
