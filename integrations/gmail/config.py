"""
integrations/gmail/config.py
Single source of truth for the Gmail integration.
Nothing outside this file should hardcode Gmail-related paths or constants.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

# integrations/gmail/config.py  →  .parent = gmail/  →  .parent = integrations/  →  .parent = project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

CREDENTIALS_DIR   = BASE_DIR / "credentials"
CLIENT_SECRET_FILE = CREDENTIALS_DIR / "gmail_credentials.json"   # downloaded from Google Cloud Console
TOKEN_FILE         = CREDENTIALS_DIR / "gmail_token.json"          # auto-created after first OAuth login

# ---------------------------------------------------------------------------
# OAuth scopes
# read-only — no compose, no send, no modify
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",   # needed to archive (remove INBOX label)
]

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

API_SERVICE_NAME = "gmail"
API_VERSION      = "v1"
USER_ID          = "me"          # Gmail API user identifier for authenticated account

# ---------------------------------------------------------------------------
# Vault paths
# ---------------------------------------------------------------------------

VAULT_DIR        = BASE_DIR / "vault" / "gmail"
INBOX_CACHE_DIR  = VAULT_DIR / "inbox_cache"    # raw fetched emails saved as JSON
DRAFTS_DIR       = VAULT_DIR / "drafts"          # Claude-generated reply drafts (Markdown)

# ---------------------------------------------------------------------------
# Reader settings
# ---------------------------------------------------------------------------

READER_MAX_RESULTS  = 10                         # max emails fetched per run
READER_LABEL_IDS    = ["INBOX", "UNREAD"]        # Gmail labels to filter on

# ---------------------------------------------------------------------------
# Classifier labels
# ---------------------------------------------------------------------------

LABEL_REPLY_NEEDED    = "reply_needed"
LABEL_NO_REPLY_NEEDED = "no_reply_needed"
LABEL_REVIEW_NEEDED   = "review_needed"

ALL_LABELS = {LABEL_REPLY_NEEDED, LABEL_NO_REPLY_NEEDED, LABEL_REVIEW_NEEDED}

# Labels that require human approval before any action is taken
SENSITIVE_LABELS = {LABEL_REPLY_NEEDED, LABEL_REVIEW_NEEDED}

# ---------------------------------------------------------------------------
# Directory setup  (call explicitly — never runs on import)
# ---------------------------------------------------------------------------

def ensure_gmail_dirs() -> None:
    """Create all required Gmail vault and credentials directories if missing."""
    for directory in (CREDENTIALS_DIR, INBOX_CACHE_DIR, DRAFTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
