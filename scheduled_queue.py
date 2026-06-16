"""Queue persistence for scheduled sends.

Stored in a second worksheet ("Queue") of the same Google Sheet as the send
log. Each row represents one queued bulk send; the CV PDF is base64-encoded
and chunked across multiple cells (Google Sheets cap is 50K chars/cell).

Schema (column order matters; do not reorder once data exists):
    id              uuid4 (string)
    created_at      ISO timestamp the user queued it
    scheduled_at    ISO timestamp the runner should send at (UTC)
    status          pending | running | sent | failed | cancelled
    sender_email    Gmail address that should send (informational)
    subject         template subject (with placeholders)
    body_html       template body (with placeholders)
    cv_filename     filename recipients see
    cv_b64_1..8     base64-encoded CV, chunked at 35000 chars each (~280KB max PDF)
    recipients_json JSON array: [{name, email, company, role, custom1, custom2}, ...]
    is_followup     "true"/"false" — when true, recipients_json rows must include
                    original_message_id so the runner threads the reply
    result_summary  short status message written after running
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


QUEUE_FIELDS = [
    "id",
    "created_at",
    "scheduled_at",
    "status",
    "sender_email",
    "subject",
    "body_html",
    "cv_filename",
    "cv_b64_1", "cv_b64_2", "cv_b64_3", "cv_b64_4",
    "cv_b64_5", "cv_b64_6", "cv_b64_7", "cv_b64_8",
    "recipients_json",
    "is_followup",
    "result_summary",
]

_CHUNK = 35000  # well under the 50K Sheets cell limit
_N_CHUNKS = 8

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_queue_ws(sa_info: dict, sheet_id: str):
    creds = Credentials.from_service_account_info(sa_info, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("Queue")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Queue", rows=200, cols=len(QUEUE_FIELDS))
        ws.append_row(QUEUE_FIELDS, value_input_option="USER_ENTERED")
        return ws
    first_row = ws.row_values(1)
    if first_row != QUEUE_FIELDS:
        ws.update("A1", [QUEUE_FIELDS])
    return ws


def chunk_cv_bytes(cv_bytes: Optional[bytes]) -> list[str]:
    """Return N_CHUNKS strings; empty strings for unused slots. None -> all empty."""
    out = [""] * _N_CHUNKS
    if not cv_bytes:
        return out
    encoded = base64.b64encode(cv_bytes).decode("ascii")
    if len(encoded) > _CHUNK * _N_CHUNKS:
        raise ValueError(
            f"CV is too large to queue: needs {len(encoded)} base64 chars, "
            f"max is {_CHUNK * _N_CHUNKS}. Try a smaller PDF (< 280KB)."
        )
    for i in range(_N_CHUNKS):
        start = i * _CHUNK
        out[i] = encoded[start : start + _CHUNK]
    return out


def unchunk_cv_bytes(row: dict) -> Optional[bytes]:
    parts = [row.get(f"cv_b64_{i+1}", "") or "" for i in range(_N_CHUNKS)]
    encoded = "".join(parts).strip()
    if not encoded:
        return None
    return base64.b64decode(encoded)


def enqueue(
    sa_info: dict,
    sheet_id: str,
    *,
    scheduled_at_iso: str,
    sender_email: str,
    subject: str,
    body_html: str,
    cv_filename: str,
    cv_bytes: Optional[bytes],
    recipients: list[dict],
    is_followup: bool,
    queue_id: str,
) -> None:
    ws = _get_queue_ws(sa_info, sheet_id)
    cv_chunks = chunk_cv_bytes(cv_bytes)
    row = [
        queue_id,
        datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        scheduled_at_iso,
        "pending",
        sender_email,
        subject,
        body_html,
        cv_filename or "",
        *cv_chunks,
        json.dumps(recipients, ensure_ascii=False),
        "true" if is_followup else "false",
        "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def read_queue(sa_info: dict, sheet_id: str) -> list[dict]:
    ws = _get_queue_ws(sa_info, sheet_id)
    try:
        records = ws.get_all_records(expected_headers=QUEUE_FIELDS)
    except Exception:
        return []
    out = []
    for r in records:
        out.append({k: r.get(k, "") for k in QUEUE_FIELDS})
    return out


def find_row_index(ws, queue_id: str) -> Optional[int]:
    col_values = ws.col_values(1)
    for idx, val in enumerate(col_values, start=1):
        if val == queue_id:
            return idx
    return None


def update_status(
    sa_info: dict,
    sheet_id: str,
    *,
    queue_id: str,
    status: str,
    result_summary: str = "",
) -> None:
    ws = _get_queue_ws(sa_info, sheet_id)
    row_idx = find_row_index(ws, queue_id)
    if row_idx is None:
        return
    status_col = QUEUE_FIELDS.index("status") + 1
    summary_col = QUEUE_FIELDS.index("result_summary") + 1
    ws.update_cell(row_idx, status_col, status)
    if result_summary:
        # trim to fit
        ws.update_cell(row_idx, summary_col, str(result_summary)[:5000])
