from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """A business-rule failure that maps to a specific HTTP status.

    Every error response has the same shape:
        {"error": {"code": "SLOT_TAKEN", "message": "...", "details": ...}}
    so clients can branch on `code` and show `message` to users.
    """

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: object | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class InvalidSlot(AppError):
    """The requested time can never be booked (outside hours, misaligned, past...)."""

    status_code = 422
    code = "INVALID_SLOT"


class SlotTaken(AppError):
    status_code = 409
    code = "SLOT_TAKEN"


class PatientDoubleBooked(AppError):
    status_code = 409
    code = "PATIENT_DOUBLE_BOOKED"


class InvalidState(AppError):
    """The appointment's current state doesn't allow the operation."""

    status_code = 409
    code = "INVALID_STATE"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


def _body(code: str, message: str, details: object | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(_body("VALIDATION_ERROR", "Request validation failed", details)),
        )
