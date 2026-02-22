"""Connect to Google Sheets using OAuth and list worksheets."""

import sys
from pathlib import Path

import gspread
from google_auth_oauthlib.flow import InstalledAppFlow

# Paths relative to this script's location
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_DIR = BASE_DIR / "credentials"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
AUTHORIZED_USER_FILE = CREDENTIALS_DIR / "authorized_user.json"

SPREADSHEET_NAME = "Meat Export Model"


def console_flow(client_config, scopes, port=0):
    """OAuth flow that prints a URL for the user to visit (no browser needed)."""
    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    return flow.run_local_server(port=port, open_browser=False)


def main():
    if not CREDENTIALS_FILE.exists():
        print(
            f"Error: OAuth credentials file not found at {CREDENTIALS_FILE}\n"
            "Download your OAuth client JSON from the Google Cloud Console "
            "and save it as credentials/credentials.json"
        )
        sys.exit(1)

    print("Authenticating with Google...")
    gc = gspread.oauth(
        credentials_filename=str(CREDENTIALS_FILE),
        authorized_user_filename=str(AUTHORIZED_USER_FILE),
        flow=console_flow,
    )

    print(f"Opening spreadsheet: '{SPREADSHEET_NAME}'")
    try:
        spreadsheet = gc.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        print(
            f"Error: Spreadsheet '{SPREADSHEET_NAME}' not found.\n"
            "Make sure the sheet exists and is shared with your Google account."
        )
        sys.exit(1)

    worksheets = spreadsheet.worksheets()
    print(f"\nFound {len(worksheets)} worksheet(s):\n")
    for i, ws in enumerate(worksheets, start=1):
        print(f"  {i}. {ws.title}")


if __name__ == "__main__":
    main()
