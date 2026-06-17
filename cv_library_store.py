"""Persist the user's CV library to a worksheet of the same Google Sheet.

Each slot is one row: idx, name, filename, then 20 base64-chunked cells
(20 × 35K = ~700KB max CV — covers nearly every PDF).

The same service account that writes the send log handles this — no extra
API/credentials needed.
"""

from __future__ import annotations

import base64
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1


N_CHUNKS = 20
CHUNK_SIZE = 35000
FIELDS = ["idx", "name", "filename"] + [f"cv_b64_{i+1}" for i in range(N_CHUNKS)]
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_ws(sa_info: dict, sheet_id: str):
    creds = Credentials.from_service_account_info(sa_info, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("CV_Library")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="CV_Library", rows=20, cols=len(FIELDS))
        ws.append_row(FIELDS, value_input_option="USER_ENTERED")
        return ws
    first_row = ws.row_values(1)
    if first_row != FIELDS:
        ws.update("A1", [FIELDS])
    return ws


def _chunk(b: bytes) -> list[str]:
    encoded = base64.b64encode(b).decode("ascii")
    if len(encoded) > CHUNK_SIZE * N_CHUNKS:
        raise ValueError(
            f"CV too large to save: {len(encoded)} base64 chars, max "
            f"{CHUNK_SIZE * N_CHUNKS}. Slim the PDF (target < 700KB)."
        )
    out = []
    for i in range(N_CHUNKS):
        start = i * CHUNK_SIZE
        out.append(encoded[start : start + CHUNK_SIZE])
    return out


def _unchunk(row: dict) -> Optional[bytes]:
    parts = [row.get(f"cv_b64_{i+1}", "") or "" for i in range(N_CHUNKS)]
    encoded = "".join(parts).strip()
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded)
    except Exception:
        return None


def load_all(sa_info: dict, sheet_id: str) -> list[dict]:
    """Return a list of {idx, name, filename, bytes} from the CV_Library worksheet."""
    ws = _get_ws(sa_info, sheet_id)
    try:
        records = ws.get_all_records(expected_headers=FIELDS)
    except Exception:
        return []
    out: list[dict] = []
    for r in records:
        try:
            idx = int(str(r.get("idx", "")).strip())
        except (ValueError, TypeError):
            continue
        name = str(r.get("name", "") or "").strip()
        filename = str(r.get("filename", "") or "").strip()
        b = _unchunk(r)
        if not (name and b):
            continue
        out.append({"idx": idx, "name": name, "filename": filename, "bytes": b})
    return out


def _find_row_by_idx(ws, idx: int) -> Optional[int]:
    col = ws.col_values(1)
    for row_no, val in enumerate(col, start=1):
        if row_no == 1:
            continue
        try:
            if int(str(val).strip()) == idx:
                return row_no
        except (ValueError, TypeError):
            continue
    return None


def save_slot(
    sa_info: dict,
    sheet_id: str,
    *,
    idx: int,
    name: str,
    filename: str,
    cv_bytes: Optional[bytes],
) -> None:
    """Upsert one slot. If cv_bytes is None we keep existing chunks (name-only update)."""
    ws = _get_ws(sa_info, sheet_id)
    existing_row = _find_row_by_idx(ws, idx)

    if cv_bytes is None and existing_row:
        # Name-only update — preserve existing CV chunks
        ws.update_cell(existing_row, FIELDS.index("name") + 1, name)
        if filename:
            ws.update_cell(existing_row, FIELDS.index("filename") + 1, filename)
        return

    chunks = _chunk(cv_bytes) if cv_bytes else [""] * N_CHUNKS
    row_data = [str(idx), name, filename] + chunks
    if existing_row:
        start = rowcol_to_a1(existing_row, 1)
        end = rowcol_to_a1(existing_row, len(row_data))
        ws.update(f"{start}:{end}", [row_data], value_input_option="USER_ENTERED")
    else:
        ws.append_row(row_data, value_input_option="USER_ENTERED")


def delete_slot(sa_info: dict, sheet_id: str, idx: int) -> None:
    ws = _get_ws(sa_info, sheet_id)
    row = _find_row_by_idx(ws, idx)
    if row:
        ws.delete_rows(row)
