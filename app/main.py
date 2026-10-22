from fastapi import FastAPI
from sqlalchemy import text

from app.db import engine
from app.errors import register_error_handlers
from app.routers import appointments, doctors, patients

app = FastAPI(
    title="Clinic Booking API",
    version="1.0.0",
    description="Book, cancel and reschedule 30-minute appointments with clinic doctors.",
)
register_error_handlers(app)
app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(appointments.router)


@app.get("/health", tags=["meta"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return {"name": app.title, "docs": "/docs"}
