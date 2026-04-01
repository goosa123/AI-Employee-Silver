"""
skills/linkedin_drafter/skill.py
Drafts a LinkedIn post using Claude CLI.
"""

import json
import os
import re
import subprocess

CLAUDE_MODEL   = "haiku"
CLAUDE_TIMEOUT = 60

_MAX_TOPIC      = 300
_MAX_TONE       = 100
_MAX_AUDIENCE   = 200
_MAX_KEY_POINT  = 300
_MAX_CTA        = 200
_MAX_KEY_POINTS = 10   # max number of key points accepted

FALLBACK = {
    "post":   "Excited to share some thoughts on this topic. Stay tuned for more insights.\n\n#LinkedIn #Professional",
    "reason": "post generation failed — generic placeholder used",
}

PROMPT_TEMPLATE = """\
Write a professional LinkedIn post based on the following brief.

Brief:
  Topic:      {topic}
  Tone:       {tone}
  Audience:   {audience}
  Key Points: {key_points}
  CTA:        {cta}

Rules:
- Write for LinkedIn: engaging, professional, human
- Use the tone and audience provided; default to professional if not specified
- Include the key points naturally in the post
- End with the CTA if provided
- Add 3-5 relevant hashtags at the end
- Do not add meta-commentary or explain the post
- Output valid JSON only, nothing outside the JSON

Format:
{{
  "post": "<full linkedin post text>",
  "reason": "<one sentence explaining the approach taken>"
}}"""


def _sanitize(value, max_len: int) -> str:
    """Convert to string, normalize whitespace, trim to max_len."""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_len]


def _sanitize_key_points(value) -> str:
    """Normalize key_points list or string into a readable bullet string."""
    if isinstance(value, list):
        points = [_sanitize(p, _MAX_KEY_POINT) for p in value[:_MAX_KEY_POINTS] if str(p).strip()]
        return "; ".join(points) if points else "none"
    return _sanitize(value, _MAX_KEY_POINT * _MAX_KEY_POINTS) or "none"


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
    """Extract and validate JSON from Claude's response. Returns dict or None."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    post   = data.get("post", "")
    reason = data.get("reason", "")

    if not isinstance(post, str) or not post.strip():
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None

    return {"post": post.strip(), "reason": reason.strip()}


def draft_linkedin_post(data: dict) -> dict:
    """
    Draft a LinkedIn post using Claude CLI.

    Args:
        data: dict with keys: topic (required), tone, audience, key_points, cta

    Returns:
        dict with keys: post, reason
        Falls back to a safe placeholder if input is invalid,
        Claude fails, or output cannot be parsed.
    """
    if not isinstance(data, dict):
        return FALLBACK.copy()

    topic = _sanitize(data.get("topic", ""), _MAX_TOPIC)
    if not topic:
        return FALLBACK.copy()

    prompt = PROMPT_TEMPLATE.format(
        topic=topic,
        tone=_sanitize(data.get("tone", "professional"), _MAX_TONE),
        audience=_sanitize(data.get("audience", "general professional network"), _MAX_AUDIENCE),
        key_points=_sanitize_key_points(data.get("key_points", [])),
        cta=_sanitize(data.get("cta", ""), _MAX_CTA) or "none",
    )

    raw = _call_claude(prompt)
    if raw is None:
        return FALLBACK.copy()

    result = _parse_response(raw)
    if result is None:
        return FALLBACK.copy()

    return result
