import enum
from datetime import datetime, time

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AppointmentStatus(str, enum.Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str | None] = mapped_column(String(120))

    working_hours: Mapped[list["WorkingHours"]] = relationship(
        back_populates="doctor",
        cascade="all, delete-orphan",
        order_by="(WorkingHours.weekday, WorkingHours.start_time)",
    )


class WorkingHours(Base):
    """A block of time a doctor works on a given weekday, in clinic-local time.

    A doctor can have several blocks per day (e.g. 08:00-13:00 and 14:00-17:00),
    which is how lunch breaks are modelled.
    """

    __tablename__ = "working_hours"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
        CheckConstraint("start_time < end_time", name="ck_working_hours_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday ... 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    doctor: Mapped[Doctor] = relationship(back_populates="working_hours")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # The core guarantee: at most one *active* booking per doctor per slot.
        # Cancelled rows are kept for history and don't block the slot.
        # Enforced by the database, so concurrent requests can't double-book.
        Index(
            "uq_appointments_doctor_slot_active",
            "doctor_id",
            "start_time",
            unique=True,
            postgresql_where="status = 'booked'",
        ),
        # A patient can't be in two appointments at the same time.
        Index(
            "uq_appointments_patient_slot_active",
            "patient_id",
            "start_time",
            unique=True,
            postgresql_where="status = 'booked'",
        ),
        CheckConstraint("start_time < end_time", name="ck_appointments_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=AppointmentStatus.BOOKED,
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()
