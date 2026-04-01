"""
integrations/gmail/reader.py
Fetches unread inbox messages from Gmail and saves each as JSON in inbox_cache/.
"""

import json
import re
from datetime import datetime

from integrations.gmail.auth import get_gmail_service
from integrations.gmail.config import (
    USER_ID,
    READER_MAX_RESULTS,
    READER_LABEL_IDS,
    INBOX_CACHE_DIR,
    ensure_gmail_dirs,
)


def _clean(text: str, maxlen: int = 30) -> str:
    """Slugify text for use in filenames."""
    text = re.sub(r"[^\w\s-]", "", str(text)).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:maxlen].strip("_").lower()


def _sender_name(from_str: str, maxlen: int = 15) -> str:
    """Extract display name or email prefix from From header."""
    m = re.match(r"^([^<]+)<", from_str)
    name = m.group(1).strip() if m else from_str.split("@")[0]
    return _clean(name, maxlen)


def _cache_filename(parsed: dict) -> str:
    """Build a readable cache filename: YYYY-MM-DD_sender_subject.json"""
    try:
        dt = datetime.now().strftime("%Y-%m-%d_%H-%M")
    except Exception:
        dt = "0000-00-00_00-00"
    sender  = _sender_name(parsed.get("from", "unknown"))
    subject = _clean(parsed.get("subject", "no_subject"), 35)
    return f"{dt}_{sender}_{subject}.json"


def _extract_header(headers: list[dict], name: str) -> str:
    """Return the value of a named header, or empty string if missing."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _parse_message(msg: dict) -> dict:
    """
    Extract clean fields from a raw Gmail message dict.

    Returns a flat dict with:
        message_id, thread_id, subject, from, date, snippet
    """
    headers = msg.get("payload", {}).get("headers", [])

    return {
        "message_id": msg.get("id", ""),
        "thread_id":  msg.get("threadId", ""),
        "subject":    _extract_header(headers, "Subject"),
        "from":       _extract_header(headers, "From"),
        "date":       _extract_header(headers, "Date"),
        "snippet":    msg.get("snippet", ""),
    }


def fetch_unread_inbox() -> list[dict]:
    """
    Fetch unread inbox messages from Gmail.

    Steps:
      1. Authenticate via get_gmail_service().
      2. List up to READER_MAX_RESULTS unread messages in INBOX.
      3. Fetch full metadata for each message.
      4. Parse into clean dicts.
      5. Save each to inbox_cache/<message_id>.json.
      6. Return list of parsed message dicts.
    """
    ensure_gmail_dirs()

    service = get_gmail_service()
    messages_api = service.users().messages()

    list_response = messages_api.list(
        userId=USER_ID,
        labelIds=READER_LABEL_IDS,
        maxResults=READER_MAX_RESULTS,
    ).execute()

    raw_list = list_response.get("messages", [])
    if not raw_list:
        return []

    results = []

    for ref in raw_list:
        msg_id = ref.get("id")
        if not msg_id:
            continue

        msg = messages_api.get(
            userId=USER_ID,
            id=msg_id,
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()

        parsed = _parse_message(msg)

        cache_path = INBOX_CACHE_DIR / _cache_filename(parsed)
        cache_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        results.append(parsed)

    return results
