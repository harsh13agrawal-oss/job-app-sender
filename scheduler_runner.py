"""Headless scheduled-send runner.

Reads pending jobs from the Queue worksheet, sends any whose scheduled_at <= now
(UTC), and marks them sent/failed. Designed to be invoked by GitHub Actions on
a cron schedule (every 15 minutes is sensible).

Environment variables required:
    GMAIL_TOKEN_JSON         Full token JSON (single line, escaped) — what
                              you'd get from generate_cloud_token.py's output
                              but as JSON, not TOML.
    GSHEETS_SA_JSON          Service-account JSON (single line).
    GSHEETS_SHEET_ID         The spreadsheet ID.

Optional:
    DRY_RUN=1                Don't actually send; log what would have happened.
    MIN_DELAY_SEC=30         Min delay between sends in a batch (default 30).
    MAX_DELAY_SEC=90         Max delay between sends in a batch (default 90).
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCreds
from googleapiclient.discovery import build

import scheduled_queue


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _required_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(f"FATAL: env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def _build_gmail_service(token_dict: dict):
    creds = UserCreds.from_authorized_user_info(token_dict, GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds.valid:
        raise RuntimeError("Gmail credentials invalid after refresh.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


_TITLES = {"dr", "mr", "mrs", "ms", "prof", "mx", "sir", "madam"}


def _first_name(full: str) -> str:
    parts = (full or "").strip().split()
    while parts and parts[0].rstrip(".").lower() in _TITLES:
        parts = parts[1:]
    return parts[0] if parts else ""


def _html_to_text(html: str) -> str:
    import html as _html
    if not html:
        return ""
    t = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</p\s*>", "\n\n", t)
    t = re.sub(r"(?is)<[^>]+>", "", t)
    return _html.unescape(t).strip()


def _render(template: str, ctx: dict) -> str:
    out = template or ""
    for k, v in (ctx or {}).items():
        out = out.replace("{" + str(k) + "}", "" if v is None else str(v))
    return out


def _build_raw_message(
    *,
    sender_email: str,
    sender_display_name: str,
    recipient_email: str,
    subject: str,
    html_body: str,
    cv_bytes: bytes | None,
    cv_filename: str,
    in_reply_to: str | None = None,
) -> dict:
    from_hdr = (
        f"{sender_display_name} <{sender_email}>" if sender_display_name else sender_email
    )
    outer = MIMEMultipart("mixed")
    outer["From"] = from_hdr
    outer["To"] = recipient_email
    outer["Subject"] = subject
    outer["Reply-To"] = sender_email
    if in_reply_to:
        outer["In-Reply-To"] = in_reply_to
        outer["References"] = in_reply_to

    inner = MIMEMultipart("alternative")
    inner.attach(MIMEText(_html_to_text(html_body) or " ", "plain", "utf-8"))
    inner.attach(MIMEText(html_body or " ", "html", "utf-8"))
    outer.attach(inner)

    if cv_bytes:
        part = MIMEApplication(cv_bytes, _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment", filename=cv_filename or "CV.pdf"
        )
        outer.attach(part)

    return {"raw": base64.urlsafe_b64encode(outer.as_bytes()).decode()}


def _get_meta(service, message_id: str) -> dict | None:
    if not message_id:
        return None
    try:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Message-ID", "Subject"],
            )
            .execute()
        )
    except Exception:
        return None
    headers = {
        h.get("name", "").lower(): h.get("value", "")
        for h in msg.get("payload", {}).get("headers", [])
    }
    return {
        "thread_id": msg.get("threadId", ""),
        "message_id_header": headers.get("message-id", ""),
        "subject": headers.get("subject", ""),
    }


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def main() -> int:
    sa_info = json.loads(_required_env("GSHEETS_SA_JSON"))
    sheet_id = _required_env("GSHEETS_SHEET_ID")
    token_dict = json.loads(_required_env("GMAIL_TOKEN_JSON"))

    dry_run = os.environ.get("DRY_RUN") == "1"
    min_d = int(os.environ.get("MIN_DELAY_SEC", "30"))
    max_d = int(os.environ.get("MAX_DELAY_SEC", "90"))
    if max_d < min_d:
        min_d, max_d = max_d, min_d

    rows = scheduled_queue.read_queue(sa_info, sheet_id)
    now = datetime.now(timezone.utc)
    due = []
    for r in rows:
        if (r.get("status") or "").strip().lower() != "pending":
            continue
        sched = _parse_iso(r.get("scheduled_at", ""))
        if not sched:
            continue
        if sched <= now:
            due.append(r)

    if not due:
        print(f"[{_now_utc_iso()}] No due jobs (queue size: {len(rows)}).")
        return 0

    print(f"[{_now_utc_iso()}] Found {len(due)} due job(s).")
    service = _build_gmail_service(token_dict)

    for job in due:
        qid = job.get("id", "")
        try:
            scheduled_queue.update_status(
                sa_info, sheet_id, queue_id=qid, status="running"
            )
        except Exception as e:
            print(f"  [{qid}] failed to mark running: {e}", file=sys.stderr)

        try:
            cv_bytes = scheduled_queue.unchunk_cv_bytes(job)
            cv_filename = job.get("cv_filename") or "CV.pdf"
            subject_tmpl = job.get("subject", "")
            body_tmpl = job.get("body_html", "")
            sender_email = job.get("sender_email", "")
            is_followup = (job.get("is_followup", "") or "").strip().lower() == "true"
            recipients = json.loads(job.get("recipients_json", "[]") or "[]")
        except Exception as e:
            scheduled_queue.update_status(
                sa_info, sheet_id, queue_id=qid, status="failed",
                result_summary=f"Decode error: {e}",
            )
            continue

        sent = 0
        failed = 0
        last = len(recipients) - 1
        for i, rcpt in enumerate(recipients):
            email = (rcpt.get("email") or "").strip()
            if not email:
                failed += 1
                continue
            full = rcpt.get("name", "") or ""
            first = _first_name(full)
            ctx = {
                "name": first or "Hiring Team",
                "first_name": first or "Hiring Team",
                "full_name": full or "Hiring Team",
                "company": rcpt.get("company", ""),
                "role": rcpt.get("role", ""),
                "custom1": rcpt.get("custom1", ""),
                "custom2": rcpt.get("custom2", ""),
            }
            sub = _render(subject_tmpl, ctx)
            bod = _render(body_tmpl, ctx)

            thread_id = None
            in_reply_to = None
            if is_followup and rcpt.get("original_message_id"):
                meta = _get_meta(service, rcpt["original_message_id"])
                if meta:
                    thread_id = meta.get("thread_id") or None
                    in_reply_to = meta.get("message_id_header") or None
                    orig_subj = meta.get("subject") or ""
                    if orig_subj and not sub.lower().startswith("re:"):
                        sub = f"Re: {orig_subj}"

            if dry_run:
                print(f"  [DRY] {email}: subject={sub!r}")
                sent += 1
            else:
                try:
                    msg = _build_raw_message(
                        sender_email=sender_email,
                        sender_display_name="",
                        recipient_email=email,
                        subject=sub,
                        html_body=bod,
                        cv_bytes=cv_bytes,
                        cv_filename=cv_filename,
                        in_reply_to=in_reply_to,
                    )
                    if thread_id:
                        msg["threadId"] = thread_id
                    service.users().messages().send(userId="me", body=msg).execute()
                    sent += 1
                except Exception as e:
                    print(f"  [{email}] send failed: {e}", file=sys.stderr)
                    failed += 1

            if i != last:
                time.sleep(random.randint(min_d, max_d))

        final = "sent" if failed == 0 else ("failed" if sent == 0 else "sent")
        summary = f"sent={sent} failed={failed} of {len(recipients)}"
        scheduled_queue.update_status(
            sa_info, sheet_id, queue_id=qid, status=final, result_summary=summary
        )
        print(f"  [{qid}] {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
