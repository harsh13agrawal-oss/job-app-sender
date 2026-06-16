"""CSV-backed send log.

Columns:
    timestamp, recipient_name, recipient_email, company, role, sector,
    cv_used, subject, status, message_id_or_error
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Optional


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


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def init_log(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


_MAX_CELL = 40000


def _clip(val) -> str:
    if val is None:
        return ""
    s = str(val)
    if len(s) > _MAX_CELL:
        s = s[: _MAX_CELL - 30] + f"...[truncated {len(s) - _MAX_CELL + 30} chars]"
    return s


def append_entry(entry: dict, path: str) -> None:
    init_log(path)
    row = {k: _clip(entry.get(k)) for k in FIELDS}
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(row)


def read_log(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: row.get(k, "") for k in FIELDS})
    rows.reverse()
    return rows


def already_sent(email: str, path: str, company: Optional[str] = None) -> bool:
    if not email:
        return False
    target_email = email.strip().lower()
    target_company = (company or "").strip().lower() if company is not None else None
    if not os.path.exists(path):
        return False
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("status", "") or "").strip().lower() != "sent":
                continue
            if (row.get("recipient_email", "") or "").strip().lower() != target_email:
                continue
            if target_company is None:
                return True
            if (row.get("company", "") or "").strip().lower() == target_company:
                return True
    return False
