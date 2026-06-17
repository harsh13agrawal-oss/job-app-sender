"""Gmail API wrapper for the Job Application Sender app.

Auth happens once per process. Outgoing mail is multipart/mixed wrapping a
multipart/alternative inner (plain-text + HTML), so deliverability is decent
and we don't ship HTML-only messages. Attachments use a caller-supplied
display name so the recipient never sees the file path on disk.
"""

from __future__ import annotations

import base64
import os
import re
import html as html_lib
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GmailSender:
    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.user_email: Optional[str] = None

    def authenticate(self) -> tuple[bool, str]:
        creds: Optional[Credentials] = None

        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                creds = None

        if creds and creds.valid:
            pass
        elif creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                try:
                    os.remove(self.token_path)
                except OSError:
                    pass
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(self.credentials_path):
                return False, (
                    f"credentials.json not found at {self.credentials_path}. "
                    "Follow the OAuth setup in README.md."
                )
            try:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                return False, f"OAuth flow failed: {e}"
            try:
                with open(self.token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except OSError as e:
                return False, f"Could not write token.json: {e}"

        try:
            self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = self.service.users().getProfile(userId="me").execute()
            self.user_email = profile.get("emailAddress")
        except HttpError as e:
            return False, f"Gmail API error: {e}"
        except Exception as e:
            return False, f"Failed to build Gmail service: {e}"

        return True, f"Connected as {self.user_email}"

    def authenticate_from_dict(self, token_info: dict) -> tuple[bool, str]:
        """Build credentials from an in-memory token dict (cloud-mode path).

        token_info must contain the fields written by Credentials.to_json():
        token, refresh_token, token_uri, client_id, client_secret, scopes.
        Used when there's no writable disk for token.json (Streamlit Cloud).
        """
        try:
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        except Exception as e:
            return False, f"Could not load token from secrets: {e}"

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                return False, f"Token refresh failed (re-run generate_cloud_token.py): {e}"

        if not creds.valid:
            return False, "Token in secrets is not usable. Regenerate it locally."

        try:
            self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = self.service.users().getProfile(userId="me").execute()
            self.user_email = profile.get("emailAddress")
        except HttpError as e:
            return False, f"Gmail API error: {e}"
        except Exception as e:
            return False, f"Failed to build Gmail service: {e}"

        return True, f"Connected as {self.user_email}"

    def disconnect(self) -> None:
        self.service = None
        self.user_email = None

    @staticmethod
    def clean_html_body(html: str) -> str:
        """Strip Quill's invisible 'empty paragraph' blocks that render as blank
        lines in delivered email. Removes <p></p>, <p><br></p>, <p>&nbsp;</p>
        and similar; collapses runs of 3+ <br> to 2; trims leading/trailing
        empty space."""
        if not html:
            return html
        s = html
        s = re.sub(
            r"<p[^>]*>\s*(?:<br\s*/?>\s*|&nbsp;|\s)*</p>",
            "",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"(?:<br\s*/?>\s*){3,}", "<br><br>", s, flags=re.IGNORECASE)
        s = re.sub(r"^(?:\s|<br\s*/?>|&nbsp;)+", "", s, flags=re.IGNORECASE)
        s = re.sub(r"(?:\s|<br\s*/?>|&nbsp;)+$", "", s, flags=re.IGNORECASE)
        return s

    @staticmethod
    def html_to_text(html: str) -> str:
        """Crude HTML -> plain text for the text/plain alternative."""
        if not html:
            return ""
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n\n", text)
        text = re.sub(r"(?i)</li\s*>", "\n", text)
        text = re.sub(r"(?i)<li\s*[^>]*>", "- ", text)
        text = re.sub(r"(?is)<[^>]+>", "", text)
        text = html_lib.unescape(text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def get_message_meta(self, message_id: str) -> Optional[dict]:
        """Return {'thread_id', 'message_id_header', 'subject'} for a stored msg id."""
        if self.service is None or not message_id:
            return None
        try:
            msg = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID", "Subject"],
                )
                .execute()
            )
        except HttpError:
            return None
        except Exception:
            return None
        headers = {
            h.get("name", "").lower(): h.get("value", "")
            for h in (msg.get("payload", {}) or {}).get("headers", [])
        }
        return {
            "thread_id": msg.get("threadId", ""),
            "message_id_header": headers.get("message-id", ""),
            "subject": headers.get("subject", ""),
        }

    def build_message(
        self,
        sender_display_name: str,
        recipient_email: str,
        subject: str,
        html_body: str,
        attachments: Iterable[tuple[str, str]],
        bcc: Optional[str] = None,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> dict:
        if not self.user_email:
            raise RuntimeError("Not authenticated — call authenticate() first.")

        from_header = (
            f"{sender_display_name} <{self.user_email}>" if sender_display_name else self.user_email
        )

        outer = MIMEMultipart("mixed")
        outer["From"] = from_header
        outer["To"] = recipient_email
        outer["Subject"] = subject
        if bcc:
            outer["Bcc"] = bcc
        if reply_to:
            outer["Reply-To"] = reply_to
        if in_reply_to:
            outer["In-Reply-To"] = in_reply_to
            outer["References"] = in_reply_to

        inner = MIMEMultipart("alternative")
        cleaned_html = self.clean_html_body(html_body or "") or " "
        plain_text = self.html_to_text(cleaned_html) or " "
        inner.attach(MIMEText(plain_text, "plain", "utf-8"))
        inner.attach(MIMEText(cleaned_html, "html", "utf-8"))
        outer.attach(inner)

        for source, display_name in attachments or []:
            if source in (None, "", b""):
                continue
            if isinstance(source, (bytes, bytearray)):
                data = bytes(source)
                hint_name = display_name or "attachment.bin"
            else:
                abs_path = str(source)
                if not os.path.isfile(abs_path):
                    raise FileNotFoundError(f"Attachment not found: {abs_path}")
                with open(abs_path, "rb") as f:
                    data = f.read()
                hint_name = display_name or os.path.basename(abs_path)
            display = display_name or hint_name
            if hint_name.lower().endswith(".pdf"):
                part = MIMEApplication(data, _subtype="pdf")
            else:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(data)
                encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=display)
            outer.attach(part)

        raw = base64.urlsafe_b64encode(outer.as_bytes()).decode()
        return {"raw": raw}

    def list_replies(
        self,
        recipient_emails: Iterable[str],
        days: int = 30,
        chunk_size: int = 20,
        max_per_query: int = 100,
    ) -> list[dict]:
        """Search the inbox for messages from any of the given senders.

        Returns a list of dicts with keys:
            id, thread_id, from, subject, date, snippet, matched_email.
        Newest first. Returns [] if not authenticated or no addresses given.
        """
        if self.service is None:
            return []
        emails = sorted({(e or "").strip().lower() for e in recipient_emails if (e or "").strip()})
        if not emails:
            return []

        chunks: list[list[str]] = [
            emails[i : i + chunk_size] for i in range(0, len(emails), chunk_size)
        ]
        seen_ids: set[str] = set()
        message_refs: list[dict] = []

        for chunk in chunks:
            from_clause = " OR ".join(f"from:{addr}" for addr in chunk)
            q = f"in:inbox newer_than:{int(days)}d ({from_clause})"
            page_token: Optional[str] = None
            while True:
                try:
                    resp = (
                        self.service.users()
                        .messages()
                        .list(
                            userId="me",
                            q=q,
                            maxResults=min(100, max_per_query),
                            pageToken=page_token,
                        )
                        .execute()
                    )
                except HttpError:
                    break
                for m in resp.get("messages", []) or []:
                    mid = m.get("id")
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        message_refs.append(m)
                page_token = resp.get("nextPageToken")
                if not page_token or len(message_refs) >= max_per_query * len(chunks):
                    break

        results: list[dict] = []
        for ref in message_refs:
            mid = ref.get("id")
            try:
                msg = (
                    self.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
            except HttpError:
                continue

            headers = {
                h.get("name", "").lower(): h.get("value", "")
                for h in msg.get("payload", {}).get("headers", [])
            }
            from_hdr = headers.get("from", "")
            from_addr_match = re.search(r"<([^>]+)>", from_hdr)
            from_addr = (from_addr_match.group(1) if from_addr_match else from_hdr).strip().lower()
            matched = next((e for e in emails if e in from_addr), from_addr)

            results.append(
                {
                    "id": mid,
                    "thread_id": msg.get("threadId", ""),
                    "from": from_hdr,
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "internal_date": int(msg.get("internalDate", "0") or 0),
                    "matched_email": matched,
                }
            )

        results.sort(key=lambda r: r.get("internal_date", 0), reverse=True)
        return results

    def send(
        self,
        sender_display_name: str,
        recipient_email: str,
        subject: str,
        html_body: str,
        attachments: Iterable[tuple[str, str]],
        bcc: Optional[str] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> tuple[bool, str]:
        if self.service is None:
            return False, "Not authenticated."
        for source, _ in attachments or []:
            if isinstance(source, (bytes, bytearray)):
                continue
            if source and not os.path.isfile(str(source)):
                return False, f"Attachment not found: {source}"
        try:
            message = self.build_message(
                sender_display_name=sender_display_name,
                recipient_email=recipient_email,
                subject=subject,
                html_body=html_body,
                attachments=attachments,
                bcc=bcc,
                reply_to=reply_to or self.user_email,
                in_reply_to=in_reply_to,
            )
            if thread_id:
                message["threadId"] = thread_id
            result = self.service.users().messages().send(userId="me", body=message).execute()
            return True, result.get("id", "")
        except FileNotFoundError as e:
            return False, str(e)[:1000]
        except HttpError as e:
            # HttpError stringifies to include the full request body; the
            # request contains the base64-encoded MIME message + attachment
            # which can be megabytes. Just take the status + reason.
            status = getattr(e.resp, "status", "?") if hasattr(e, "resp") else "?"
            reason = getattr(e, "reason", "") or ""
            return False, f"Gmail API error: HTTP {status} {reason}"[:1000]
        except Exception as e:
            return False, f"Send failed: {e}"[:1000]
