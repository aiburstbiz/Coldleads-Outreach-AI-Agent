"""
gmail_auth.py
Handles OAuth2 flow for Gmail API.
First run: opens browser for login and saves token.
Subsequent runs: uses saved token, refreshes automatically.
"""
import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

CREDENTIALS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "credentials", "oauth_credentials.json"
)
TOKEN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "credentials", "token.json"
)


def get_gmail_service():
    """
    Returns an authenticated Gmail API service object.
    On first call: opens browser for OAuth consent.
    On subsequent calls: loads saved token from token.json.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
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

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)