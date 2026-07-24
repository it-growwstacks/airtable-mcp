# error_codes.py
# Single source of truth for every error this server can return.

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDef:
    code: str
    message: str
    http_status: int

    def __str__(self) -> str:
        return self.code


class Errors:

    # ── Client errors (caller's fault) ───────────────────────────
    EMPLOYEE_NOT_FOUND = ErrorDef(
        code="EMPLOYEE_NOT_FOUND",
        message="No employee found with that code.",
        http_status=404,
    )
    INVALID_PARAMETER = ErrorDef(
        code="INVALID_PARAMETER",
        message="One or more parameters are invalid.",
        http_status=400,
    )
    INVALID_DATE_FORMAT = ErrorDef(
        code="INVALID_DATE_FORMAT",
        message="Date must be in YYYY-MM-DD format, e.g. 2026-07-07.",
        http_status=400,
    )

    # ── Security errors ───────────────────────────────────────────
    UNAUTHENTICATED = ErrorDef(
        code="UNAUTHENTICATED",
        message="Missing or invalid API key.",
        http_status=401,
    )
    FORBIDDEN = ErrorDef(
        code="FORBIDDEN",
        message="You do not have permission to access this resource.",
        http_status=403,
    )
    RATE_LIMITED = ErrorDef(
        code="RATE_LIMITED",
        message="Too many requests. Please wait before trying again.",
        http_status=429,
    )

    # ── Server errors (our fault) ─────────────────────────────────
    INTERNAL_ERROR = ErrorDef(
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
        http_status=500,
    )

    # ── New CRM-specific errors (Clients/Projects/Tasks) ──────────
    CLIENT_NOT_FOUND = ErrorDef(
        code="CLIENT_NOT_FOUND",
        message="No client found matching that name or ID.",
        http_status=404,
    )
    PROJECT_NOT_FOUND = ErrorDef(
        code="PROJECT_NOT_FOUND",
        message="No project found matching that name or ID.",
        http_status=404,
    )
    TASK_NOT_FOUND = ErrorDef(
        code="TASK_NOT_FOUND",
        message="No task found matching that name or ID.",
        http_status=404,
    )
    AIRTABLE_UNAVAILABLE = ErrorDef(
        code="AIRTABLE_UNAVAILABLE",
        message="Could not reach the data source. Please try again shortly.",
        http_status=503,
    )