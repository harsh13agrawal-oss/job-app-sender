"""Run this ONCE locally to mint a refresh-token bundle for cloud deployment.

It opens your browser, has you sign into the same Gmail you want the cloud app
to send from, and prints a TOML block you paste into Streamlit Cloud secrets
under the key `gmail_token`.

Usage (from the project folder, with the venv active):
    python generate_cloud_token.py

Re-run any time the refresh token stops working (rare — usually it never does).
"""

from __future__ import annotations

import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    creds_path = os.path.join(here, "credentials.json")
    if not os.path.exists(creds_path):
        print(
            f"ERROR: credentials.json not found at {creds_path}\n"
            "Follow the OAuth setup in README.md first.",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    token_dict = json.loads(creds.to_json())

    print("\n" + "=" * 60)
    print("Paste the block below into Streamlit Cloud → App → Settings → Secrets")
    print("=" * 60 + "\n")
    print("[gmail_token]")
    for key, val in token_dict.items():
        if isinstance(val, list):
            items = ", ".join(f'"{v}"' for v in val)
            print(f"{key} = [{items}]")
        elif isinstance(val, bool):
            print(f"{key} = {str(val).lower()}")
        elif isinstance(val, (int, float)):
            print(f"{key} = {val}")
        else:
            escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
            print(f'{key} = "{escaped}"')
    print()
    print("=" * 60)
    print("Also remember to set these other secrets in the same dialog:")
    print('  app_password = "<a strong password you choose>"')
    print('  gsheets_sheet_id = "<the spreadsheet ID from its URL>"')
    print("  [gsheets_service_account]   # paste the service-account JSON here")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
