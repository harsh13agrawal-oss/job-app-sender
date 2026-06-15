"""Google Sheets backend for the send log.

Mirrors the API of log_manager.py (init_log / append_entry / read_log /
already_sent / now_iso) so the rest of the app stays oblivious. Selected
at startup when running on Streamlit Cloud (st.secrets has the gsheets
config). Locally, log_manager.py (CSV) is used instead.

Required Streamlit secrets:
    gsheets_service_account   — full service-account JSON as a TOML table
    gsheets_sheet_id          — the spreadsheet ID (from its URL)
The service account email must be granted Editor access to the sheet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials


FIELDS = [
    "timestamp",
    "recipient_name",
    "recipient_email",
    "company",
    "role",
    "sector",
    "cv_used",
    "subject",
    "status",
    "message_id_or_error",
]

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


@st.cache_resource(show_spinner=False)
def _get_worksheet():
    sa_info = dict(st.secrets["gsheets_service_account"])
    sheet_id = st.secrets["gsheets_sheet_id"]
    creds = Credentials.from_service_account_info(sa_info, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1
    _ensure_header(ws)
    return ws


def _ensure_header(ws) -> None:
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if first_row != FIELDS:
        if not first_row:
            ws.append_row(FIELDS, value_input_option="USER_ENTERED")
        else:
            ws.update("A1", [FIELDS])


def init_log(_path: str = "") -> None:
    _get_worksheet()


def append_entry(entry: dict, _path: str = "") -> None:
    ws = _get_worksheet()
    row = ["" if entry.get(k) is None else str(entry.get(k)) for k in FIELDS]
    ws.append_row(row, value_input_option="USER_ENTERED")


def read_log(_path: str = "") -> list[dict]:
    ws = _get_worksheet()
    try:
        records = ws.get_all_records(expected_headers=FIELDS)
    except Exception:
        return []
    out = [{k: str(r.get(k, "")) for k in FIELDS} for r in records]
    out.reverse()
    return out


def already_sent(email: str, _path: str = "", company: Optional[str] = None) -> bool:
    if not email:
        return False
    target_email = email.strip().lower()
    target_company = (company or "").strip().lower() if company is not None else None
    ws = _get_worksheet()
    try:
        records = ws.get_all_records(expected_headers=FIELDS)
    except Exception:
        return False
    for r in records:
        if str(r.get("status", "")).strip().lower() != "sent":
            continue
        if str(r.get("recipient_email", "")).strip().lower() != target_email:
            continue
        if target_company is None:
            return True
        if str(r.get("company", "")).strip().lower() == target_company:
            return True
    return False
