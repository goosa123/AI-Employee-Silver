"""
scripts/linkedin_auth.py
One-time LinkedIn OAuth2 token generator.
Run this once: python scripts/linkedin_auth.py
It will open your browser, you log in, and the token is saved to credentials/linkedin_token.json
"""

import sys
import json
import os
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CLIENT_ID     = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback")
TOKEN_FILE    = BASE_DIR / "credentials" / "linkedin_token.json"

SCOPES = ["openid", "profile", "email", "w_member_social"]

AUTH_URL  = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


# ---------------------------------------------------------------------------
# Local callback server
# ---------------------------------------------------------------------------

_auth_code = None

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Auth complete! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Error: no code received.</h2>")

    def log_message(self, *args):
        pass  # suppress server logs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET not found in .env")
        sys.exit(1)

    state = secrets.token_urlsafe(16)

    auth_params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "state":         state,
        "scope":         " ".join(SCOPES),
    }

    url = AUTH_URL + "?" + urlencode(auth_params)
    print(f"\nOpening browser for LinkedIn login...")
    print(f"If browser doesn't open, paste this URL manually:\n{url}\n")
    webbrowser.open(url)

    # Start local server to catch callback
    server = HTTPServer(("localhost", 8080), _CallbackHandler)
    print("Waiting for LinkedIn callback on http://localhost:8080 ...")
    server.handle_request()

    if not _auth_code:
        print("ERROR: No auth code received.")
        sys.exit(1)

    print("Auth code received. Fetching access token...")

    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          _auth_code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })

    if resp.status_code != 200:
        print(f"ERROR: Token request failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    token_data["saved_at"] = datetime.now(timezone.utc).isoformat()

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    print(f"\nToken saved to: {TOKEN_FILE}")
    print(f"Expires in: {token_data.get('expires_in', '?')} seconds (~60 days)")
    print("\nLinkedIn auth complete!")


if __name__ == "__main__":
    main()
