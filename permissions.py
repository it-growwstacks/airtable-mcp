# permissions.py
# Layer 3.5 — Permission Lookup
#
# Reads the Permissions table (same base, same read-only PAT as
# airtable_client.py). This module NEVER writes to Airtable — rows
# are managed by hand in the Airtable UI, not through this server.
#
# Fail-CLOSED by design: if a caller's clerk_user_id is not found in
# this table, or is marked inactive, access is denied. An unknown
# user must never silently default to full access.

import os
import requests
from dotenv import load_dotenv
from error_codes import Errors

load_dotenv()

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
TABLE_PERMISSIONS = os.environ.get("AIRTABLE_TABLE_PERMISSIONS", "Permissions")

_API_ROOT = f"https://api.airtable.com/v0/{BASE_ID}"


class PermissionError(Exception):
    def __init__(self, error, message: str | None = None):
        self.error = error
        self.message = message or error.message
        super().__init__(self.message)


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}"}


def _fetch_all_permission_rows() -> list:
    records = []
    offset = None
    url = f"{_API_ROOT}/{requests.utils.quote(TABLE_PERMISSIONS)}"

    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        except requests.exceptions.RequestException as e:
            raise PermissionError(Errors.AIRTABLE_UNAVAILABLE, f"Could not reach Airtable: {e}")

        if resp.status_code != 200:
            raise PermissionError(Errors.AIRTABLE_UNAVAILABLE, f"Permissions lookup failed: {resp.status_code}")

        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    return records


def get_permissions_for_user(clerk_user_id: str) -> dict | None:
    rows = _fetch_all_permission_rows()
    print(f"DEBUG: looking for clerk_user_id={clerk_user_id!r}", flush=True)
    for rec in rows:
        fields = rec.get("fields", {})
        row_id = str(fields.get("clerk_user_id", "")).strip()
        print(f"DEBUG: comparing against row clerk_user_id={row_id!r}, active={fields.get('active')}", flush=True)
        if row_id == clerk_user_id.strip():
            if not fields.get("active", False):
                print("DEBUG: matched but marked inactive", flush=True)
                return None
            allowed_raw = fields.get("allowed_tools", "")
            print(f"DEBUG: allowed_tools raw value={allowed_raw!r}", flush=True)
            allowed_tools = {t.strip() for t in allowed_raw.split(",") if t.strip()}
            print(f"DEBUG: parsed allowed_tools={allowed_tools!r}", flush=True)
            return {
                "role": fields.get("role", "viewer"),
                "allowed_tools": allowed_tools,
            }
    print("DEBUG: no matching row found", flush=True)
    return None


def check_tool_permission(clerk_user_id: str, tool_name: str) -> dict:
    """
    Raises PermissionError (403) if this user cannot use this tool.
    Returns the permission dict if allowed.
    """
    perms = get_permissions_for_user(clerk_user_id)
    if perms is None:
        raise PermissionError(
            Errors.FORBIDDEN,
            message="Your account is not provisioned for this server. Contact an admin."
        )
    if tool_name not in perms["allowed_tools"]:
        raise PermissionError(
            Errors.FORBIDDEN,
            message=f"You do not have permission to use '{tool_name}'."
        )
    return perms