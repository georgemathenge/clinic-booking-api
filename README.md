# Clinic Booking API

A REST API for a small clinic: patients see a doctor's free 30-minute slots for a day, book one, cancel it, or move it. It's built with **FastAPI + PostgreSQL**, deployed on **Render**, and tested and deployed by **GitHub Actions**.

- **Live API:** `https://<your-service>.onrender.com` &nbsp;·&nbsp; **Interactive docs:** `/docs`
- **Health check:** `/health`
- AI usage reflection: [REFLECTION.md](REFLECTION.md)

> The free Render tier sleeps after ~15 min idle, so the first request can take ~30–60 s to wake the service.

---

## Section 1 — System design

### Requirements as I read them

| Need | What it implies |
|---|---|
| 5 doctors, each with set working hours | Working hours are **data**, not code, per doctor, per weekday |
| 30-minute slots | Slots are **derived** from hours, not stored |
| See free slots for a doctor on a day | Availability = generated slots − booked − too-soon |
| Once booked, nobody else can take it | Must hold **under concurrent requests**, not just in the happy path |
| Patients can cancel | Cancelling frees the slot; keep the record for history |
| "Starting small but want to grow" | Simple now, with clear seams for more doctors, slot lengths, locations, auth |

### Data model

```
doctors                 working_hours                     patients
───────                 ─────────────                     ────────
id                      id                                id
name                    doctor_id  ──► doctors.id         name
specialty               weekday     (0=Mon … 6=Sun)       email (unique)
                        start_time  (clinic-local time)   phone
                        end_time

appointments
────────────
id
doctor_id   ──► doctors.id
patient_id  ──► patients.id
start_time, end_time       (timestamptz, stored UTC)
status                     booked | cancelled
cancellation_reason, cancelled_at
created_at, updated_at

UNIQUE (doctor_id,  start_time) WHERE status = 'booked'   ← no double-booking
UNIQUE (patient_id, start_time) WHERE status = 'booked'   ← patient can't be in two places
```

- **Working hours are blocks.** A doctor can have several blocks a day. A lunch break is just the gap between `08:00–13:00` and `14:00–17:00`, so breaks don't need their own table.
- **Slots aren't stored.** They're computed from the working hours for that weekday. Storing every slot would mean generating rows ahead of time, keeping them in sync whenever hours change, and cleaning them up. Computing them is cheap: at most a few dozen per doctor per day.
- **Appointments are the only thing written when booking.** A slot is "taken" when an appointment with `status = 'booked'` exists for that doctor and start time.

### Components

```
HTTP ──► routers/          thin: parse request, call a service, shape the response
           │
           ▼
         services/booking.py   every "is this allowed?" rule: hours, past, lead time,
           │                   taken, state transitions; maps DB conflicts to 409s
           ▼
         services/slots.py     pure functions: working hours + date → slot list
           │                   (no DB, so it's unit-tested in isolation)
           ▼
         models.py + Postgres  the constraints that make double-booking impossible
```

`errors.py` gives every failure the same JSON shape. `deps.get_now` supplies "now" as a dependency, so tests can freeze the clock.

### Key decisions

1. **The database enforces "one booking per slot", not just the application.**
   A check-then-insert in code has a race: two requests can both see the slot as free and both insert. A **partial unique index** on `(doctor_id, start_time) WHERE status='booked'` makes the second insert fail atomically, and I translate that failure into a `409 SLOT_TAKEN`. The app still checks first, but only to give a friendly error in the common case. Correctness doesn't depend on that check. `test_concurrent_bookings_only_one_wins` disables the app check and races two threads to prove the index alone holds. I also confirmed the test **fails** when the index is removed.
   *Why a partial index:* cancelled appointments stay in the table for history, and they must not block the slot.

2. **Cancelling is a soft delete, a status change.** The appointment keeps its reason and timestamp, so there's an audit trail of who cancelled what and why. The partial index means cancelled rows never block a rebooking.

3. **Rescheduling updates the appointment in place.** It runs in one transaction under a `SELECT … FOR UPDATE` row lock. The old slot is released and the new slot claimed atomically, so there's never a moment where both or neither are held. The appointment keeps its id, which suits clients and any future notifications. The new time goes through the same `_validate_slot` as a fresh booking.

4. **Time zones: store UTC, reason in clinic time.** Working hours are clinic-local times (`Africa/Nairobi`, configurable). Appointment times are `timestamptz`. The API accepts ISO-8601 with an offset (`…+03:00` or `…Z`); a time **without** an offset is read as clinic-local, since that's what a receptionist means by "10:00". Responses are always in clinic time with an explicit offset.

5. **Status codes are chosen so clients can act on them:**

   | Code | When | `error.code` |
   |---|---|---|
   | `201` | Booked | — |
   | `404` | Doctor, patient or appointment doesn't exist | `NOT_FOUND` |
   | `409` | Slot already taken (incl. lost race) | `SLOT_TAKEN` |
   | `409` | Patient already has an appointment at that time | `PATIENT_DOUBLE_BOOKED` |
   | `409` | Cancel an already-cancelled one / reschedule a cancelled one / act on a started one | `INVALID_STATE` |
   | `422` | Malformed body or query | `VALIDATION_ERROR` |
   | `422` | Outside hours, off the 30-min grid, in the past, < 60 min ahead | `INVALID_SLOT` |

   `409` means the request was valid but conflicts with the current state: retrying with a different slot may work. `422` means the request itself can never succeed. Every error body has the shape `{"error": {"code", "message", "details?"}}`.

6. **Business logic lives in services, separate from HTTP.** Services take `now` and `settings` as arguments, which makes the rules deterministic to test and reusable if a queue worker or admin tool needs them later.

### Trade-offs I considered

| Option | Chosen? | Why |
|---|---|---|
| Pre-generate a `slots` table and lock rows | No | More moving parts, and it must be regenerated whenever hours change. The partial unique index gives the same guarantee for free. |
| Postgres `EXCLUSION` constraint on `tstzrange` overlap | Not yet | It's the right tool once slot lengths vary (e.g. 60-min consults overlapping 30-min ones). With a fixed 30-min grid, equal start times already mean overlap, so a unique index is simpler. **This is the first thing I'd change if variable-length appointments arrive.** |
| Hard-delete on cancel | No | It loses history, and you can't report on cancellation reasons. |
| Reschedule = cancel + create new | No | Two rows for one visit, a changed id, and an extra failure mode in between. |
| Sync SQLAlchemy vs async | Sync | The workload is tiny and sync code is simpler to reason about with transactions and locks. FastAPI runs sync endpoints in a threadpool. |
| Auth | Out of scope | See *Assumptions*. It's the biggest gap before real use. |

### How it grows

- **More doctors:** no code change; they're rows. Availability is per doctor per day, so it's a bounded query. `appointments(doctor_id, start_time)` is indexed by the unique index.
- **Exceptions to the weekly schedule** (leave, holidays, one-off extra clinics): add a `schedule_exceptions(doctor_id, date, start, end, kind)` table and apply it in `generate_slots`. Nothing else changes.
- **Different slot lengths per doctor or service:** move `slot_minutes` onto the doctor or appointment type, and switch the unique index to an exclusion constraint on time ranges.
- **Multiple clinics or time zones:** move `timezone` from global settings onto a `clinic`/`location` row that doctors belong to.
- **Notifications or reminders:** the service layer is the single place where state changes, so emitting an event there, or adding an outbox table, is a contained change.
- **Read load:** availability could be cached per (doctor, date) and invalidated on book, cancel or reschedule. It isn't needed at this size.

### Assumptions (where the brief was ambiguous)

- **Clinic time zone** is `Africa/Nairobi` (the company's location). It's configurable via `CLINIC_TIMEZONE`.
- **Slots are anchored to each working block's start** and must fit entirely inside it. A block of `09:00–10:45` offers 09:00, 09:30 and 10:00, not 10:30.
- **"Not in the past" and "≥ 1 hour ahead"** (the bonus) are both enforced, with separate error messages. The lead time is configurable via `MIN_BOOKING_LEAD_MINUTES`. Availability hides slots inside the lead window, so the list only ever shows what you can actually book.
- **Availability for a past date or a day off** returns `200` with an empty `slots` list rather than an error. Asking is valid; the answer is "nothing".
- **Cancelling needs a non-empty reason** (the brief says "with a reason").
- **You can't cancel or reschedule an appointment that has already started.** It's history by then.
- **Rescheduling keeps the same doctor.** Changing doctors is a new booking.
- **Rescheduling to the slot it already occupies** is a `422` rather than a silent no-op, so the client learns nothing changed.
- **A patient can't hold two bookings at the same time**, even with different doctors.
- **No authentication.** `patient_id` is passed in the body, so anyone can cancel anyone's appointment. In production, the patient would come from the auth token and cancel/reschedule would check ownership. I left this out to stay within scope, and I'm stating it plainly rather than half-building it.
- **Seed data:** a migration creates 5 doctors with varied schedules (including lunch breaks, part-time days and a Saturday clinic) and 2 demo patients, so the deployed API can be tried immediately.

---

## Section 2 — API

Full interactive docs are at **`/docs`** (Swagger) and `/redoc`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/doctors` | List doctors with their working hours |
| `GET` | `/doctors/{id}` | One doctor |
| `GET` | `/doctors/{id}/availability?date=YYYY-MM-DD` | Free, bookable 30-min slots that day |
| `POST` | `/patients` | Register a patient |
| `GET` | `/patients/{id}` | One patient |
| `GET` | `/patients/{id}/appointments` | **Bonus:** upcoming booked appointments, soonest first |
| `POST` | `/appointments` | Book a slot |
| `GET` | `/appointments/{id}` | One appointment |
| `PATCH` | `/appointments/{id}/cancel` | Cancel with a reason |
| `PATCH` | `/appointments/{id}/reschedule` | Move to a new slot |
| `GET` | `/health` | Liveness and DB connectivity |

### Example

```bash
BASE=http://localhost:8000          # or the live URL

curl "$BASE/doctors/1/availability?date=2026-10-26"

curl -X POST $BASE/appointments -H 'content-type: application/json' \
  -d '{"doctor_id": 1, "patient_id": 1, "start_time": "2026-10-26T10:00:00+03:00"}'
# 201 {"id": 1, "status": "booked", "start_time": "2026-10-26T10:00:00+03:00", ...}

# Same slot again:
# 409 {"error": {"code": "SLOT_TAKEN", "message": "This slot is already booked"}}

curl -X PATCH $BASE/appointments/1/reschedule -H 'content-type: application/json' \
  -d '{"start_time": "2026-10-26T11:30:00+03:00"}'

curl -X PATCH $BASE/appointments/1/cancel -H 'content-type: application/json' \
  -d '{"reason": "Feeling better"}'
```

### Project layout

```
app/
  main.py              app factory, router wiring, /health
  config.py            settings from env (DB URL, timezone, lead time)
  db.py                engine / session
  models.py            SQLAlchemy models + the partial unique indexes
  schemas.py           request/response models (Pydantic)
  errors.py            error types → consistent JSON error responses
  deps.py              get_now (overridable clock)
  routers/             doctors, patients, appointments (thin HTTP layer)
  services/
    slots.py           pure slot generation
    booking.py         all booking rules
alembic/versions/      0001 schema, 0002 seed doctors
tests/                 38 tests against real Postgres
```

---

## Running locally

**With Docker (one command):**

```bash
docker compose up --build
# API on http://localhost:8000/docs; migrations and seed data run on start
```

**Without Docker for the app (Postgres still in Docker):**

```bash
docker compose up -d db
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

**Tests** run against real Postgres, because the double-booking guarantee depends on a Postgres partial index and SQLite would test something different:

```bash
docker compose up -d db
docker compose exec db psql -U clinic -c "CREATE DATABASE clinic_test"   # first time only
pytest -v
```

Tests freeze "now" at Monday 2030-01-07 08:00, so they're deterministic regardless of when they run.

What's covered: slot generation (grid, partial blocks, breaks, weekdays), availability (booked slots hidden, lead time, days off, past dates), booking validation (each rejection reason, time-zone handling, the exact 1-hour boundary), double-booking (sequential and **concurrent**), patient double-booking, cancel (frees the slot, twice → 409, reason required), reschedule (frees the old slot and takes the new one, same validation, cancelled → 409, taken → 409 with the original left untouched), and the bonus patient appointments endpoint.

---

## Section 3 — Deployment & CI/CD

**Hosting:** Render runs the `Dockerfile` as a web service, backed by Render managed PostgreSQL. Both are defined in [`render.yaml`](render.yaml) (a Render Blueprint). The container runs `alembic upgrade head` before starting, so every deploy brings the schema up to date.

**Pipeline** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

| Trigger | Jobs |
|---|---|
| Any **pull request** | `test`: starts a Postgres 17 service, installs deps, checks migrations apply **up → down → up**, runs `pytest` |
| **Push to `main`** (i.e. a merged PR) | `test`, then `deploy`: calls Render's deploy hook, then polls `/health` until the new version answers |

- **`main` is the deploy branch.** Merging a PR into `main` produces a push to `main`, which runs the tests again on the merged code and deploys only if they pass.
- Render's own auto-deploy is **turned off** (`autoDeploy: false`). That way a deploy can only come from a green pipeline, never directly from a push.
- Branch protection on `main` requires the `test` check to pass before merging.
- Secrets: `RENDER_DEPLOY_HOOK_URL` is a repo secret. `APP_URL` is a repo variable used for the post-deploy health check.

**Setting it up from scratch:**
1. Render → *New* → *Blueprint* → pick this repo. That creates the web service and the database.
2. Render → service → *Settings* → *Deploy Hook* → copy the URL.
3. GitHub → *Settings* → *Secrets and variables* → *Actions*: add the secret `RENDER_DEPLOY_HOOK_URL` and the variable `APP_URL`.
4. GitHub → *Settings* → *Branches*: protect `main` and require the `test` status check.

**Known limitation:** Render's free Postgres expires after 30 days, and the free web service sleeps when idle. Both are fine for an assessment. For real use, I'd move to paid tiers or another provider.
