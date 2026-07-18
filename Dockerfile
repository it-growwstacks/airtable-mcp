# Dockerfile — Sheet-MCP (workwitness-sheets-mcp)
# Packages the Streamable HTTP server for deployment (Cloudflare Container / any
# Docker host). Built against server.py after the Phase 3 transport flip —
# this container listens on 0.0.0.0:8000 over HTTP, it does not speak stdio.
#
# Secrets (.env, credentials.json) are NEVER copied into this image.
# They are injected at container run time — see "What you must supply at
# runtime" below. This keeps the image itself safe to store, share, or
# push to a registry with zero credentials inside it.

FROM python:3.12-slim AS base

# ── Non-root user ───────────────────────────────────────────────────────
# Running as root inside a container is unnecessary risk — if the process
# is ever compromised, a non-root user limits what it can touch on the
# host or inside the container filesystem. Standard production practice.
#
# Note: no build-essential / compiler toolchain here. PyJWT[crypto]'s
# cryptography dependency ships a prebuilt manylinux wheel for x86_64,
# so pip installs it as a binary — no compilation happens. If this is
# ever deployed to a non-x86_64 host (e.g. ARM) and pip falls back to
# building from source, add build-essential back in as a RUN step
# before the pip install below.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# ── Install dependencies first, code second ─────────────────────────────
# Docker caches layers. Copying requirements.txt and installing BEFORE
# copying the rest of the code means Docker only re-runs the (slow) pip
# install when requirements.txt actually changes — not on every code edit.
# This is the single biggest build-speed win in a Dockerfile like this.
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# ── Copy application code ────────────────────────────────────────────────
# Only the files the server actually imports. credentials.json and .env
# are deliberately NOT copied — see the note at the top of this file.
COPY server.py auth.py rate_limiter.py validators.py supabase_client.py \
     error_codes.py audit_logger.py ./

# audit_logs is created at runtime by audit_logger.py's os.makedirs() call,
# but we pre-create it here and hand ownership to appuser so the non-root
# user can actually write to it — without this, the first log write would
# fail with a permissions error inside the container.
RUN mkdir -p /app/audit_logs && chown -R appuser:appuser /app

USER appuser

# ── Network ───────────────────────────────────────────────────────────
# Documents that the container listens on 8000. This does not itself
# publish the port — that still happens via `docker run -p` or the
# hosting platform's own port mapping (e.g. Cloudflare Container config).
EXPOSE 8000

# ── Start the server ─────────────────────────────────────────────────
# Matches server.py's own __main__ block exactly — no flags duplicated
# here that are already set in code (host/port live in the FastMCP
# constructor in server.py, not here).
CMD ["python", "server.py"] 