"""Connect to Google Sheets using a service account and list worksheets."""

import sys
from pathlib import Path

import gspread
from gspread.exceptions import APIError

# Paths relative to this script's location
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_DIR = BASE_DIR / "credentials"
SERVICE_ACCOUNT_FILE = CREDENTIALS_DIR / "service_account.json"

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1ROyguHxXvad-SV0yMN8zFUlGTegGM5C-d10VipsTEu0/edit?usp=sharing"


def main():
    if not SERVICE_ACCOUNT_FILE.exists():
        print(
            f"Error: Service account key not found at {SERVICE_ACCOUNT_FILE}\n"
            "Download your service account JSON key from the Google Cloud Console "
            "and save it as credentials/service_account.json"
        )
        sys.exit(1)

    print("Authenticating with service account...")
    gc = gspread.service_account(filename=str(SERVICE_ACCOUNT_FILE))

    print(f"Opening spreadsheet by URL...")
    try:
        spreadsheet = gc.open_by_url(SPREADSHEET_URL)
    except APIError as e:
        resp = e.response
        print(f"\n--- API Error ---")
        print(f"Status code: {resp.status_code}")
        print(f"Reason: {resp.reason}")
        print(f"\nHeaders:")
        for key, value in resp.headers.items():
            print(f"  {key}: {value}")
        print(f"\nBody:\n{resp.text}")
        sys.exit(1)
    except PermissionError as e:
        print(f"\n--- Permission Error ---")
        print(f"The service account does not have access to this spreadsheet.")
        print(f"Underlying error: {e.__cause__}")
        if hasattr(e, '__cause__') and isinstance(e.__cause__, APIError):
            resp = e.__cause__.response
            print(f"Status code: {resp.status_code}")
            print(f"Reason: {resp.reason}")
            print(f"\nHeaders:")
            for key, value in resp.headers.items():
                print(f"  {key}: {value}")
            print(f"\nBody:\n{resp.text}")
        sys.exit(1)
    except gspread.SpreadsheetNotFound:
        print(
            "Error: Spreadsheet not found.\n"
            "Make sure the sheet is shared with the service account email address."
        )
        sys.exit(1)

    worksheets = spreadsheet.worksheets()
    print(f"\nFound {len(worksheets)} worksheet(s):\n")
    for i, ws in enumerate(worksheets, start=1):
        print(f"  {i}. {ws.title}")


if __name__ == "__main__":
    main()
