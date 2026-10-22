"""seed the clinic's 5 doctors, their working hours, and two demo patients

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence
from datetime import time

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MON_FRI = range(0, 5)

DOCTORS = [
    # (id, name, specialty, [(weekdays, start, end), ...])
    (1, "Dr. Amina Odhiambo", "General Practice",
     [(MON_FRI, time(8, 0), time(13, 0)), (MON_FRI, time(14, 0), time(17, 0))]),
    (2, "Dr. Brian Kamau", "Paediatrics",
     [(MON_FRI, time(9, 0), time(12, 30)), (MON_FRI, time(13, 30), time(17, 0))]),
    (3, "Dr. Cynthia Wanjiru", "Dermatology",
     [((0, 2, 4), time(10, 0), time(16, 0))]),
    (4, "Dr. David Mutua", "Cardiology",
     [((1, 3), time(8, 0), time(12, 0)), ((5,), time(9, 0), time(13, 0))]),
    (5, "Dr. Esther Njeri", "Gynaecology",
     [(MON_FRI, time(12, 0), time(18, 0))]),
]

PATIENTS = [
    (1, "Demo Patient One", "patient1@example.com", "+254700000001"),
    (2, "Demo Patient Two", "patient2@example.com", "+254700000002"),
]


def upgrade() -> None:
    doctors = sa.table("doctors", sa.column("id"), sa.column("name"), sa.column("specialty"))
    hours = sa.table("working_hours", sa.column("doctor_id"), sa.column("weekday"),
                     sa.column("start_time"), sa.column("end_time"))
    patients = sa.table("patients", sa.column("id"), sa.column("name"), sa.column("email"), sa.column("phone"))

    op.bulk_insert(doctors, [{"id": i, "name": n, "specialty": s} for i, n, s, _ in DOCTORS])
    op.bulk_insert(hours, [
        {"doctor_id": i, "weekday": d, "start_time": start, "end_time": end}
        for i, _, _, blocks in DOCTORS
        for days, start, end in blocks
        for d in days
    ])
    op.bulk_insert(patients, [{"id": i, "name": n, "email": e, "phone": p} for i, n, e, p in PATIENTS])

    # Explicit ids above don't advance the serial sequences; fix them so
    # the next INSERT doesn't collide with id 1.
    for table in ("doctors", "patients"):
        op.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")


def downgrade() -> None:
    op.execute("DELETE FROM appointments WHERE doctor_id BETWEEN 1 AND 5 OR patient_id IN (1, 2)")
    op.execute("DELETE FROM patients WHERE id IN (1, 2)")
    op.execute("DELETE FROM doctors WHERE id BETWEEN 1 AND 5")
