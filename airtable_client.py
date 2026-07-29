# airtable_client.py
# Layer 6 — Data Access
#
# ============================================================
# THIS SERVER IS READ-ONLY. THIS FILE MUST NEVER CONTAIN A
# create_record / update_record / delete_record FUNCTION.
# Enforcement is intentionally layered three ways:
#   1. The Airtable PAT itself must only be scoped to
#      data.records:read (+ schema.bases:read).
#   2. This file only issues HTTP GET requests to Airtable.
#   3. server.py only defines get_/list_/search_ tools.
# ============================================================
#
# Connects to the "UpLoads(MCP)" base using a Personal Access Token.
# Exposes clean, read-only functions for Clients, Projects, and Tasks.

import os
import re
import logging
import requests
from dotenv import load_dotenv
from error_codes import Errors

load_dotenv()

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
API_KEY = os.environ.get("AIRTABLE_API_KEY", "")

TABLE_CLIENTS  = os.environ.get("AIRTABLE_TABLE_CLIENTS", "1. Clients")
TABLE_PROJECTS = os.environ.get("AIRTABLE_TABLE_PROJECTS", "2. Projects")
TABLE_TASKS    = os.environ.get("AIRTABLE_TABLE_TASKS", "3. Tasks")

_API_ROOT = f"https://api.airtable.com/v0/{BASE_ID}"

_log = logging.getLogger("airtable-crm-mcp")

if not BASE_ID or not API_KEY:
    raise RuntimeError(
        "AIRTABLE_BASE_ID and AIRTABLE_API_KEY must be set. "
        "The server cannot start without Airtable configuration."
    )

_RECORD_ID_PATTERN = re.compile(r"^rec[A-Za-z0-9]{14}$")


# ── Field redaction — enforced on every response ──────────────────────
REDACTED_FIELDS = {
    "Clients": {
        "Client Credentials", "Lifetime Value (USD)", "Lifetime Value (INR)",
        "Phone No. / WhatsApp No.", "Email", "GHL Contact ID",
        "MS Teams Channel ID", "Upwork Room ID",
    },
    "Projects": {
        "Project Value", "GHL Opportunity ID",
        "Client Credentials (from Client)",
    },
    "Tasks": {
        "Hourly Rate (in USD)", "Fixed Price (in USD)", "Task Price Total (in USD)",
        "Task Price (INR)", "Net Amount Received", "Net Amount Received in INR",
        "Client Credentials (from Client Name)", "Zoho Books Invoice Link",
        "Zoho Books Invoice Number", "Each Dev Revenue Calculation (USD)",
        "Each Dev Revenue Calculation (INR)", "Platform Charges",
    },
}


def _redact(fields: dict, table_key: str) -> dict:
    blocked = REDACTED_FIELDS.get(table_key, set())
    return {k: v for k, v in fields.items() if k not in blocked}


class AirtableError(Exception):
    def __init__(self, error, message: str | None = None):
        self.error = error
        self.message = message or error.message
        super().__init__(self.message)


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}"}


def _get(url: str, params: dict | None = None) -> dict:
    """The ONLY HTTP verb used anywhere in this file: GET."""
    try:
        resp = requests.get(url, headers=_headers(), params=params or {}, timeout=10)
    except requests.exceptions.RequestException as e:
        raise AirtableError(Errors.AIRTABLE_UNAVAILABLE, f"Could not reach Airtable: {e}")

    if resp.status_code in (401, 403):
        raise AirtableError(
            Errors.AIRTABLE_UNAVAILABLE,
            "Airtable rejected our credentials. Check AIRTABLE_API_KEY and base access."
        )
    if resp.status_code == 404:
        raise AirtableError(Errors.AIRTABLE_UNAVAILABLE, "Requested table or record not found.")
    if resp.status_code != 200:
        raise AirtableError(Errors.AIRTABLE_UNAVAILABLE, f"Airtable returned status {resp.status_code}.")

    return resp.json()


def _fetch_all_records(table_name: str, extra_params: dict | None = None) -> list:
    records = []
    offset = None
    url = f"{_API_ROOT}/{requests.utils.quote(table_name)}"

    while True:
        params = dict(extra_params or {})
        params["pageSize"] = 100
        if offset:
            params["offset"] = offset

        data = _get(url, params=params)
        records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break

    return records


def _fetch_record_by_id(table_name: str, record_id: str) -> dict | None:
    url = f"{_API_ROOT}/{requests.utils.quote(table_name)}/{record_id}"
    try:
        return _get(url)
    except AirtableError as e:
        if e.error.code == "AIRTABLE_UNAVAILABLE" and "not found" in e.message.lower():
            return None
        raise


def is_record_id(value: str) -> bool:
    return bool(_RECORD_ID_PATTERN.match(value.strip()))


def _flatten(record: dict, table_key: str, redact: bool = True) -> dict:
    fields = record.get("fields", {})
    if redact:
        fields = _redact(fields, table_key)
    flat = dict(fields)
    flat["_record_id"] = record.get("id")
    return flat


def _find_by_name_or_id(table_name: str, table_key: str, primary_field: str, value: str):
    value = value.strip()

    if is_record_id(value):
        return _fetch_record_by_id(table_name, value)

    all_records = _fetch_all_records(table_name)
    value_lower = value.lower()
    for rec in all_records:
        name_value = str(rec.get("fields", {}).get(primary_field, "")).strip().lower()
        if name_value == value_lower:
            return rec

    for rec in all_records:
        name_value = str(rec.get("fields", {}).get(primary_field, "")).strip().lower()
        if value_lower in name_value:
            return rec

    return None


# ═══════════════════════════════════════════════════════════════════
# CLIENTS
# ═══════════════════════════════════════════════════════════════════

CLIENT_STATUS_VALUES = {
    "Client - Active", "Client - Active - Without Projects",
    "Client - Inactive", "Lost", "Lead",
}


def get_client(client_ref: str) -> dict | None:
    rec = _find_by_name_or_id(TABLE_CLIENTS, "Clients", "Client Company Name", client_ref)
    if not rec and not is_record_id(client_ref):
        rec = _find_by_name_or_id(TABLE_CLIENTS, "Clients", "Contact Person", client_ref)
    if not rec:
        return None
    return _flatten(rec, "Clients")


def list_clients(status: str | None = None, limit: int = 20) -> list:
    records = _fetch_all_records(TABLE_CLIENTS)
    results = []
    for rec in records:
        raw_status = rec.get("fields", {}).get("Client Status", "")
        if status and raw_status != status:
            continue
        results.append(_flatten(rec, "Clients"))
        if len(results) >= limit:
            break
    return results


def search_clients(query: str, limit: int = 10) -> list:
    query_lower = query.strip().lower()
    records = _fetch_all_records(TABLE_CLIENTS)
    results = []
    for rec in records:
        fields = rec.get("fields", {})
        haystack = " ".join([
            str(fields.get("Client Company Name", "")),
            str(fields.get("Contact Person", "")),
        ]).lower()
        if query_lower in haystack:
            results.append(_flatten(rec, "Clients"))
        if len(results) >= limit:
            break
    return results


# ═══════════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════════

PROJECT_STATUS_VALUES = {
    "Internal", "Regular", "Handover", "Upcomming", "In Progress",
    "Complete - Payment Pending", "Client Pending", "Hold", "Complete", "Lost",
}


def get_project(project_ref: str) -> dict | None:
    rec = _find_by_name_or_id(TABLE_PROJECTS, "Projects", "Project Name", project_ref)
    if not rec:
        return None
    return _flatten(rec, "Projects")


def get_project_raw(project_ref: str) -> dict | None:
    """Unredacted, internal traversal only — never return directly to a caller."""
    rec = _find_by_name_or_id(TABLE_PROJECTS, "Projects", "Project Name", project_ref)
    if not rec:
        return None
    return _flatten(rec, "Projects", redact=False)


def list_projects(status: str | None = None, limit: int = 20) -> list:
    records = _fetch_all_records(TABLE_PROJECTS)
    results = []
    for rec in records:
        raw_status = rec.get("fields", {}).get("Status", "")
        if status and raw_status != status:
            continue
        results.append(_flatten(rec, "Projects"))
        if len(results) >= limit:
            break
    return results


def get_projects_by_ids(record_ids: list) -> list:
    results = []
    for rid in record_ids:
        rec = _fetch_record_by_id(TABLE_PROJECTS, rid)
        if rec:
            results.append(_flatten(rec, "Projects"))
    return results


def get_project_task_ids(project_record_unredacted: dict) -> list:
    return project_record_unredacted.get("Tasks", []) or []


# ═══════════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════════

TASK_STATUS_VALUES = {
    "Upcoming", "Waiting to Start from Client Side", "Todo", "In progress",
    "Do Feasibility Check", "IN QA Review", "In Client Review/Waiting for Client",
    "Client Pending", "Internal Action", "Stuck", "On Hold", "Done", "Lost",
}


def get_task(task_ref: str) -> dict | None:
    rec = _find_by_name_or_id(TABLE_TASKS, "Tasks", "Task Name", task_ref)
    if not rec:
        return None
    return _flatten(rec, "Tasks")


def list_tasks_by_status(status: str, limit: int = 20) -> list:
    records = _fetch_all_records(TABLE_TASKS)
    results = []
    for rec in records:
        raw_status = rec.get("fields", {}).get("Status", "")
        if raw_status == status:
            results.append(_flatten(rec, "Tasks"))
        if len(results) >= limit:
            break
    return results


def search_tasks(query: str, limit: int = 10) -> list:
    query_lower = query.strip().lower()
    records = _fetch_all_records(TABLE_TASKS)
    results = []
    for rec in records:
        fields = rec.get("fields", {})
        haystack = str(fields.get("Task Name", "")).lower()
        if query_lower in haystack:
            results.append(_flatten(rec, "Tasks"))
        if len(results) >= limit:
            break
    return results


def get_tasks_by_ids(record_ids: list) -> list:
    results = []
    for rid in record_ids:
        rec = _fetch_record_by_id(TABLE_TASKS, rid)
        if rec:
            results.append(_flatten(rec, "Tasks"))
    return results

def get_tasks_by_ids_unredacted(record_ids: list) -> list:
    """Like get_tasks_by_ids, but returns unredacted flat dicts — used only
    internally for reading Assignee Names / PM Name, never returned raw to a caller."""
    results = []
    for rid in record_ids:
        rec = _fetch_record_by_id(TABLE_TASKS, rid)
        if rec:
            results.append(_flatten(rec, "Tasks", redact=False))
    return results

def find_projects_by_person(person_name: str) -> list:
    """
    Given an assignee or project manager's name (case-insensitive, fuzzy
    match), returns the distinct set of Project record IDs they appear on,
    found by scanning Tasks' Assignee Names / PM Name lookup fields.
    """
    person_lower = person_name.strip().lower()
    all_tasks = _fetch_all_records(TABLE_TASKS)

    matched_project_ids = set()
    for rec in all_tasks:
        fields = rec.get("fields", {})
        assignee_names = fields.get("Assignee Names", []) or []
        pm_names = fields.get("PM Name", []) or []
        all_names = assignee_names + pm_names

        is_match = any(
            person_lower == n.strip().lower()
            or person_lower in n.strip().lower()
            or _fuzzy_match(person_lower, n)
            for n in all_names if n
        )
        if is_match:
            project_ids = fields.get("Project", []) or []
            matched_project_ids.update(project_ids)

    return list(matched_project_ids)

def validate_schema() -> None:
    checks = [
        (TABLE_CLIENTS, "Clients", {"Client Company Name", "Contact Person", "Client Status", "Projects"}),
        (TABLE_PROJECTS, "Projects", {"Project Name", "Status", "Client", "Tasks"}),
        (TABLE_TASKS, "Tasks", {"Task Name", "Status", "Project", "Client Name"}),
    ]
    for table_name, table_key, required in checks:
        try:
            records = _fetch_all_records(table_name, extra_params={"maxRecords": 1})
            if records:
                present = set(records[0].get("fields", {}).keys())
                missing = required - present
                if missing:
                    _log.warning(f"SCHEMA WARNING: {table_key} table missing expected columns: {missing}")
        except Exception as e:
            _log.warning(f"SCHEMA WARNING: could not validate {table_key} schema at startup: {e}")


validate_schema()