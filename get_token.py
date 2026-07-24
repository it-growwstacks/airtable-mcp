# get_token.py
# Generates a Clerk JWT for testing the Airtable-CRM-MCP server.
# Run this, copy the token, paste into Inspector's Authorization header
# (or as a Bearer token) for testing authenticated tool calls.

from clerk_backend_api import Clerk

# ── Fill these in from YOUR fresh Clerk app (the CRM one, not Sheet-MCP's) ──
CLERK_SECRET_KEY = "sk_test_cQmqorf8dtE8oOA9jgPEcTE3bBVPtxXkvRRSdn7538"      # Clerk dashboard -> API Keys -> Secret key
CLERK_USER_ID    = "user_3GfASewVpE2JESbfxUNIFZECQcs"         # Clerk dashboard -> Users -> click your test user -> copy full User ID (use the copy icon, IDs are visually truncated)
TEMPLATE_NAME    = "airtable-mcp"       # the JWT template name you created for this app

with Clerk(bearer_auth=CLERK_SECRET_KEY) as sdk:

    # Step 1 — Create a session for the test user
    print("Creating session...")
    session = sdk.sessions.create(request={"user_id": CLERK_USER_ID})
    session_id = session.id
    print(f"Session created: {session_id}")

    # Step 2 — Generate JWT from our JWT template
    print(f"Generating JWT from template '{TEMPLATE_NAME}'...")
    token_response = sdk.sessions.create_token_from_template(
        session_id=session_id,
        template_name=TEMPLATE_NAME
    )

    jwt_token = token_response.jwt

    print("\n" + "="*60)
    print("YOUR JWT TOKEN:")
    print("="*60)
    print(jwt_token)
    print("="*60)
    print("\nCopy the token above.")
    print("In Inspector: Authentication -> Custom Headers -> toggle ON the")
    print("'Authorization' row -> value: Bearer <paste token here>")
    print("Token expires quickly (often 60s) — re-run this script if you get a 401.")