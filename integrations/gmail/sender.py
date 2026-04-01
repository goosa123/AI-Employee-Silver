"""
integrations/gmail/sender.py
Sends a reply via Gmail API and archives the original message.
"""

import base64
import logging
from email.mime.text import MIMEText

from integrations.gmail.config import USER_ID

log = logging.getLogger(__name__)


def _build_raw(to: str, subject: str, body: str) -> str:
    """Encode a plain-text reply as base64url MIME."""
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"]      = to
    msg["Subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


def send_reply(service, *, to: str, subject: str, body: str, thread_id: str) -> str:
    """
    Send a reply in the given thread.

    Returns the sent message ID.
    Raises on API error.
    """
    raw = _build_raw(to, subject, body)
    sent = service.users().messages().send(
        userId=USER_ID,
        body={"raw": raw, "threadId": thread_id},
    ).execute()
    msg_id = sent.get("id", "")
    log.info(f"SENT | to={to} | thread={thread_id} | sent_id={msg_id}")
    return msg_id


def archive_message(service, message_id: str) -> None:
    """
    Archive a message by removing the INBOX label.
    Silently skips if message_id is empty.
    """
    if not message_id:
        return
    service.users().messages().modify(
        userId=USER_ID,
        id=message_id,
        body={"removeLabelIds": ["INBOX"]},
    ).execute()
    log.info(f"ARCHIVED | message_id={message_id}")
