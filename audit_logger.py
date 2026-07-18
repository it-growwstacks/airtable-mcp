# audit_logger.py
# Sets up structured logging for every tool call.
# Logs who called what, when, and the outcome.
# Never logs employee personal data — only call metadata.

import os
import logging
import structlog
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── Create the audit_logs directory if it does not exist ──────────────
# Use absolute path so the folder is always created in the project directory
# regardless of which directory Claude Desktop launches the server from
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_AUDIT_LOG_DIR = os.path.join(_PROJECT_DIR, "audit_logs")
os.makedirs(_AUDIT_LOG_DIR, exist_ok=True)

# ── Configure structlog ───────────────────────────────────────────────
# This runs once at import time and configures the entire logging pipeline.

logging.basicConfig(
    format="%(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    handlers=[
        # Write to console so you can see calls in the terminal
        logging.StreamHandler(),
        # Write to a rotating log file in the audit_logs folder
        logging.FileHandler(
            os.path.join(_AUDIT_LOG_DIR, f"audit_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"),
            encoding="utf-8"
        ),
    ]
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

# ── The logger every other file imports ──────────────────────────────
logger = structlog.get_logger("workwitness-mcp")


# ── Helper functions used by tool handlers ───────────────────────────

def log_tool_call(api_key: str, tool: str, inputs: dict, outcome: str, duration_ms: int):
    """
    Logs one completed tool call.
    Called at the end of every tool handler — success or failure.

    api_key    : first 8 chars only — enough to identify, not enough to steal
    tool       : name of the tool that was called
    inputs     : sanitised input parameters (no PII values, just keys)
    outcome    : "success" or the error code string
    duration_ms: how long the full call took in milliseconds
    """
    logger.info(
        "tool_call",
        api_key=api_key[:8] + "...",      # never log the full key
        tool=tool,
        input_keys=list(inputs.keys()),   # log parameter names, not values
        outcome=outcome,
        duration_ms=duration_ms,
    )


def log_auth_failure(reason: str, raw_key_prefix: str = ""):
    """
    Logs a failed authentication attempt.
    Called by auth.py when a request is rejected.
    """
    logger.warning(
        "auth_failure",
        reason=reason,
        key_prefix=raw_key_prefix[:4] + "..." if raw_key_prefix else "none",
    )


def log_rate_limit(api_key: str):
    """
    Logs when a caller exceeds their rate limit.
    Called by rate_limiter.py.
    """
    logger.warning(
        "rate_limited",
        api_key=api_key[:8] + "...",
    )