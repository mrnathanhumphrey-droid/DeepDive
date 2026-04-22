"""Google Drive integration for DeepDive — uploads DOCX reports via OAuth2."""

import os
import io
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_DIR = os.path.join(os.path.dirname(__file__), "credentials")
CLIENT_SECRET_FILE = os.path.join(CREDENTIALS_DIR, "oauth_client.json")
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, "token.json")


def get_credentials():
    """Get or refresh OAuth2 credentials. Opens browser on first run."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def upload_docx_to_drive(docx_bytes: bytes, filename: str,
                          folder_id: str = None) -> dict:
    """Upload a DOCX file to Google Drive.

    Args:
        docx_bytes: The DOCX file content as bytes.
        filename: The filename to use in Drive (e.g., "deepdive_report.docx").
        folder_id: Optional Google Drive folder ID. If None, reads from env.

    Returns:
        dict with 'id', 'name', and 'webViewLink' of the created file.
    """
    if not folder_id:
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)

    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        resumable=True,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()

    return file


def is_drive_configured() -> bool:
    """Check if Google Drive integration is configured."""
    return (
        os.path.exists(CLIENT_SECRET_FILE)
        and bool(os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip())
    )


def is_drive_authenticated() -> bool:
    """Check if we already have a valid token (no browser prompt needed)."""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return True
    except Exception:
        return False
    return False
