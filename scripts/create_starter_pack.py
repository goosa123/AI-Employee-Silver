"""
scripts/create_starter_pack.py
Creates a clean starter pack of AI-Employee-Silver on the Desktop.
Removes all auth tokens, PID files, pycache, logs — keeps full code + structure.
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime

SRC  = Path(__file__).resolve().parent.parent
DEST = Path.home() / "Desktop" / "AI-Employee-Starter"

# Files/folders to completely skip
SKIP_NAMES = {
    "__pycache__", ".git", ".env",
}

# Specific files to skip (relative to SRC)
SKIP_FILES = {
    "credentials/gmail_token.json",
    "credentials/linkedin_token.json",
    "credentials/gmail_credentials.json",
    "vault/gmail/dev_watcher.pid",
    "vault/linkedin/dev_watcher.pid",
    "watchers/launcher.lock",
    "watchers/watcher.lock",
    "scripts/create_starter_pack.py",   # skip this script itself
}

# Vault folders to keep empty (clear contents but keep folder)
VAULT_CLEAR = {
    "vault/Inbox",
    "vault/Drop",
    "vault/Needs_Action",
    "vault/Pending_Approval",
    "vault/Approved",
    "vault/Rejected",
    "vault/Done",
    "vault/Archive",
    "vault/Plans",
    "vault/Logs",
    "vault/Dashboard",
    "vault/gmail",
    "vault/linkedin/drafts",
}


def should_skip(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in SKIP_NAMES for p in parts):
        return True
    if rel in SKIP_FILES:
        return True
    # Skip log files
    if rel.endswith(".log") or rel.endswith(".pid") or rel.endswith(".lock"):
        return True
    return False


def is_vault_clear(rel: str) -> bool:
    for folder in VAULT_CLEAR:
        if rel.startswith(folder + "/") or rel.startswith(folder + "\\"):
            # Keep the folder itself but not its contents
            remaining = rel[len(folder):].lstrip("/\\")
            if remaining:
                return True
    return False


def copy_project():
    if DEST.exists():
        print(f"Removing old: {DEST}")
        shutil.rmtree(DEST)

    print(f"Creating: {DEST}")
    DEST.mkdir(parents=True)

    copied = 0
    skipped = 0

    for src_path in SRC.rglob("*"):
        rel = str(src_path.relative_to(SRC))

        if should_skip(rel):
            skipped += 1
            continue

        if is_vault_clear(rel):
            skipped += 1
            continue

        dest_path = DEST / rel

        if src_path.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)
            copied += 1

    # Ensure all vault folders exist (even if emptied)
    for folder in VAULT_CLEAR:
        (DEST / folder).mkdir(parents=True, exist_ok=True)
        # Add .gitkeep so folder is not empty
        (DEST / folder / ".gitkeep").write_text("")

    # Ensure credentials folder exists (without tokens)
    (DEST / "credentials").mkdir(parents=True, exist_ok=True)

    # Create blank .env template
    env_template = """\
# AI Employee Starter — Environment Variables
# Fill these in before running linkedin_auth.py

LINKEDIN_CLIENT_ID=your_linkedin_client_id_here
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret_here
LINKEDIN_REDIRECT_URI=http://localhost:8080/callback
"""
    (DEST / ".env.template").write_text(env_template, encoding="utf-8")

    print(f"Copied: {copied} files | Skipped: {skipped} files")
    print(f"Done: {DEST}")
    return copied


if __name__ == "__main__":
    copy_project()
    print("\nStarter pack ready on Desktop!")
