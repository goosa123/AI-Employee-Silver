"""
skills/email_drafter/skill.py
Drafts a professional email reply using Claude CLI.
"""

import json
import os
import re
import subprocess

CLAUDE_MODEL   = "haiku"
CLAUDE_TIMEOUT = 60

_MAX_FROM    = 200
_MAX_SUBJECT = 300
_MAX_SNIPPET = 1200

FALLBACK = {
    "draft":  (
        "Thank you for your email. I will review your message and get back to you shortly.\n\n"
        "Best regards,\n[Your Name]"
    ),
    "reason": "draft generation failed — generic reply used",
}

PROMPT_TEMPLATE = """\
Read the email below carefully and write the most appropriate reply based on what is being asked.

Original Email:
  From:    {from_}
  Subject: {subject}
  Snippet: {snippet}

Rules:
- ALWAYS reply in the SAME LANGUAGE the sender used — if they wrote in English, reply in English; Urdu reply in Urdu; Roman Urdu reply in Roman Urdu; mixed reply in same mix
- You are writing on behalf of the EMAIL ACCOUNT OWNER — a real human person
- NEVER say "I'm Claude", "I'm an AI", "I'm an assistant", or reveal any AI identity
- NEVER make up personal details, commitments, or decisions the owner hasn't stated
- If personal info is missing (meeting time, price, decision) — write a polite holding reply:
  "I'll let you know" / "We'll discuss when we meet" / "I'll get back to you soon"
- Match the reply to the REQUEST TYPE:
    * Creative request (write a poem, song, story, lines) → actually write it, in the language/style asked
    * Information request → provide the information clearly and directly
    * Question → answer it directly
    * Work request (translate, summarize, explain, calculate) → do the work
    * Business/formal query → professional tone, short paragraphs
    * Casual friendly message → warm, natural tone matching the sender's language
- Do not refuse creative or informational requests — fulfill them
- ABSOLUTE RULE — NEVER share or include in the draft:
    * Any passwords, PINs, or login credentials
    * Windows license keys or product keys
    * VS Code settings, tokens, or API keys
    * Any sensitive account information or secret keys
    * Any files, images, documents, or data from the local computer/laptop
    * Any personal data, photos, or stored content of any kind
    * If asked for any of the above, firmly refuse — only the account owner can decide to share files or data
- Do not invent personal commitments or facts not present in the original email
- Keep it concise — no unnecessary filler
- End with a polite closing appropriate to the tone
- Leave [Your Name] placeholder only when a name signature is needed
- Output valid JSON only, no explanation outside the JSON

Format:
{{
  "draft": "<full reply text>",
  "reason": "<one sentence explaining the approach taken>"
}}"""


def _sanitize(value, max_len: int) -> str:
    """Convert to string, normalize whitespace, and trim to max_len."""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_len]


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
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    draft  = data.get("draft", "")
    reason = data.get("reason", "")

    if not isinstance(draft, str) or not draft.strip():
        return None

    if not isinstance(reason, str) or not reason.strip():
        return None

    return {"draft": draft.strip(), "reason": reason.strip()}


def draft_email_reply(email: dict) -> dict:
    """
    Draft a professional email reply using Claude CLI.

    Args:
        email: dict with keys: from, subject, snippet

    Returns:
        dict with keys: draft, reason
        Falls back to a safe generic reply if input is invalid,
        Claude fails, or output cannot be parsed.
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
