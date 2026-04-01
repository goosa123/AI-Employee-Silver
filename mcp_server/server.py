"""
mcp_server/server.py
Minimal MCP server for AI Employee Silver.
Exposes 3 tools that wrap existing project functions — no duplicate logic.

Run:
    python mcp_server/server.py
"""

import sys
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

mcp = FastMCP("AI Employee Silver")

DASHBOARD_FILE = BASE_DIR / "vault" / "Dashboard" / "dashboard.md"


# ---------------------------------------------------------------------------
# Tool 1 — Gmail: send a reply
# ---------------------------------------------------------------------------

@mcp.tool()
def gmail_send_reply(to: str, subject: str, body: str, thread_id: str) -> str:
    """
    Send an email reply via Gmail.

    Args:
        to:        Recipient email address.
        subject:   Email subject (Re: prefix added automatically if missing).
        body:      Plain-text reply body.
        thread_id: Gmail thread ID to reply into.

    Returns:
        Sent message ID on success, or an error string.
    """
    try:
        from integrations.gmail.auth import get_gmail_service
        from integrations.gmail.sender import send_reply

        service = get_gmail_service()
        sent_id = send_reply(service, to=to, subject=subject, body=body, thread_id=thread_id)
        log.info(f"gmail_send_reply | to={to} | sent_id={sent_id}")
        return f"sent:{sent_id}"
    except Exception as e:
        log.error(f"gmail_send_reply | error={e}")
        return f"error:{e}"


# ---------------------------------------------------------------------------
# Tool 2 — LinkedIn: create a post draft
# ---------------------------------------------------------------------------

@mcp.tool()
def linkedin_create_draft(
    topic: str,
    tone: str = "professional",
    audience: str = "general",
    key_points: str = "",
    cta: str = "",
) -> str:
    """
    Draft a LinkedIn post and save it to vault/Pending_Approval/ for review.

    Args:
        topic:      Main topic or subject of the post.
        tone:       Writing tone (professional, casual, inspirational).
        audience:   Target audience description.
        key_points: Comma-separated key points to include (optional).
        cta:        Call-to-action line (optional).

    Returns:
        Artifact filename on success, or an error string.
    """
    try:
        from skills.linkedin_drafter.skill import draft_linkedin_post
        from processors.linkedin_processor import _save_artifact

        brief = {
            "topic":      topic,
            "tone":       tone,
            "audience":   audience,
            "key_points": [kp.strip() for kp in key_points.split(",") if kp.strip()],
            "cta":        cta,
        }

        result        = draft_linkedin_post(brief)
        post          = result.get("post", "")
        reason        = result.get("reason", "drafted via MCP")
        artifact_path = _save_artifact(brief, post, reason, "mcp_tool")

        log.info(f"linkedin_create_draft | topic={topic} | artifact={artifact_path.name}")
        return f"saved:{artifact_path.name}"
    except Exception as e:
        log.error(f"linkedin_create_draft | error={e}")
        return f"error:{e}"


# ---------------------------------------------------------------------------
# Tool 3 — Dashboard: get current status
# ---------------------------------------------------------------------------

@mcp.tool()
def dashboard_get_status() -> str:
    """
    Return the current dashboard snapshot from vault/Dashboard/dashboard.md.

    Returns:
        Dashboard markdown content, or an error string.
    """
    try:
        if not DASHBOARD_FILE.exists():
            return "error:dashboard.md not found — run generate_dashboard.py first"
        content = DASHBOARD_FILE.read_text(encoding="utf-8")
        log.info("dashboard_get_status | ok")
        return content
    except Exception as e:
        log.error(f"dashboard_get_status | error={e}")
        return f"error:{e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(f"Starting MCP server | base_dir={BASE_DIR}")
    mcp.run()
