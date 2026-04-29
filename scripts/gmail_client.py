import base64
import logging
import os
from typing import Optional

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/spreadsheets',
]


class GmailAuthError(Exception):
    pass


class LabelNotFoundError(Exception):
    pass


class GmailClient:
    """Wraps Gmail API for reading job alert emails by label."""

    def __init__(self, creds_path: str, token_path: str, label_name: str) -> None:
        self._creds_path = creds_path
        self._token_path = token_path
        self.label_name = label_name
        self.service = None
        self.credentials: Optional[Credentials] = None
        self._label_id: Optional[str] = None

    def authenticate(self) -> None:
        """Load or acquire OAuth credentials and build the Gmail service."""
        creds: Optional[Credentials] = None

        if os.path.exists(self._token_path):
            try:
                creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)
            except Exception as e:
                logger.warning("Failed to load token file: %s", e)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Refreshed expired credentials")
            except Exception as e:
                logger.warning("Token refresh failed: %s — re-authenticating", e)
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(self._creds_path):
                raise GmailAuthError(f"OAuth credentials file not found: {self._creds_path}")
            flow = InstalledAppFlow.from_client_secrets_file(self._creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            logger.info("Completed OAuth flow")

        with open(self._token_path, 'w') as f:
            f.write(creds.to_json())

        self.credentials = creds
        self.service = build('gmail', 'v1', credentials=creds)
        logger.info("Gmail service ready")

    def _resolve_label_id(self) -> str:
        """Return Gmail label ID for self.label_name; caches result."""
        if self._label_id:
            return self._label_id
        result = self.service.users().labels().list(userId='me').execute()
        for label in result.get('labels', []):
            if label['name'] == self.label_name:
                self._label_id = label['id']
                return self._label_id
        raise LabelNotFoundError(f"Gmail label not found: {self.label_name!r}")

    def get_unread_threads(self) -> list[dict]:
        """Return list of unread thread dicts for the configured label."""
        query = f"label:{self.label_name} is:unread"
        result = self.service.users().threads().list(
            userId='me', q=query, maxResults=100
        ).execute()
        threads = result.get('threads', [])
        logger.info("Found %d unread thread(s) for label %r", len(threads), self.label_name)
        return threads

    def get_thread_body(self, thread_id: str) -> str:
        """Return concatenated plain-text body for all messages in a thread."""
        thread = self.service.users().threads().get(
            userId='me', id=thread_id, format='full'
        ).execute()
        parts: list[str] = []
        for message in thread.get('messages', []):
            text = self._extract_text_from_payload(message.get('payload', {}))
            if text:
                parts.append(text)
        return "\n\n---\n\n".join(parts)

    def _extract_text_from_payload(self, payload: dict) -> str:
        mime = payload.get('mimeType', '')

        if mime == 'text/plain':
            return self._decode_body(payload.get('body', {}))
        if mime == 'text/html':
            raw = self._decode_body(payload.get('body', {}))
            return BeautifulSoup(raw, 'html.parser').get_text(separator=' ', strip=True)

        # Walk multipart tree; prefer plain parts
        children = payload.get('parts', [])
        plain = next((p for p in children if p.get('mimeType') == 'text/plain'), None)
        if plain:
            return self._decode_body(plain.get('body', {}))
        for child in children:
            text = self._extract_text_from_payload(child)
            if text:
                return text
        return ''

    def _decode_body(self, body: dict) -> str:
        data = body.get('data', '')
        if not data:
            return ''
        return base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')

    def mark_thread_read(self, thread_id: str) -> None:
        """Remove UNREAD label from a thread."""
        self.service.users().threads().modify(
            userId='me',
            id=thread_id,
            body={'removeLabelIds': ['UNREAD']},
        ).execute()
        logger.debug("Marked thread %s as read", thread_id)
