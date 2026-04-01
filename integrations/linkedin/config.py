"""
integrations/linkedin/config.py
Single source of truth for the LinkedIn integration.
Nothing outside this file should hardcode LinkedIn-related paths or constants.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

# integrations/linkedin/config.py → .parent = linkedin/ → .parent = integrations/ → .parent = root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Vault paths
# ---------------------------------------------------------------------------

VAULT_DIR        = BASE_DIR / "vault" / "linkedin"
INTAKE_DIR       = VAULT_DIR / "intake"        # user drops brief files here
DRAFTS_DIR       = VAULT_DIR / "drafts"        # Claude-generated post drafts (.md)
PROCESSED_IDS    = VAULT_DIR / "processed_ids.txt"   # dedup by intake filename stem

PENDING_APPROVAL = BASE_DIR / "vault" / "Pending_Approval"   # shared with Gmail

# ---------------------------------------------------------------------------
# Intake settings
# ---------------------------------------------------------------------------

INTAKE_EXTENSIONS = {".md", ".json"}   # supported brief file types

# ---------------------------------------------------------------------------
# Source tag
# ---------------------------------------------------------------------------

SOURCE = "linkedin"

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_DRAFTED  = "drafted"
STATUS_PENDING  = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

# ---------------------------------------------------------------------------
# Normalized input schema field constants
#
# Both .md and .json intake files must produce a dict with these keys.
#
# Required:
#   FIELD_TOPIC       — what the post is about
#
# Optional:
#   FIELD_TONE        — professional / casual / inspirational
#   FIELD_AUDIENCE    — who the post targets
#   FIELD_KEY_POINTS  — list of bullet points to include
#   FIELD_CTA         — call to action
# ---------------------------------------------------------------------------

FIELD_TOPIC      = "topic"
FIELD_TONE       = "tone"
FIELD_AUDIENCE   = "audience"
FIELD_KEY_POINTS = "key_points"
FIELD_CTA        = "cta"

REQUIRED_FIELDS = {FIELD_TOPIC}
OPTIONAL_FIELDS = {FIELD_TONE, FIELD_AUDIENCE, FIELD_KEY_POINTS, FIELD_CTA}
ALL_FIELDS      = REQUIRED_FIELDS | OPTIONAL_FIELDS

# ---------------------------------------------------------------------------
# Directory setup  (call explicitly — never runs on import)
# ---------------------------------------------------------------------------

def ensure_linkedin_dirs() -> None:
    """Create all required LinkedIn vault directories if missing."""
    for directory in (INTAKE_DIR, DRAFTS_DIR, PENDING_APPROVAL):
        directory.mkdir(parents=True, exist_ok=True)
