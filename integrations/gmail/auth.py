"""
integrations/gmail/auth.py
Handles Gmail OAuth2 authentication and returns a ready API service object.
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from integrations.gmail.config import (
    CLIENT_SECRET_FILE,
    TOKEN_FILE,
    SCOPES,
    API_SERVICE_NAME,
    API_VERSION,
    ensure_gmail_dirs,
)


def get_gmail_service():
    """
    Authenticate with Gmail API and return a service object.

    Flow:
      1. Ensure all required directories exist.
      2. Raise FileNotFoundError if gmail_credentials.json is missing.
      3. Load gmail_token.json if present.
      4. Refresh expired token if a refresh token is available.
      5. Run local OAuth browser flow if no valid token exists.
      6. Save token back to gmail_token.json.
      7. Return authenticated Gmail API service.
    """
    ensure_gmail_dirs()

    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"Gmail credentials file not found: {CLIENT_SECRET_FILE}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials "
            "and save it to the credentials/ folder."
        )

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE), SCOPES
        )
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)
