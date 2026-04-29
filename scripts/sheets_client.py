import logging

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_HEADER_ALIASES = {'url', 'linkedin url', 'link', 'job url'}


class SheetsClient:
    """Writes job scores to a Google Sheet using shared OAuth credentials."""

    def __init__(self, credentials, sheet_id: str, sheet_name: str = "") -> None:
        self._sheet_id = sheet_id
        self.service = build('sheets', 'v4', credentials=credentials)
        if sheet_name:
            self._sheet_name = sheet_name
        else:
            meta = self.service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            self._sheet_name = meta['sheets'][0]['properties']['title']
            logger.info("Auto-detected sheet name: %r", self._sheet_name)

    def get_existing_urls(self) -> set[str]:
        """Return set of URLs already in column E to prevent duplicate writes."""
        range_name = f"'{self._sheet_name}'!E:E"
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self._sheet_id,
            range=range_name,
        ).execute()
        values = result.get('values', [])
        urls: set[str] = set()
        for i, row in enumerate(values):
            if not row:
                continue
            cell = row[0].strip()
            if i == 0 and cell.lower() in _HEADER_ALIASES:
                continue
            if cell:
                urls.add(cell)
        logger.debug("Found %d existing URL(s) in sheet", len(urls))
        return urls

    def append_rows(self, rows: list[list]) -> int:
        """Append rows to the sheet; returns count of rows written."""
        if not rows:
            return 0
        response = self.service.spreadsheets().values().append(
            spreadsheetId=self._sheet_id,
            range=f"'{self._sheet_name}'!A:I",
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': rows},
        ).execute()
        written: int = response.get('updates', {}).get('updatedRows', 0)
        logger.info("Appended %d row(s) to sheet", written)
        return written
