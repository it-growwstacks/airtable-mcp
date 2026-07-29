# server.py
# Airtable-CRM-MCP — READ-ONLY server, 9 tools across Clients/Projects/Tasks.
#
# Layers: Transport -> Auth -> Identity -> Permissions -> Rate Limit ->
# Validation -> Data Fetch -> Audit Log -> Response Shaping.
#
# READ-ONLY SERVER. No tool below may create, update, or delete any
# Airtable record. See airtable_client.py header for enforcement.
#
# Permissions (Layer 3.5): every tool call is checked against the
# Permissions table (same base, read-only). Unknown callers are denied
# by default — see permissions.py.
#
# Name lookups (client_ref, project_ref) are case-insensitive and
# fuzzy-tolerant — see airtable_client._find_by_name_or_id.

import sys
import traceback

try:
    import os
    import time
    from datetime import datetime, timezone
    from dotenv import load_dotenv
    from mcp.server.fastmcp import FastMCP, Context
    from starlette.responses import JSONResponse

    from error_codes import Errors
    from auth import verify_token, extract_bearer_token, AuthError
    from rate_limiter import check_rate_limit, RateLimitError
    from permissions import check_tool_permission, PermissionError
    from validators import (
    GetClientInput, ListClientsInput, SearchClientsInput,
    GetProjectInput, ListProjectsInput, GetClientProjectsInput,
    SearchTasksInput, GetProjectTasksInput, GetProjectTeamInput,
    GetPersonAssignmentsInput,
    validate_input, ValidationError,
    )
    import airtable_client as at
    from airtable_client import AirtableError
    from audit_logger import log_tool_call
except Exception:
    print("=== STARTUP CRASH ===", file=sys.stderr, flush=True)
    traceback.print_exc()
    sys.exit(1)

load_dotenv()

mcp = FastMCP("airtable-crm-mcp", host="0.0.0.0", port=8000)


# ── Shared request-handling helpers ───────────────────────────────────

def _authenticate_and_scope(ctx: Context, tool_name: str) -> tuple[str, dict]:
    """Runs Layers 2-3.5 (auth, identity extraction, permissions, rate limiting)."""
    request = ctx.request_context.request
    bearer = extract_bearer_token(dict(request.headers))
    claims = verify_token(bearer)

    company_id = claims.get("company_id") or claims.get("sub")
    if not company_id:
        raise AuthError(Errors.UNAUTHENTICATED, message="Token missing identity claims.")

    check_rate_limit(company_id)
    check_tool_permission(company_id, tool_name)

    return company_id, claims


def _error_response(error, extra: dict | None = None) -> dict:
    body = {
        "error": True,
        "code": error.code,
        "message": error.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        body.update(extra)
    return body


def _find_client_record(client_ref: str):
    """Resolve a client by Company Name first, then Contact Person, with fuzzy fallback."""
    rec = at._find_by_name_or_id(at.TABLE_CLIENTS, "Clients", "Client Company Name", client_ref)
    if not rec and not at.is_record_id(client_ref):
        rec = at._find_by_name_or_id(at.TABLE_CLIENTS, "Clients", "Contact Person", client_ref)
    return rec


# ═══════════════════════════════════════════════════════════════════
# CLIENT TOOLS
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_client_status(client_ref: str, ctx: Context) -> dict:
    """Return the company name and country for one client. Accepts a client/company name (case-insensitive, typo-tolerant fuzzy match) or Airtable record ID. Read-only. Sensitive fields (credentials, financials, contact info) are never included."""
    start = time.time()
    inputs = {"client_ref": client_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_client_status")
        validated = validate_input(GetClientInput, inputs)

        client_rec = _find_client_record(validated.client_ref)
        if not client_rec:
            raise AirtableError(Errors.CLIENT_NOT_FOUND)

        client = at._flatten(client_rec, "Clients")

        response = {
            "company_name": client.get("Client Company Name"),
            "country": client.get("Country"),
        }

        log_tool_call(company_id, "get_client_status", inputs, "success", int((time.time() - start) * 1000))
        return response

    except AuthError as e:
        log_tool_call(company_id, "get_client_status", inputs, e.error.code, int((time.time() - start) * 1000))
        return _error_response(e.error)
    except PermissionError as e:
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
    """List clients, optionally filtered by Client Status (e.g. 'Client - Active', 'Lead', 'Lost'). Returns company name, client name, and status. Read-only, redacted."""
    start = time.time()
    inputs = {"status": status}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "list_clients")
        validated = validate_input(ListClientsInput, inputs)

        clients = at.list_clients(status=validated.status or None, limit=validated.limit)
        results = [
            {
                "company_name": c.get("Client Company Name"),
                "client_name": c.get("Contact Person"),
                "client_status": c.get("Client Status"),
            }
            for c in clients
        ]

        log_tool_call(company_id, "list_clients", inputs, "success", int((time.time() - start) * 1000))
        return {"status_filter": validated.status or "all", "count": len(results), "clients": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
    """Search clients by name or company name — case-insensitive, supports partial and fuzzy/typo-tolerant matching (minimum 2 characters). Returns client name, company name, and associated project names. Read-only, redacted."""
    start = time.time()
    inputs = {"query": query}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "search_clients")
        validated = validate_input(SearchClientsInput, inputs)

        clients = at.search_clients(validated.query, limit=validated.limit)
        results = []
        for c in clients:
            project_ids = c.get("Projects", []) or []
            projects = at.get_projects_by_ids(project_ids)
            project_names = [p.get("Project Name") for p in projects if p.get("Project Name")]
            results.append({
                "client_name": c.get("Contact Person"),
                "company_name": c.get("Client Company Name"),
                "project_names": project_names,
            })

        log_tool_call(company_id, "search_clients", inputs, "success", int((time.time() - start) * 1000))
        return {"query": validated.query, "matched_count": len(results), "clients": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
    """Return all projects linked to one client. Accepts a client/company name (case-insensitive, fuzzy match) or record ID. Returns client name, company name, and each project's name and status. Read-only, redacted."""
    start = time.time()
    inputs = {"client_ref": client_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_client_projects")
        validated = validate_input(GetClientProjectsInput, inputs)

        client_rec = _find_client_record(validated.client_ref)
        if not client_rec:
            raise AirtableError(Errors.CLIENT_NOT_FOUND)

        client_fields = client_rec.get("fields", {})
        project_ids = client_fields.get("Projects", []) or []
        projects = at.get_projects_by_ids(project_ids)

        results = [
            {
                "project_name": p.get("Project Name"),
                "project_status": p.get("Status"),
            }
            for p in projects
        ]

        log_tool_call(company_id, "get_client_projects", inputs, "success", int((time.time() - start) * 1000))
        return {
            "client_name": client_fields.get("Contact Person"),
            "company_name": client_fields.get("Client Company Name"),
            "count": len(results),
            "projects": results,
        }

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


# ═══════════════════════════════════════════════════════════════════
# PROJECT TOOLS
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_project_status(project_ref: str, ctx: Context) -> dict:
    """Return the status and details for one project. Accepts a project name (case-insensitive, fuzzy match) or record ID. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_project_status")
        validated = validate_input(GetProjectInput, inputs)

        project = at.get_project(validated.project_ref)
        if not project:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)

        response = {
            "project_name": project.get("Project Name"),
            "project_status": project.get("Status"),
            "project_details": project.get("Project Details"),
        }

        log_tool_call(company_id, "get_project_status", inputs, "success", int((time.time() - start) * 1000))
        return response

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
def get_person_assignments(person_name: str, ctx: Context) -> dict:
    """Given an assignee or project manager's name (case-insensitive, fuzzy match), return every project they're on, each with its status and client name. Read-only, redacted."""
    start = time.time()
    inputs = {"person_name": person_name}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_person_assignments")
        validated = validate_input(GetPersonAssignmentsInput, inputs)

        project_ids = at.find_projects_by_person(validated.person_name)
        if not project_ids:
            return {"person_name": validated.person_name, "count": 0, "projects": []}

        results = []
        for pid in project_ids:
            prec = at._fetch_record_by_id(at.TABLE_PROJECTS, pid)
            if not prec:
                continue
            pfields = prec.get("fields", {})
            client_ids = pfields.get("Client", []) or []
            client_name = None
            if client_ids:
                crec = at._fetch_record_by_id(at.TABLE_CLIENTS, client_ids[0])
                if crec:
                    cf = crec.get("fields", {})
                    client_name = cf.get("Contact Person") or cf.get("Client Company Name")
            results.append({
                "project_name": pfields.get("Project Name"),
                "project_status": pfields.get("Status"),
                "client_name": client_name,
            })

        log_tool_call(company_id, "get_person_assignments", inputs, "success", int((time.time() - start) * 1000))
        return {"person_name": validated.person_name, "count": len(results), "projects": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
    """List projects, optionally filtered by Status (e.g. 'In Progress', 'Complete', 'Hold', 'Lost'). Returns project name, status, and client name. Read-only, redacted."""
    start = time.time()
    inputs = {"status": status}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "list_projects")
        validated = validate_input(ListProjectsInput, inputs)

        projects_raw = at.list_projects(status=validated.status or None, limit=validated.limit)
        results = []
        for p in projects_raw:
            client_ids = p.get("Client", []) or []
            client_names = []
            for cid in client_ids:
                crec = at._fetch_record_by_id(at.TABLE_CLIENTS, cid)
                if crec:
                    client_names.append(crec.get("fields", {}).get("Contact Person") or crec.get("fields", {}).get("Client Company Name"))
            results.append({
                "project_name": p.get("Project Name"),
                "project_status": p.get("Status"),
                "client_name": client_names[0] if client_names else None,
            })

        log_tool_call(company_id, "list_projects", inputs, "success", int((time.time() - start) * 1000))
        return {"status_filter": validated.status or "all", "count": len(results), "projects": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
    """Return all tasks belonging to one project, regardless of status. Accepts a project name (case-insensitive, fuzzy match) or record ID. Returns each task's name, status, and planned execution date. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_project_tasks")
        validated = validate_input(GetProjectTasksInput, inputs)

        project_raw = at.get_project_raw(validated.project_ref)
        if not project_raw:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)

        task_ids = at.get_project_task_ids(project_raw)
        tasks = at.get_tasks_by_ids(task_ids)

        results = [
            {
                "task_name": t.get("Task Name"),
                "status": t.get("Status"),
                "planned_execution_date": t.get("Planned Execution Date"),
            }
            for t in tasks
        ]

        log_tool_call(company_id, "get_project_tasks", inputs, "success", int((time.time() - start) * 1000))
        return {"project_name": project_raw.get("Project Name"), "count": len(results), "tasks": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
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
    """Given a project name (case-insensitive, fuzzy match) or record ID, return the project name, the names of all assignees, and the project manager's name. Names are resolved from Airtable, not record IDs. Read-only, redacted."""
    start = time.time()
    inputs = {"project_ref": project_ref}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "get_project_team")
        validated = validate_input(GetProjectTeamInput, inputs)

        project_raw = at.get_project_raw(validated.project_ref)
        if not project_raw:
            raise AirtableError(Errors.PROJECT_NOT_FOUND)

        task_ids = at.get_project_task_ids(project_raw)
        tasks_raw = at.get_tasks_by_ids_unredacted(task_ids)

        assignee_names = set()
        pm_names = set()
        for t in tasks_raw:
            for name in (t.get("Assignee Names") or []):
                if name:
                    assignee_names.add(name)
            for name in (t.get("PM Name") or []):
                if name:
                    pm_names.add(name)

        log_tool_call(company_id, "get_project_team", inputs, "success", int((time.time() - start) * 1000))
        return {
            "project_name": project_raw.get("Project Name"),
            "assignee_names": sorted(assignee_names),
            "project_manager_names": sorted(pm_names),
        }

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


# ═══════════════════════════════════════════════════════════════════
# TASK TOOLS (only search_tasks survives, unchanged)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def search_tasks(query: str, ctx: Context) -> dict:
    """Search tasks by name (free text, minimum 2 characters). Read-only, redacted."""
    start = time.time()
    inputs = {"query": query}
    company_id = "unknown"
    try:
        company_id, _ = _authenticate_and_scope(ctx, "search_tasks")
        validated = validate_input(SearchTasksInput, inputs)

        tasks = at.search_tasks(validated.query, limit=validated.limit)
        results = [
            {"record_id": t.get("_record_id"), "task_name": t.get("Task Name"), "status": t.get("Status")}
            for t in tasks
        ]

        log_tool_call(company_id, "search_tasks", inputs, "success", int((time.time() - start) * 1000))
        return {"query": validated.query, "matched_count": len(results), "tasks": results}

    except AuthError as e:
        return _error_response(e.error)
    except PermissionError as e:
        return _error_response(e.error)
    except RateLimitError as e:
        return _error_response(e.error, {"retry_after_seconds": e.retry_after})
    except ValidationError as e:
        return _error_response(e.error)
    except AirtableError as e:
        return _error_response(e.error)
    except Exception:
        return _error_response(Errors.INTERNAL_ERROR)


# ── Health check ───────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})


# ── Run ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")