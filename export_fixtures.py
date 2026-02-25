"""Export every worksheet from the Meat Export Model spreadsheet to JSON fixtures."""

import json
import re
import sys
from pathlib import Path

import gspread
from gspread.exceptions import APIError

BASE_DIR = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "credentials" / "service_account.json"
FIXTURES_DIR = BASE_DIR / "tests" / "fixtures"

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1ROyguHxXvad-SV0yMN8zFUlGTegGM5C-d10VipsTEu0/edit?usp=sharing"
)


def slugify(name):
    """Turn a worksheet title into a safe filename slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug


def export_worksheet(ws):
    """Return a list of dicts (one per row) using the first row as headers."""
    rows = ws.get_all_values()
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def main():
    if not SERVICE_ACCOUNT_FILE.exists():
        print(
            f"Error: Service account key not found at {SERVICE_ACCOUNT_FILE}\n"
            "Download your service account JSON key from the Google Cloud Console "
            "and save it as credentials/service_account.json"
        )
        sys.exit(1)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print("Authenticating with service account...")
    gc = gspread.service_account(filename=str(SERVICE_ACCOUNT_FILE))

    print("Opening spreadsheet...")
    try:
        spreadsheet = gc.open_by_url(SPREADSHEET_URL)
    except (APIError, PermissionError, gspread.SpreadsheetNotFound) as e:
        print(f"Error opening spreadsheet: {e}")
        sys.exit(1)

    worksheets = spreadsheet.worksheets()
    print(f"Found {len(worksheets)} worksheet(s)\n")

    for ws in worksheets:
        slug = slugify(ws.title)
        out_path = FIXTURES_DIR / f"{slug}.json"
        print(f"  Exporting '{ws.title}' -> {out_path.relative_to(BASE_DIR)}")

        data = export_worksheet(ws)
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"    {len(data)} rows written")

    print(f"\nDone. Fixtures saved to {FIXTURES_DIR.relative_to(BASE_DIR)}/")


if __name__ == "__main__":
    main()
