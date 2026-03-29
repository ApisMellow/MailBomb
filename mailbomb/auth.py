from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]

CONFIG_DIR = Path.home() / ".mailbomb"


def get_credentials_path():
    return CONFIG_DIR / "credentials.json"


def get_token_path():
    return CONFIG_DIR / "token.json"


def get_gmail_service(token_path=None, credentials_path=None):
    """Build and return an authenticated Gmail API service."""
    token_path = Path(token_path) if token_path else get_token_path()
    credentials_path = Path(credentials_path) if credentials_path else get_credentials_path()

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"No credentials.json found at {credentials_path}. "
                    "Run 'mailbomb setup' first."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)
