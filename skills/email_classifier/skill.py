"""
skills/email_classifier/skill.py
Classifies a single email using Claude CLI.
"""

import json
import os
import re
import subprocess

CLAUDE_MODEL   = "haiku"
CLAUDE_TIMEOUT = 60

VALID_CATEGORIES = {"reply_needed", "no_reply_needed", "review_needed", "auto_reply"}

FALLBACK = {"category": "review_needed", "reason": "classification failed"}

# Maximum character length for each sanitized field sent to Claude
_MAX_FROM    = 200
_MAX_SUBJECT = 300
_MAX_SNIPPET = 500

PROMPT_TEMPLATE = """\
Classify the following email into exactly one of these categories:

- no_reply_needed : ANY of these apply:
    * sender address contains noreply, no-reply, donotreply, mailer-daemon, or automated@
    * subject/snippet contains: newsletter, unsubscribe, notification, receipt,
      order confirmed, otp, verification code, shipping update, auto-reply
    * email is promotional content, advertisement, offer, discount, limited time deal,
      cold outreach selling a product or service, or bulk marketing message

- auto_reply : sender is asking for creative content or a task that AI can fully complete
    on its own WITHOUT needing personal input from the recipient. Examples in ANY language:
    * write a story, poem, song, lyrics, lines, paragraph
    * write a sales pitch, cover letter, bio, caption, post
    * translate something, summarize something, explain something
    * write code, a script, an essay, a joke
    * any creative writing or content generation request
    NOTE: if the request is about scheduling, deals, meetings, or needs personal
    information from the recipient — do NOT use auto_reply

- review_needed : ANY of these apply:
    * questions about timing, meetings, deals, calls (e.g. "kab baat hogi", "when is the deal")
    * sender asks for personal data, files, credentials, or decisions only recipient can make
    * subject/snippet contains: urgent, asap, payment, transfer, bank, wire, invoice,
      contract, agreement, terms, sign, important client, key client, vip, deal, proposal
    * intent is unclear or ambiguous

- reply_needed : sender expects a simple direct response (greeting, thank you, confirmation)
    and none of the above categories apply

Rule order: no_reply_needed → auto_reply → review_needed → reply_needed
When in doubt, choose review_needed.

Email:
  From:    {from_}
  Subject: {subject}
  Snippet: {snippet}

Respond with valid JSON only. No explanation outside the JSON.
Format:
{{
  "category": "<reply_needed | no_reply_needed | review_needed>",
  "reason": "<one short sentence>"
}}"""


def _sanitize(value, max_len: int) -> str:
    """Convert to string, normalize whitespace, and trim to max_len."""
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value[:max_len]


def _call_claude(prompt: str) -> str | None:
    """Run Claude CLI and return stdout, or None on any failure."""
    try:
        env = {**os.environ, "BROWSER": "", "CLAUDE_NO_BROWSER": "1"}
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", CLAUDE_MODEL, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None
    except Exception:
        return None


def _parse_response(raw: str) -> dict | None:
    """
    Extract and validate JSON from Claude's response.
    Returns dict if valid, None otherwise.
    """
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    category = data.get("category", "")
    reason   = data.get("reason", "")

    if category not in VALID_CATEGORIES:
        return None

    if not isinstance(reason, str) or not reason.strip():
        return None

    return {"category": category, "reason": reason.strip()}


def classify_email(email: dict) -> dict:
    """
    Classify a single email using Claude CLI.

    Args:
        email: dict with keys: from, subject, snippet

    Returns:
        dict with keys: category, reason
        Falls back to review_needed if input is invalid, Claude fails,
        or Claude returns invalid output.
    """
    if not isinstance(email, dict):
        return FALLBACK.copy()

    prompt = PROMPT_TEMPLATE.format(
        from_=_sanitize(email.get("from", ""),    _MAX_FROM),
        subject=_sanitize(email.get("subject", ""), _MAX_SUBJECT),
        snippet=_sanitize(email.get("snippet", ""), _MAX_SNIPPET),
    )

    raw = _call_claude(prompt)
    if raw is None:
        return FALLBACK.copy()

    result = _parse_response(raw)
    if result is None:
        return FALLBACK.copy()

    return result
