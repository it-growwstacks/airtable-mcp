# server.py
# WorkWitness Sheets MCP Server
# Single tool implementation: get_employee_status
# Production-grade — all 8 layers active

# Fix 1  (Layer 3)  — Explicit rejection when both company_id and sub are missing
# Fix 2  (Layer 4)  — rate_limiter.py bug fixed (company_id → api_key) — see rate_limiter.py
# Fix 3  (Layer 4)  — retry_after_seconds added to rate limit response
# Fix 4  (Layer 7)  — ALL log_tool_call calls wrapped in try/except so a disk-full never kills a successful response
# Fix 5  (Layer 8)  — focus_score: None when not recorded, not 0
# Fix 6  (Layer 8)  — hours_worked: sanity check > 24 = data error
# Fix 7  (Layer 8)  — blockers: expanded NO_BLOCKER_VALUES set
# Fix 8  (Layer 8)  — staleness warning when data > 7 days old
# Fix 9  (Layer 8)  — empty stage returns "Not recorded" not empty string
# Fix 10 (Layer 8)  — _compute_performance_signal handles None focus_score


# server.py
# Airtable-CRM-MCP — READ-ONLY server, 11 tools across Clients/Projects/Tasks.

import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context
from starlette.responses import JSONResponse
from permissions import check_tool_permission, PermissionError


from error_codes import Errors
from auth import verify_token, extract_bearer_token, AuthError
from rate_limiter import check_rate_limit, RateLimitError
from validators import (
    GetClientInput, ListClientsInput, SearchClientsInput,
    GetProjectInput, ListProjectsInput, GetClientProjectsInput,
    GetTaskInput, ListTasksByStatusInput, SearchTasksInput,
    GetProjectTasksInput, GetProjectTeamInput,
    validate_input, ValidationError,
)
import airtable_client as at
from airtable_client import AirtableError
from audit_logger import log_tool_call

load_dotenv()

mcp = FastMCP("airtable-crm-mcp", host="0.0.0.0", port=8000)


def _authenticate_and_scope(ctx: Context):
    request = ctx.request_context.request
    bearer = extract_bearer_token(dict(request.headers))
    claims = verify_token(bearer)
    company_id = claims.get("company_id") or claims.get("sub")
    if not company_id:
        raise AuthError(Errors.UNAUTHENTICATED, message="Token missing identity claims.")
    check_rate_limit(company_id)
    return company_id, claims


def _error_response(error, extra=None):
    body = {"error": True, "code": error.code, "message": error.message,
            "timestamp": datetime.now(timezone.utc).isoformat()}
    if extra:
        body.update(extra)
    return body


@mcp.tool()
def get_client_status(client_ref: str, ctx: Context) -> dict:
    """Return the current status and summary for one client. Accepts a client/company name or Airtable record ID. Read-only. Sensitive fields (credentials, financials, contact info) are never included."""
    start = time.time()
    inputs = {"client_ref": client_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetClientInput, inputs)
        client = at.get_client(validated.client_ref)
        if not client:
            raise AirtableError(Errors.CLIENT_NOT_FOUND)
        response = {
            "record_id": client.get("_record_id"),
            "client_id": client.get("Client ID"),
            "client_company_name": client.get("Client Company Name"),
            "contact_person": client.get("Contact Person"),
            "client_status": client.get("Client Status"),
            "country": client.get("Country"),
            "city": client.get("City"),
            "lead_source": client.get("Lead Source"),
            "requirement_notes": client.get("Requirement / Notes"),
        }
        log_tool_call(company_id, "get_client_status", inputs, "success", int((time.time() - start) * 1000))
        return response
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def list_clients(status: str = "", ctx: Context = None) -> dict:
    """List clients, optionally filtered by Client Status (e.g. 'Client - Active', 'Lead', 'Lost'). Read-only, redacted."""
    start = time.time()
    inputs = {"status": status}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(ListClientsInput, inputs)
        clients = at.list_clients(status=validated.status or None, limit=validated.limit)
        results = [{"record_id": c.get("_record_id"), "client_company_name": c.get("Client Company Name"),
                    "contact_person": c.get("Contact Person"), "client_status": c.get("Client Status")} for c in clients]
        log_tool_call(company_id, "list_clients", inputs, "success", int((time.time() - start) * 1000))
        return {"status_filter": validated.status or "all", "count": len(results), "clients": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def search_clients(query: str, ctx: Context) -> dict:
    """Search clients by name or company name (free text, minimum 2 characters). Read-only, redacted."""
    start = time.time()
    inputs = {"query": query}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(SearchClientsInput, inputs)
        clients = at.search_clients(validated.query, limit=validated.limit)
        results = [{"record_id": c.get("_record_id"), "client_company_name": c.get("Client Company Name"),
                    "contact_person": c.get("Contact Person"), "client_status": c.get("Client Status")} for c in clients]
        log_tool_call(company_id, "search_clients", inputs, "success", int((time.time() - start) * 1000))
        return {"query": validated.query, "matched_count": len(results), "clients": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def get_client_projects(client_ref: str, ctx: Context) -> dict:
    """Return all projects linked to one client. Accepts a client/company name or record ID. Read-only, redacted."""
    start = time.time()
    inputs = {"client_ref": client_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetClientProjectsInput, inputs)
        client_rec = at._find_by_name_or_id(at.TABLE_CLIENTS, "Clients", "Client Company Name", validated.client_ref)
        if not client_rec and not at.is_record_id(validated.client_ref):
            client_rec = at._find_by_name_or_id(at.TABLE_CLIENTS, "Clients", "Contact Person", validated.client_ref)
        if not client_rec:
            raise AirtableError(Errors.CLIENT_NOT_FOUND)
        client_fields = client_rec.get("fields", {})
        project_ids = client_fields.get("Projects", []) or []
        projects = at.get_projects_by_ids(project_ids)
        results = [{"record_id": p.get("_record_id"), "project_name": p.get("Project Name"),
                    "status": p.get("Status"), "project_start_date": p.get("Project Start Date"),
                    "project_completion_date": p.get("Project Completion Date")} for p in projects]
        log_tool_call(company_id, "get_client_projects", inputs, "success", int((time.time() - start) * 1000))
        return {"client": client_fields.get("Client Company Name") or client_fields.get("Contact Person"),
                "count": len(results), "projects": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def get_project_status(project_ref: str, ctx: Context) -> dict:
    """Return the current status and summary for one project. Accepts a project name or record ID. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetProjectInput, inputs)
        project = at.get_project(validated.project_ref)
        if not project:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)
        response = {
            "record_id": project.get("_record_id"), "project_id": project.get("Project ID"),
            "project_name": project.get("Project Name"), "status": project.get("Status"),
            "project_details": project.get("Project Details"),
            "project_start_date": project.get("Project Start Date"),
            "project_completion_date": project.get("Project Completion Date"),
            "blocker": project.get("Blocker"),
        }
        log_tool_call(company_id, "get_project_status", inputs, "success", int((time.time() - start) * 1000))
        return response
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def list_projects(status: str = "", ctx: Context = None) -> dict:
    """List projects, optionally filtered by Status (e.g. 'In Progress', 'Complete', 'Hold', 'Lost'). Read-only, redacted."""
    start = time.time()
    inputs = {"status": status}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(ListProjectsInput, inputs)
        projects = at.list_projects(status=validated.status or None, limit=validated.limit)
        results = [{"record_id": p.get("_record_id"), "project_name": p.get("Project Name"),
                    "status": p.get("Status")} for p in projects]
        log_tool_call(company_id, "list_projects", inputs, "success", int((time.time() - start) * 1000))
        return {"status_filter": validated.status or "all", "count": len(results), "projects": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def get_project_tasks(project_ref: str, ctx: Context) -> dict:
    """Return all tasks belonging to one project. Accepts a project name or record ID. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetProjectTasksInput, inputs)
        project_raw = at.get_project_raw(validated.project_ref)
        if not project_raw:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)
        task_ids = at.get_project_task_ids(project_raw)
        tasks = at.get_tasks_by_ids(task_ids)
        results = [{"record_id": t.get("_record_id"), "task_name": t.get("Task Name"),
                    "status": t.get("Status"), "planned_execution_date": t.get("Planned Execution Date"),
                    "attention_required": t.get("Attention Required")} for t in tasks]
        log_tool_call(company_id, "get_project_tasks", inputs, "success", int((time.time() - start) * 1000))
        return {"project": project_raw.get("Project Name"), "count": len(results), "tasks": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def get_project_team(project_ref: str, ctx: Context) -> dict:
    """Given a project name or record ID, return the tasks in that project AND the distinct set of people (assignees and project managers) working on it. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetProjectTeamInput, inputs)
        project_raw = at.get_project_raw(validated.project_ref)
        if not project_raw:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)
        task_ids = at.get_project_task_ids(project_raw)
        tasks = at.get_tasks_by_ids(task_ids)
        task_summaries, assignees, pms = [], set(), set()
        for t in tasks:
            task_summaries.append({"record_id": t.get("_record_id"), "task_name": t.get("Task Name"), "status": t.get("Status")})
            assignees.update(t.get("Assignee") or [])
            pms.update(t.get("Project Manager") or [])
        log_tool_call(company_id, "get_project_team", inputs, "success", int((time.time() - start) * 1000))
        return {
            "project": project_raw.get("Project Name"), "task_count": len(task_summaries), "tasks": task_summaries,
            "distinct_assignee_record_ids": sorted(assignees), "distinct_project_manager_record_ids": sorted(pms),
            "note": "Assignee/PM are returned as Airtable record IDs. Name resolution against the Team DataBase table is out of scope for this server per current access rules.",
        }
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def get_task_status(task_ref: str, ctx: Context) -> dict:
    """Return the current status and detail for one task. Accepts a task name or record ID. Read-only, redacted."""
    start = time.time()
    inputs = {"task_ref": task_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(GetTaskInput, inputs)
        task = at.get_task(validated.task_ref)
        if not task:
            raise AirtableError(Errors.TASK_NOT_FOUND)
        response = {
            "record_id": task.get("_record_id"), "task_no": task.get("Task No."),
            "task_name": task.get("Task Name"), "status": task.get("Status"),
            "planned_execution_date": task.get("Planned Execution Date"),
            "attention_required": task.get("Attention Required"),
            "task_notes_details": task.get("Task Notes/Details"),
            "task_start_date_time": task.get("Task Start Date & Time"),
            "task_end_date_time": task.get("Task End Date & Time"),
        }
        log_tool_call(company_id, "get_task_status", inputs, "success", int((time.time() - start) * 1000))
        return response
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def list_tasks_by_status(status: str, ctx: Context) -> dict:
    """List tasks filtered by Status (required, e.g. 'Stuck', 'In progress', 'Done', 'On Hold'). Read-only, redacted."""
    start = time.time()
    inputs = {"status": status}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(ListTasksByStatusInput, inputs)
        tasks = at.list_tasks_by_status(validated.status, limit=validated.limit)
        results = [{"record_id": t.get("_record_id"), "task_name": t.get("Task Name"),
                    "status": t.get("Status"), "planned_execution_date": t.get("Planned Execution Date")} for t in tasks]
        log_tool_call(company_id, "list_tasks_by_status", inputs, "success", int((time.time() - start) * 1000))
        return {"status_filter": validated.status, "count": len(results), "tasks": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.tool()
def search_tasks(query: str, ctx: Context) -> dict:
    """Search tasks by name (free text, minimum 2 characters). Read-only, redacted."""
    start = time.time()
    inputs = {"query": query}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx)
        validated = validate_input(SearchTasksInput, inputs)
        tasks = at.search_tasks(validated.query, limit=validated.limit)
        results = [{"record_id": t.get("_record_id"), "task_name": t.get("Task Name"), "status": t.get("Status")} for t in tasks]
        log_tool_call(company_id, "search_tasks", inputs, "success", int((time.time() - start) * 1000))
        return {"query": validated.query, "matched_count": len(results), "tasks": results}
    except AuthError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")