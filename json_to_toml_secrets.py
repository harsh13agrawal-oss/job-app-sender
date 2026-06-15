"""Convert a Google service-account JSON key into a TOML block.

Usage:
    python json_to_toml_secrets.py path-to-service-account.json

Prints a [gsheets_service_account] TOML block ready to paste into
Streamlit Cloud → Settings → Secrets.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python json_to_toml_secrets.py <service_account.json>", file=sys.stderr)
        return 1

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    print("\n" + "=" * 60)
    print("Paste this block into Streamlit Cloud → Settings → Secrets")
    print("(keep your existing secrets above this — just add this block)")
    print("=" * 60 + "\n")

    print("[gsheets_service_account]")
    for key, val in data.items():
        if key == "private_key":
            print(f'{key} = """\\')
            for line in val.splitlines():
                print(line)
            print('"""')
        elif isinstance(val, bool):
            print(f"{key} = {str(val).lower()}")
        elif isinstance(val, (int, float)):
            print(f"{key} = {val}")
        else:
            escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
            print(f'{key} = "{escaped}"')

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
