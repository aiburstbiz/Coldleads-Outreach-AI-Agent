"""
gmail_auth.py
Handles OAuth2 flow for Gmail API.
First run: opens browser for login and saves token.
Subsequent runs: uses saved token, refreshes automatically.
"""
import os
import json
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

CREDENTIALS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "credentials", "oauth_credentials.json"
)
TOKEN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "credentials", "token.json"
)


def get_gmail_service():
    """
    Returns an authenticated Gmail API service object, for use from the
    running server (FastAPI request handlers, LangGraph nodes, etc.).

    IMPORTANT: this function never blocks on interactive input. If there's
    no valid token and no usable refresh token, it raises RuntimeError
    immediately rather than falling into a blocking input() call — a
    hung input() inside a live web request would tie up a worker thread
    indefinitely with no human at a terminal to respond to it.

    If you see this error, run `python -m dev2_delivery.services.gmail_auth`
    from a real terminal to complete the one-time interactive OAuth setup.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise RuntimeError(
                    "Gmail refresh token is invalid or has been revoked. "
                    "Re-run the interactive OAuth setup: "
                    "python -m dev2_delivery.services.gmail_auth"
                ) from e
        else:
            raise RuntimeError(
                "No valid Gmail token found and no refresh token available. "
                "Run the interactive OAuth setup first: "
                "python -m dev2_delivery.services.gmail_auth"
            )

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def run_interactive_auth_setup():
    """
    One-time interactive OAuth setup — run this directly from a terminal
    (not imported/called from the server) to create or replace token.json.
    Usage: python -m dev2_delivery.services.gmail_auth
    """
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")

    print("\n--- AUTHORIZATION REQUIRED ---")
    print("Open this URL in your browser:")
    print(auth_url)
    print("------------------------------")
    code = input("Paste the authorization code here: ").strip()
    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print(f"\nToken saved to {TOKEN_PATH}. Auth OK.")


if __name__ == "__main__":
    run_interactive_auth_setup()