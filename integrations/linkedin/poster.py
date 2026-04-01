"""
integrations/linkedin/poster.py
Posts a text update to LinkedIn using the member's access token.
Token must be generated first via: python scripts/linkedin_auth.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR   = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = BASE_DIR / "credentials" / "linkedin_token.json"

load_dotenv(BASE_DIR / ".env")

log = logging.getLogger(__name__)

API_ME   = "https://api.linkedin.com/v2/userinfo"
API_POST = "https://api.linkedin.com/v2/ugcPosts"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _load_token() -> str:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"LinkedIn token not found at {TOKEN_FILE}. "
            "Run: python scripts/linkedin_auth.py"
        )
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    token = data.get("access_token")
    if not token:
        raise ValueError("access_token missing from token file. Re-run linkedin_auth.py")
    return token


def _get_member_urn(token: str) -> str:
    """Fetch the authenticated member's URN (urn:li:person:XXXXX)."""
    resp = requests.get(
        API_ME,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch member info ({resp.status_code}): {resp.text}")
    sub = resp.json().get("sub")
    if not sub:
        raise RuntimeError("Could not retrieve member sub from userinfo endpoint.")
    return f"urn:li:person:{sub}"


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

def post_to_linkedin(text: str) -> dict:
    """
    Post text content to LinkedIn on behalf of the authenticated member.

    Args:
        text: The full post text including hashtags.

    Returns:
        dict with keys: success (bool), post_id (str or None), error (str or None)
    """
    try:
        token      = _load_token()
        member_urn = _get_member_urn(token)
    except Exception as e:
        log.error(f"AUTH_ERROR | reason={e}")
        return {"success": False, "post_id": None, "error": str(e)}

    payload = {
        "author": member_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    try:
        resp = requests.post(
            API_POST,
            headers={
                "Authorization":  f"Bearer {token}",
                "Content-Type":   "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=payload,
            timeout=15,
        )
    except Exception as e:
        log.error(f"POST_REQUEST_ERROR | reason={e}")
        return {"success": False, "post_id": None, "error": str(e)}

    if resp.status_code in (200, 201):
        post_id = resp.headers.get("x-restli-id") or resp.json().get("id", "unknown")
        log.info(f"POST_SUCCESS | post_id={post_id}")
        return {"success": True, "post_id": post_id, "error": None}
    else:
        log.error(f"POST_FAILED | status={resp.status_code} | body={resp.text}")
        return {"success": False, "post_id": None, "error": f"{resp.status_code}: {resp.text}"}
