"""Job Application Sender — Streamlit UI.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import time
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

try:
    from streamlit_quill import st_quill
    HAVE_QUILL = True
except ImportError:
    HAVE_QUILL = False

from email_sender import GmailSender
from template_manager import DEFAULT_TEMPLATES, load_templates, render, save_templates


def _has_secret(key: str) -> bool:
    try:
        return key in st.secrets
    except Exception:
        return False


CLOUD_MODE = _has_secret("gsheets_sheet_id")

if CLOUD_MODE:
    from log_manager_gsheet import (
        already_sent,
        append_entry,
        init_log,
        now_iso,
        read_log,
    )
else:
    from log_manager import (
        already_sent,
        append_entry,
        init_log,
        now_iso,
        read_log,
    )


APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TEMPLATES_PATH = os.path.join(APP_DIR, "templates.json")
LOG_PATH = os.path.join(APP_DIR, "logs", "send_log.csv")
CREDENTIALS_PATH = os.path.join(APP_DIR, "credentials.json")
TOKEN_PATH = os.path.join(APP_DIR, "token.json")

SECTORS = [
    "Finance / PE / IB",
    "Consulting",
    "Tech / Corporate Finance",
    "General / Other",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "sender_display_name": "CA Harsh Agarwal",
    "phone": "",
    "linkedin_url": "",
    "bcc_self": True,
    "min_delay_sec": 45,
    "max_delay_sec": 120,
    "daily_cap": 40,
    "attach_cover_letter": True,
    "cv_display_filename": "Harsh Agarwal - CV.pdf",
    "cover_letter_display_filename": "Harsh Agarwal - Cover Letter.pdf",
    "cv_paths": {s: "" for s in SECTORS},
    "cover_letter_paths": {s: "" for s in SECTORS},
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_config() -> dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in (data or {}).items():
        if k in ("cv_paths", "cover_letter_paths") and isinstance(v, dict):
            merged_paths = dict(merged[k])
            for sector, path_val in v.items():
                if sector in SECTORS:
                    merged_paths[sector] = str(path_val or "")
            merged[k] = merged_paths
        else:
            merged[k] = v
    for s in SECTORS:
        merged["cv_paths"].setdefault(s, "")
        merged["cover_letter_paths"].setdefault(s, "")
    return merged


def save_config(cfg: dict[str, Any]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def require_login() -> None:
    """Single-password gate. Active only when 'app_password' is in secrets."""
    if not _has_secret("app_password"):
        return
    if st.session_state.get("authed"):
        return
    st.title("Job Application Sender")
    st.caption("Sign in to continue.")
    with st.form("login_form", clear_on_submit=False):
        pw = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", type="primary")
    if ok:
        if pw and pw == st.secrets["app_password"]:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


def auto_connect_gmail() -> None:
    """In cloud mode, connect Gmail automatically using token from secrets."""
    if not CLOUD_MODE:
        return
    if st.session_state.connected:
        return
    if not _has_secret("gmail_token"):
        return
    token_info = dict(st.secrets["gmail_token"])
    ok, msg = st.session_state.sender.authenticate_from_dict(token_info)
    if ok:
        st.session_state.connected = True
        st.session_state.connected_email = st.session_state.sender.user_email or ""
    else:
        st.session_state.gmail_auto_connect_error = msg


def ensure_state() -> None:
    if "sender" not in st.session_state:
        st.session_state.sender = GmailSender(
            credentials_path=CREDENTIALS_PATH, token_path=TOKEN_PATH
        )
    if "connected" not in st.session_state:
        st.session_state.connected = False
    if "connected_email" not in st.session_state:
        st.session_state.connected_email = ""
    if "templates" not in st.session_state:
        st.session_state.templates = load_templates(TEMPLATES_PATH)
    if "config" not in st.session_state:
        st.session_state.config = load_config()
    if "bulk_df" not in st.session_state:
        st.session_state.bulk_df = None
    if "uploaded_cvs" not in st.session_state:
        st.session_state.uploaded_cvs = {}
    if "uploaded_cls" not in st.session_state:
        st.session_state.uploaded_cls = {}
    if "cv_library" not in st.session_state:
        st.session_state.cv_library = {}  # {idx: bytes}
    if "cv_library_names" not in st.session_state:
        st.session_state.cv_library_names = {}  # {idx: name}
    if "followup_candidates" not in st.session_state:
        st.session_state.followup_candidates = []
    if "followup_body_key_n" not in st.session_state:
        st.session_state.followup_body_key_n = 0
    if "followup_subject_text" not in st.session_state:
        st.session_state.followup_subject_text = "Following up: {role} at {company}"
        st.session_state.followup_body_initial = (
            "<p>Dear {name},</p>"
            "<p>I hope this note finds you well. I wanted to follow up on my earlier email "
            "about the <strong>{role}</strong> opportunity at <strong>{company}</strong>.</p>"
            "<p>I understand things get busy, and I would be happy to share any additional "
            "information that would help. If there is someone else on your team I should "
            "be reaching out to, I would be grateful for the introduction.</p>"
            "<p>Looking forward to hearing from you.</p>"
            "<p>Warm regards,<br><strong>CA Harsh Agarwal</strong></p>"
        )
        st.session_state.followup_last_tmpl_choice = None
    if "quick_body_key_n" not in st.session_state:
        st.session_state.quick_body_key_n = 0
    if "quick_subject_text" not in st.session_state:
        first = next(iter(st.session_state.templates), None)
        if first:
            st.session_state.quick_subject_text = st.session_state.templates[first]["subject"]
            st.session_state.quick_body_initial = st.session_state.templates[first]["body_html"]
            st.session_state.quick_last_tmpl_choice = first
        else:
            st.session_state.quick_subject_text = (
                "Application for {role} at {company} – CA Harsh Agarwal"
            )
            st.session_state.quick_body_initial = (
                "<p>Dear {name},</p><p>I am writing to express my interest in the "
                "<strong>{role}</strong> opportunity at <strong>{company}</strong>.</p>"
                "<p>{custom1}</p><p>Warm regards,<br><strong>CA Harsh Agarwal</strong></p>"
            )
            st.session_state.quick_last_tmpl_choice = None
    init_log(LOG_PATH)


def sent_today_count() -> int:
    today = date.today().isoformat()
    count = 0
    for row in read_log(LOG_PATH):
        if (row.get("status", "") or "").lower() != "sent":
            continue
        ts = row.get("timestamp", "") or ""
        if ts.startswith(today):
            count += 1
    return count


def attachments_for_sector(cfg: dict[str, Any], sector: str) -> list[tuple, ...]:
    """Return [(source, display_filename), ...].

    Source is bytes when the user uploaded a file this session, or a path
    string when configured locally. email_sender.build_message handles both.
    """
    out: list[tuple] = []
    uploaded_cvs = st.session_state.get("uploaded_cvs", {})
    uploaded_cls = st.session_state.get("uploaded_cls", {})

    cv_bytes = uploaded_cvs.get(sector)
    if cv_bytes:
        out.append((cv_bytes, cfg.get("cv_display_filename") or "CV.pdf"))
    else:
        cv_path = (cfg.get("cv_paths", {}) or {}).get(sector, "").strip()
        if cv_path:
            out.append((cv_path, cfg.get("cv_display_filename") or os.path.basename(cv_path)))

    if cfg.get("attach_cover_letter"):
        cl_bytes = uploaded_cls.get(sector)
        if cl_bytes:
            out.append((cl_bytes, cfg.get("cover_letter_display_filename") or "Cover Letter.pdf"))
        else:
            cl_path = (cfg.get("cover_letter_paths", {}) or {}).get(sector, "").strip()
            if cl_path:
                out.append(
                    (cl_path, cfg.get("cover_letter_display_filename") or os.path.basename(cl_path))
                )
    return out


def build_context(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(row.get("name", "") or "").strip() or "Hiring Team",
        "company": str(row.get("company", "") or "").strip(),
        "role": str(row.get("role", "") or "").strip(),
        "sector": str(row.get("sector", "") or "").strip(),
        "custom1": str(row.get("custom1", "") or "").strip(),
        "custom2": str(row.get("custom2", "") or "").strip(),
        "phone": str(cfg.get("phone", "") or "").strip(),
        "linkedin_url": str(cfg.get("linkedin_url", "") or "").strip(),
    }


def render_sidebar() -> None:
    cfg = st.session_state.config
    with st.sidebar:
        st.header("Gmail")
        if st.session_state.connected:
            st.success(f"Connected as {st.session_state.connected_email}")
            if not CLOUD_MODE and st.button("Disconnect", use_container_width=True):
                st.session_state.sender.disconnect()
                st.session_state.connected = False
                st.session_state.connected_email = ""
                st.rerun()
        elif CLOUD_MODE:
            err = st.session_state.get("gmail_auto_connect_error", "")
            st.error("Gmail auto-connect failed.")
            if err:
                st.caption(err)
            st.caption("Re-run generate_cloud_token.py locally and update the secret.")
        else:
            st.info("Not connected")
            if st.button("Connect Gmail", use_container_width=True, type="primary"):
                with st.spinner("Opening browser for Google sign-in..."):
                    ok, msg = st.session_state.sender.authenticate()
                if ok:
                    st.session_state.connected = True
                    st.session_state.connected_email = st.session_state.sender.user_email or ""
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        st.divider()
        st.header("Sender identity")
        cfg["sender_display_name"] = st.text_input(
            "Display name", value=cfg.get("sender_display_name", "")
        )
        cfg["phone"] = st.text_input("Phone", value=cfg.get("phone", ""))
        cfg["linkedin_url"] = st.text_input("LinkedIn URL", value=cfg.get("linkedin_url", ""))

        st.divider()
        st.header("Attachments")
        cfg["cv_display_filename"] = st.text_input(
            "CV display filename (what the recipient sees)",
            value=cfg.get("cv_display_filename", ""),
        )
        cfg["cover_letter_display_filename"] = st.text_input(
            "Cover letter display filename",
            value=cfg.get("cover_letter_display_filename", ""),
        )
        cfg["attach_cover_letter"] = st.checkbox(
            "Attach cover letter", value=cfg.get("attach_cover_letter", True)
        )

        if CLOUD_MODE:
            with st.expander("📂 CV Library — upload your CVs", expanded=False):
                st.caption(
                    "Give each a friendly name. They appear in the Quick Send tab's "
                    "CV dropdown."
                )
                for i in range(5):
                    name_key = f"cv_lib_name_{i}"
                    file_key = f"cv_lib_file_{i}"
                    name_val = st.text_input(
                        f"Name #{i+1}",
                        value=st.session_state.cv_library_names.get(i, ""),
                        key=name_key,
                        placeholder=f"e.g. Finance CV",
                    )
                    st.session_state.cv_library_names[i] = name_val
                    f_upl = st.file_uploader(
                        f"PDF #{i+1}",
                        type=["pdf"],
                        key=file_key,
                    )
                    if f_upl is not None:
                        st.session_state.cv_library[i] = f_upl.getvalue()
                    if st.session_state.cv_library.get(i):
                        n = st.session_state.cv_library_names.get(i) or f"CV {i+1}"
                        st.caption(f"  ✅ '{n}' loaded")
                    if i < 4:
                        st.divider()

            with st.expander("Upload CV PDFs (per sector — for Bulk Import tab)"):
                st.caption("Files are held in memory only for this session.")
                for s in SECTORS:
                    up = st.file_uploader(
                        f"CV — {s}", type=["pdf"], key=f"cv_upload_{s}"
                    )
                    if up is not None:
                        st.session_state.uploaded_cvs[s] = up.getvalue()
                    if st.session_state.uploaded_cvs.get(s):
                        st.caption(f"✅ CV loaded for {s}")
            with st.expander("Upload cover letter PDFs (per sector)"):
                for s in SECTORS:
                    up = st.file_uploader(
                        f"Cover letter — {s}", type=["pdf"], key=f"cl_upload_{s}"
                    )
                    if up is not None:
                        st.session_state.uploaded_cls[s] = up.getvalue()
                    if st.session_state.uploaded_cls.get(s):
                        st.caption(f"✅ Cover letter loaded for {s}")
        else:
            with st.expander("Per-sector CV paths"):
                for s in SECTORS:
                    cfg["cv_paths"][s] = st.text_input(
                        f"CV — {s}",
                        value=cfg["cv_paths"].get(s, ""),
                        key=f"cv_path_{s}",
                    )
            with st.expander("Per-sector cover letter paths"):
                for s in SECTORS:
                    cfg["cover_letter_paths"][s] = st.text_input(
                        f"Cover letter — {s}",
                        value=cfg["cover_letter_paths"].get(s, ""),
                        key=f"cl_path_{s}",
                    )

        st.divider()
        st.header("Send behavior")
        cfg["bcc_self"] = st.checkbox("BCC myself", value=cfg.get("bcc_self", True))
        col_a, col_b = st.columns(2)
        with col_a:
            cfg["min_delay_sec"] = int(
                st.number_input(
                    "Min delay (sec)",
                    min_value=0,
                    max_value=3600,
                    value=int(cfg.get("min_delay_sec", 45)),
                )
            )
        with col_b:
            cfg["max_delay_sec"] = int(
                st.number_input(
                    "Max delay (sec)",
                    min_value=0,
                    max_value=3600,
                    value=int(cfg.get("max_delay_sec", 120)),
                )
            )
        if cfg["max_delay_sec"] < cfg["min_delay_sec"]:
            st.warning("Max delay is less than min delay — they will be swapped at send time.")
        cfg["daily_cap"] = int(
            st.number_input(
                "Daily cap",
                min_value=1,
                max_value=500,
                value=int(cfg.get("daily_cap", 40)),
            )
        )

        if st.button("Save settings", use_container_width=True):
            save_config(cfg)
            st.success("Settings saved.")

        st.divider()
        st.metric("Sent today", f"{sent_today_count()} / {cfg.get('daily_cap', 40)}")


def preflight_send(
    recipient_email: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, str]],
    cfg: dict[str, Any],
) -> tuple[bool, str]:
    if not st.session_state.connected:
        return False, "Not connected to Gmail."
    if not recipient_email or not EMAIL_RE.match(recipient_email.strip()):
        return False, f"Invalid recipient email: {recipient_email!r}"
    if not (subject or "").strip():
        return False, "Subject is empty."
    if not (html_body or "").strip():
        return False, "Body is empty."
    for source, _ in attachments:
        if isinstance(source, (bytes, bytearray)):
            continue  # uploaded in-memory bytes, no disk path to check
        if source and not os.path.isfile(str(source)):
            return False, f"Attachment not found on disk: {source}"
    if sent_today_count() >= int(cfg.get("daily_cap", 40)):
        return False, "Daily cap reached."
    return True, ""


def _safe_log(entry: dict) -> None:
    """Append a log row, but never let a logging failure break the send."""
    try:
        append_entry(entry, LOG_PATH)
    except Exception as e:
        st.warning(
            f"⚠️ Couldn't log to Google Sheet: **{type(e).__name__}**: {e}\n\n"
            "The email itself was sent successfully (if status='sent' above). "
            "This is a logging-only issue."
        )


def do_send(
    recipient_name: str,
    recipient_email: str,
    company: str,
    role: str,
    sector: str,
    subject: str,
    html_body: str,
    cfg: dict[str, Any],
    attachments: list | None = None,
) -> tuple[bool, str]:
    if attachments is None:
        attachments = attachments_for_sector(cfg, sector)
    ok, msg = preflight_send(recipient_email, subject, html_body, attachments, cfg)

    def _label(att) -> str:
        if isinstance(att[0], (bytes, bytearray)):
            return att[1] or "(uploaded)"
        return str(att[0])

    if not ok:
        _safe_log(
            {
                "timestamp": now_iso(),
                "recipient_name": recipient_name,
                "recipient_email": recipient_email,
                "company": company,
                "role": role,
                "sector": sector,
                "cv_used": ", ".join(_label(a) for a in attachments),
                "subject": subject,
                "status": "skipped",
                "message_id_or_error": msg,
            }
        )
        return False, msg

    bcc = st.session_state.connected_email if cfg.get("bcc_self") else None
    ok, info = st.session_state.sender.send(
        sender_display_name=cfg.get("sender_display_name", ""),
        recipient_email=recipient_email.strip(),
        subject=subject,
        html_body=html_body,
        attachments=attachments,
        bcc=bcc,
        reply_to=st.session_state.connected_email,
    )
    _safe_log(
        {
            "timestamp": now_iso(),
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "company": company,
            "role": role,
            "sector": sector,
            "cv_used": ", ".join(_label(a) for a in attachments),
            "subject": subject,
            "status": "sent" if ok else "failed",
            "message_id_or_error": info,
        }
    )
    return ok, info


def tab_compose() -> None:
    cfg = st.session_state.config
    templates = st.session_state.templates
    st.subheader("Compose a single application")

    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Recipient name", key="cmp_name")
        email = st.text_input("Recipient email", key="cmp_email")
        company = st.text_input("Company", key="cmp_company")
        role = st.text_input("Role", key="cmp_role")
    with c2:
        sector = st.selectbox("Sector", SECTORS, key="cmp_sector")
        template_names = list(templates.keys())
        default_idx = template_names.index(sector) if sector in template_names else 0
        tmpl_name = st.selectbox(
            "Template", template_names, index=default_idx, key="cmp_template"
        )
        custom1 = st.text_input("custom1 (firm-specific hook)", key="cmp_custom1")
        custom2 = st.text_input("custom2 (closing line, optional)", key="cmp_custom2")

    ctx = build_context(
        {
            "name": name,
            "company": company,
            "role": role,
            "sector": sector,
            "custom1": custom1,
            "custom2": custom2,
        },
        cfg,
    )
    base_subject = templates[tmpl_name]["subject"]
    base_body = templates[tmpl_name]["body_html"]

    rendered_subject = render(base_subject, ctx)
    rendered_body = render(base_body, ctx)

    subject = st.text_input("Subject", value=rendered_subject, key="cmp_subject_field")
    body_html = st.text_area("Body (HTML)", value=rendered_body, height=320, key="cmp_body_field")

    attachments = attachments_for_sector(cfg, sector)

    col_a, col_b = st.columns([1, 1])
    with col_a:
        preview_clicked = st.button("Preview", use_container_width=True)
    with col_b:
        send_disabled = not st.session_state.connected
        send_clicked = st.button(
            "Send",
            type="primary",
            use_container_width=True,
            disabled=send_disabled,
            help=("Connect Gmail first" if send_disabled else None),
        )

    if email and already_sent(email, LOG_PATH, company=company or None):
        st.warning(
            f"Heads up: a 'sent' row already exists for {email}"
            + (f" at {company}" if company else "")
            + "."
        )

    if preview_clicked:
        with st.container(border=True):
            st.markdown(
                f"**From:** {cfg.get('sender_display_name','')} "
                f"&lt;{st.session_state.connected_email or '(not connected)'}&gt;"
            )
            st.markdown(f"**To:** {email or '(empty)'}")
            if cfg.get("bcc_self"):
                st.markdown(f"**Bcc:** {st.session_state.connected_email or '(not connected)'}")
            st.markdown(f"**Reply-To:** {st.session_state.connected_email or '(not connected)'}")
            st.markdown(f"**Subject:** {subject}")
            if attachments:
                st.markdown("**Attachments:**")
                for path, display in attachments:
                    exists = "✅" if os.path.isfile(path) else "⚠️ missing"
                    st.markdown(f"- `{display}`  ← `{path}`  ({exists})")
            else:
                st.markdown("**Attachments:** _(none)_")
            st.markdown("---")
            st.markdown(body_html, unsafe_allow_html=True)

    if send_clicked:
        ok, info = do_send(name, email, company, role, sector, subject, body_html, cfg)
        if ok:
            st.success(f"Sent. Message id: {info}")
        else:
            st.error(f"Not sent: {info}")


def tab_bulk() -> None:
    cfg = st.session_state.config
    templates = st.session_state.templates
    st.subheader("Bulk import")

    uploaded = st.file_uploader("CSV or XLSX", type=["csv", "xlsx"], key="bulk_uploader")
    skip_dupes = st.checkbox("Skip duplicates already in send log", value=True, key="bulk_skip")

    required = ["name", "email", "company", "role", "sector"]
    optional = ["template", "custom1", "custom2"]

    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith(".xlsx"):
                df = pd.read_excel(uploaded, engine="openpyxl")
            else:
                df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            return
        df.columns = [str(c).strip().lower() for c in df.columns]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"Missing required columns: {missing}")
            return
        for col in optional:
            if col not in df.columns:
                df[col] = ""
        df = df.fillna("")
        st.session_state.bulk_df = df
        st.dataframe(df, use_container_width=True)

    df = st.session_state.bulk_df
    if df is None or df.empty:
        return

    send_all = st.button(
        "Send all",
        type="primary",
        disabled=not st.session_state.connected,
        help=("Connect Gmail first" if not st.session_state.connected else None),
    )
    if not send_all:
        return

    progress = st.progress(0.0)
    status_line = st.empty()
    results: list[dict[str, str]] = []
    total = len(df)
    cap = int(cfg.get("daily_cap", 40))
    min_d = int(cfg.get("min_delay_sec", 45))
    max_d = int(cfg.get("max_delay_sec", 120))
    if max_d < min_d:
        min_d, max_d = max_d, min_d

    sent_this_run = 0
    rows = df.to_dict("records")
    last_idx = total - 1

    for i, row in enumerate(rows):
        recipient_email = str(row.get("email", "") or "").strip()
        company = str(row.get("company", "") or "").strip()
        sector = str(row.get("sector", "") or "").strip()
        if sector not in SECTORS:
            sector = SECTORS[-1]
        tmpl_name = str(row.get("template", "") or "").strip() or sector
        if tmpl_name not in templates:
            tmpl_name = sector if sector in templates else next(iter(templates))

        status_line.markdown(f"**[{i+1}/{total}]** {recipient_email or '(missing email)'}")

        if sent_today_count() >= cap:
            results.append(
                {"email": recipient_email, "status": "stopped", "info": "Daily cap reached."}
            )
            for j in range(i, total):
                r2 = rows[j]
                results.append(
                    {
                        "email": str(r2.get("email", "")),
                        "status": "skipped",
                        "info": "Daily cap reached.",
                    }
                )
            break

        if skip_dupes and recipient_email and already_sent(
            recipient_email, LOG_PATH, company=company or None
        ):
            results.append(
                {"email": recipient_email, "status": "skipped", "info": "Duplicate."}
            )
            progress.progress((i + 1) / total)
            continue

        ctx = build_context(row, cfg)
        subject = render(templates[tmpl_name]["subject"], ctx)
        body_html = render(templates[tmpl_name]["body_html"], ctx)

        ok, info = do_send(
            str(row.get("name", "")),
            recipient_email,
            company,
            str(row.get("role", "")),
            sector,
            subject,
            body_html,
            cfg,
        )
        results.append(
            {"email": recipient_email, "status": "sent" if ok else "failed", "info": info}
        )
        if ok:
            sent_this_run += 1

        progress.progress((i + 1) / total)

        if i != last_idx and ok:
            delay = random.randint(min_d, max_d) if max_d > 0 else 0
            if delay > 0:
                status_line.markdown(
                    f"**[{i+1}/{total}]** sleeping {delay}s before next send..."
                )
                time.sleep(delay)

    status_line.markdown(f"**Done.** Sent {sent_this_run} this run.")
    st.dataframe(pd.DataFrame(results), use_container_width=True)


def tab_templates() -> None:
    templates = st.session_state.templates
    st.subheader("Templates")

    names = list(templates.keys())
    if not names:
        st.session_state.templates = {k: dict(v) for k, v in DEFAULT_TEMPLATES.items()}
        save_templates(st.session_state.templates, TEMPLATES_PATH)
        st.rerun()
        return

    selected = st.selectbox("Edit template", names, key="tmpl_select")
    subject = st.text_input(
        "Subject", value=templates[selected]["subject"], key=f"tmpl_subject_{selected}"
    )

    if HAVE_QUILL:
        body = st_quill(
            value=templates[selected]["body_html"],
            html=True,
            placeholder=(
                "Edit your template... use {name}, {company}, {role}, {custom1}, {custom2} "
                "as placeholders."
            ),
            toolbar=[
                [{"header": [1, 2, 3, False]}],
                ["bold", "italic", "underline", "strike"],
                [{"color": []}, {"background": []}],
                [{"list": "ordered"}, {"list": "bullet"}],
                [{"align": []}],
                ["link"],
                ["clean"],
            ],
            key=f"tmpl_body_quill_{selected}",
        ) or ""
    else:
        body = st.text_area(
            "Body (HTML)",
            value=templates[selected]["body_html"],
            height=360,
            key=f"tmpl_body_{selected}",
        )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("Save changes", use_container_width=True):
            templates[selected] = {"subject": subject, "body_html": body}
            save_templates(templates, TEMPLATES_PATH)
            st.success(f"Saved '{selected}'.")
    with c2:
        if st.button("Duplicate as new", use_container_width=True):
            base = f"{selected} (copy)"
            new_name = base
            n = 2
            while new_name in templates:
                new_name = f"{selected} (copy {n})"
                n += 1
            templates[new_name] = {"subject": subject, "body_html": body}
            save_templates(templates, TEMPLATES_PATH)
            st.success(f"Created '{new_name}'.")
            st.rerun()
    with c3:
        if st.button(
            "Delete",
            use_container_width=True,
            disabled=len(templates) <= 1,
            help=("Cannot delete the last template" if len(templates) <= 1 else None),
        ):
            del templates[selected]
            save_templates(templates, TEMPLATES_PATH)
            st.success(f"Deleted '{selected}'.")
            st.rerun()
    with c4:
        if st.button("Restore defaults", use_container_width=True):
            st.session_state.templates = {k: dict(v) for k, v in DEFAULT_TEMPLATES.items()}
            save_templates(st.session_state.templates, TEMPLATES_PATH)
            st.success("Defaults restored.")
            st.rerun()

    with st.expander("Create a brand-new template"):
        new_name = st.text_input("New template name", key="tmpl_new_name")
        if st.button("Create", key="tmpl_new_create"):
            if not new_name.strip():
                st.error("Name is empty.")
            elif new_name in templates:
                st.error(f"'{new_name}' already exists.")
            else:
                templates[new_name] = {
                    "subject": "Application: {role} – CA Harsh Agarwal",
                    "body_html": "<p>Dear {name},</p><p>...</p>",
                }
                save_templates(templates, TEMPLATES_PATH)
                st.success(f"Created '{new_name}'.")
                st.rerun()


@st.cache_data
def _sample_recipients_xlsx_bytes() -> bytes:
    """Build a sample recipient list as an Excel file in memory."""
    df = pd.DataFrame(
        [
            {
                "name": "Anika Sharma",
                "email": "anika.sharma@example.com",
                "company": "Apex Capital Partners",
                "role": "Investment Analyst",
                "custom1": "your buy-and-build thesis in Indian healthcare mid-market",
                "custom2": "I am available next Tuesday for a call.",
            },
            {
                "name": "Rohan Mehta",
                "email": "rohan.mehta@example.com",
                "company": "Vertex Strategy Group",
                "role": "Associate Consultant",
                "custom1": "",
                "custom2": "",
            },
            {
                "name": "Priya Iyer",
                "email": "priya.iyer@example.com",
                "company": "LedgerWave Technologies",
                "role": "Senior Finance Analyst",
                "custom1": "scaling the finance function from Series B to D",
                "custom2": "Happy to jump on a quick call this week.",
            },
        ]
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Recipients", index=False)
        ws = writer.sheets["Recipients"]
        for col_idx, col_name in enumerate(df.columns, start=1):
            from openpyxl.utils import get_column_letter
            max_len = max(
                [len(str(col_name))]
                + [len(str(v)) for v in df[col_name].tolist()]
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)
    return buf.getvalue()


@st.cache_data
def _sample_recipients_csv_bytes() -> bytes:
    df = pd.DataFrame(
        [
            {
                "name": "Anika Sharma",
                "email": "anika.sharma@example.com",
                "company": "Apex Capital Partners",
                "role": "Investment Analyst",
                "custom1": "your buy-and-build thesis in Indian healthcare mid-market",
                "custom2": "I am available next Tuesday for a call.",
            },
            {
                "name": "Rohan Mehta",
                "email": "rohan.mehta@example.com",
                "company": "Vertex Strategy Group",
                "role": "Associate Consultant",
                "custom1": "",
                "custom2": "",
            },
            {
                "name": "Priya Iyer",
                "email": "priya.iyer@example.com",
                "company": "LedgerWave Technologies",
                "role": "Senior Finance Analyst",
                "custom1": "scaling the finance function from Series B to D",
                "custom2": "Happy to jump on a quick call this week.",
            },
        ]
    )
    return df.to_csv(index=False).encode("utf-8")


def tab_quick_send() -> None:
    """Simple one-shot bulk send: list + one CV + one template -> sends to all."""
    cfg = st.session_state.config
    st.subheader("Quick Send")
    st.caption(
        "Upload a list, upload one CV, type a message, click Send. "
        "Everyone gets the same template (personalised with their name + company)."
    )

    st.markdown("**Step 1 — Recipient list (CSV or XLSX)**")
    st.caption(
        "Required columns: `name`, `email`, `company`. "
        "Optional: `role`, `custom1`, `custom2`."
    )
    c_xlsx, c_csv, _spacer = st.columns([1, 1, 3])
    with c_xlsx:
        st.download_button(
            "⬇️ Sample Excel",
            data=_sample_recipients_xlsx_bytes(),
            file_name="sample_recipients.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="Download a sample .xlsx with the right columns and 3 example rows.",
        )
    with c_csv:
        st.download_button(
            "⬇️ Sample CSV",
            data=_sample_recipients_csv_bytes(),
            file_name="sample_recipients.csv",
            mime="text/csv",
            use_container_width=True,
            help="Download a sample .csv with the right columns and 3 example rows.",
        )
    uploaded = st.file_uploader("Upload list", type=["csv", "xlsx"], key="quick_uploader")

    # ---- Step 2: pick or upload a CV ----
    st.markdown("**Step 2 — Your CV** (one PDF, attached to every email)")
    library_choices: list[str] = []
    name_to_bytes: dict[str, bytes] = {}
    for i in sorted(st.session_state.cv_library_names.keys()):
        nm = (st.session_state.cv_library_names.get(i) or "").strip()
        bts = st.session_state.cv_library.get(i)
        if nm and bts:
            library_choices.append(nm)
            name_to_bytes[nm] = bts

    upload_new_label = "📤 Upload a new CV..."
    cv_options = library_choices + [upload_new_label]
    if not library_choices:
        st.caption(
            "No CVs in your library yet. Add some in the sidebar (📂 CV Library), "
            "or upload one here for this session."
        )
    cv_choice = st.selectbox("Pick a CV", cv_options, key="quick_cv_choice")

    cv_bytes: bytes | None = None
    if cv_choice == upload_new_label:
        cv_file = st.file_uploader("Upload CV PDF", type=["pdf"], key="quick_cv_upload")
        if cv_file is not None:
            cv_bytes = cv_file.getvalue()
    else:
        cv_bytes = name_to_bytes.get(cv_choice)

    cv_display = st.text_input(
        "Filename recipients see",
        value=cfg.get("cv_display_filename") or (
            f"{cv_choice}.pdf" if cv_choice != upload_new_label else "CV.pdf"
        ),
        key="quick_cv_display",
    )

    # ---- Step 3: pick a template or write custom ----
    st.markdown("**Step 3 — Your message** (pick a template or write your own)")
    st.caption(
        "Placeholders supported: `{name}`, `{company}`, `{role}`, `{custom1}`, `{custom2}`"
    )

    templates = st.session_state.templates
    CUSTOM = "✏️ Custom (write your own)"
    tmpl_options = list(templates.keys()) + [CUSTOM]
    prev_choice = st.session_state.get("quick_last_tmpl_choice")
    default_idx = tmpl_options.index(prev_choice) if prev_choice in tmpl_options else 0

    tmpl_choice = st.selectbox(
        "Template", tmpl_options, index=default_idx, key="quick_tmpl_choice"
    )

    if tmpl_choice != prev_choice and tmpl_choice in templates:
        st.session_state.quick_subject_text = templates[tmpl_choice]["subject"]
        st.session_state.quick_body_initial = templates[tmpl_choice]["body_html"]
        st.session_state.quick_body_key_n += 1
        st.session_state.quick_last_tmpl_choice = tmpl_choice
        st.rerun()
    elif tmpl_choice != prev_choice:
        st.session_state.quick_last_tmpl_choice = tmpl_choice

    subject = st.text_input("Subject", key="quick_subject_text")

    if HAVE_QUILL:
        body = st_quill(
            value=st.session_state.quick_body_initial,
            html=True,
            placeholder=(
                "Write your message... use {name}, {company}, {role}, {custom1}, {custom2} "
                "as placeholders."
            ),
            toolbar=[
                [{"header": [1, 2, 3, False]}],
                ["bold", "italic", "underline", "strike"],
                [{"color": []}, {"background": []}],
                [{"list": "ordered"}, {"list": "bullet"}],
                [{"align": []}],
                ["link"],
                ["clean"],
            ],
            key=f"quick_body_quill_{st.session_state.quick_body_key_n}",
        ) or ""
    else:
        body = st.text_area(
            "Body (HTML)",
            value=st.session_state.quick_body_initial,
            height=280,
            key=f"quick_body_{st.session_state.quick_body_key_n}",
        )

    with st.expander("💾 Save current as a new template"):
        new_tmpl_name = st.text_input("Template name", key="quick_save_tmpl_name")
        if st.button("Save as new template", disabled=not new_tmpl_name.strip()):
            nm = new_tmpl_name.strip()
            if nm in templates:
                st.error(f"'{nm}' already exists. Pick a different name.")
            else:
                templates[nm] = {"subject": subject, "body_html": body}
                save_templates(templates, TEMPLATES_PATH)
                st.success(f"Saved '{nm}'. It now appears in the Template dropdown.")
                st.rerun()

    skip_dupes = st.checkbox(
        "Skip duplicates already in send log", value=True, key="quick_skip"
    )

    if uploaded is None or not cv_bytes:
        st.info("Upload the recipient list and pick (or upload) a CV to continue.")
        return

    try:
        if uploaded.name.lower().endswith(".xlsx"):
            df = pd.read_excel(uploaded, engine="openpyxl")
        else:
            df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read recipient list: {e}")
        return

    df.columns = [str(c).strip().lower() for c in df.columns]
    required = ["name", "email", "company"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Missing required columns: {missing}. Found: {list(df.columns)}")
        return
    for col in ["role", "custom1", "custom2"]:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")

    st.markdown(f"**Preview — {len(df)} recipient(s):**")
    st.dataframe(df, use_container_width=True)

    if len(df) > 0:
        first = df.iloc[0].to_dict()
        ctx = build_context(first, cfg)
        with st.expander(f"Preview email to {first.get('name', '')}"):
            st.markdown(f"**Subject:** {render(subject, ctx)}")
            st.markdown(f"**Attachment:** {cv_display}")
            st.markdown("---")
            st.markdown(render(body, ctx), unsafe_allow_html=True)

    send_clicked = st.button(
        "Send to all",
        type="primary",
        disabled=not st.session_state.connected,
        help=("Connect Gmail first" if not st.session_state.connected else None),
        use_container_width=True,
    )
    if not send_clicked:
        return

    attachments = [(cv_bytes, cv_display)]

    progress = st.progress(0.0)
    status_line = st.empty()
    results: list[dict[str, str]] = []
    total = len(df)
    cap = int(cfg.get("daily_cap", 40))
    min_d = int(cfg.get("min_delay_sec", 45))
    max_d = int(cfg.get("max_delay_sec", 120))
    if max_d < min_d:
        min_d, max_d = max_d, min_d

    rows = df.to_dict("records")
    last_idx = total - 1
    sent_this_run = 0

    for i, row in enumerate(rows):
        recipient_email = str(row.get("email", "") or "").strip()
        company = str(row.get("company", "") or "").strip()
        name = str(row.get("name", "") or "").strip()
        role = str(row.get("role", "") or "").strip()

        status_line.markdown(f"**[{i+1}/{total}]** {recipient_email or '(missing email)'}")

        if sent_today_count() >= cap:
            results.append(
                {"email": recipient_email, "status": "stopped", "info": "Daily cap reached."}
            )
            for j in range(i, total):
                results.append(
                    {
                        "email": str(rows[j].get("email", "")),
                        "status": "skipped",
                        "info": "Daily cap reached.",
                    }
                )
            break

        if skip_dupes and recipient_email and already_sent(
            recipient_email, LOG_PATH, company=company or None
        ):
            results.append(
                {"email": recipient_email, "status": "skipped", "info": "Duplicate."}
            )
            progress.progress((i + 1) / total)
            continue

        ctx = build_context(row, cfg)
        sub = render(subject, ctx)
        bod = render(body, ctx)

        ok, info = do_send(
            name, recipient_email, company, role, "Quick Send",
            sub, bod, cfg, attachments=attachments,
        )
        results.append(
            {"email": recipient_email, "status": "sent" if ok else "failed", "info": info}
        )
        if ok:
            sent_this_run += 1

        progress.progress((i + 1) / total)

        if i != last_idx and ok:
            delay = random.randint(min_d, max_d) if max_d > 0 else 0
            if delay > 0:
                status_line.markdown(
                    f"**[{i+1}/{total}]** sleeping {delay}s before next send..."
                )
                time.sleep(delay)

    status_line.markdown(f"**Done.** Sent {sent_this_run} this run.")
    st.dataframe(pd.DataFrame(results), use_container_width=True)


def tab_followup() -> None:
    """Send one follow-up to people who haven't replied to the first email."""
    cfg = st.session_state.config
    st.subheader("Follow-up")
    st.caption(
        "Find people you've emailed who haven't replied yet, then send them a "
        "single follow-up. Skips anyone already sent a follow-up."
    )

    if not st.session_state.connected:
        st.info("Connect Gmail in the sidebar to use Follow-up.")
        return

    # ---- Step 1: find candidates ----
    st.markdown("**Step 1 — Find people who haven't replied**")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        look_back = int(st.number_input(
            "Look back for replies (days)",
            min_value=1, max_value=365, value=30,
            help="How far back Gmail is searched for replies.",
            key="followup_lookback",
        ))
    with c2:
        min_age = int(st.number_input(
            "Wait at least N days after first email",
            min_value=0, max_value=365, value=3,
            help="Only show people emailed N+ days ago. Default 3 = polite.",
            key="followup_minage",
        ))
    with c3:
        check_clicked = st.button(
            "🔍 Find non-responders",
            type="primary",
            use_container_width=True,
        )

    if check_clicked:
        log_rows = read_log(LOG_PATH)
        primary_sends: dict[str, dict] = {}
        followup_already_sent: set[str] = set()

        for row in log_rows:
            if (row.get("status") or "").lower() != "sent":
                continue
            email = (row.get("recipient_email") or "").strip().lower()
            if not email:
                continue
            sector = row.get("sector") or ""
            if sector == "Follow-up":
                followup_already_sent.add(email)
                continue
            ts = row.get("timestamp") or ""
            if email not in primary_sends or (
                ts and ts < primary_sends[email].get("timestamp", "")
            ):
                primary_sends[email] = {
                    "name": row.get("recipient_name", ""),
                    "company": row.get("company", ""),
                    "role": row.get("role", ""),
                    "subject": row.get("subject", ""),
                    "timestamp": ts,
                }

        candidates_emails = [e for e in primary_sends if e not in followup_already_sent]

        if not candidates_emails:
            st.info(
                "Everyone you've emailed has either replied or already received a follow-up. "
                "Nothing to do here."
            )
            st.session_state.followup_candidates = []
            return

        with st.spinner(
            f"Querying Gmail for replies from {len(candidates_emails)} recipient(s)..."
        ):
            replies = st.session_state.sender.list_replies(
                recipient_emails=candidates_emails,
                days=look_back,
            )
        replied_emails = {
            (r.get("matched_email") or "").strip().lower() for r in (replies or [])
        }

        from datetime import datetime
        now = datetime.now()
        candidates = []
        for email in candidates_emails:
            if email in replied_emails:
                continue
            info = primary_sends[email]
            try:
                ts_dt = datetime.fromisoformat(info["timestamp"])
                days_ago = (now - ts_dt).days
            except Exception:
                days_ago = 0
            if days_ago < min_age:
                continue
            candidates.append({
                "send": True,
                "email": email,
                "name": info["name"],
                "company": info["company"],
                "role": info["role"],
                "sent_at": (info["timestamp"] or "")[:10],
                "days_ago": days_ago,
                "original_subject": info["subject"],
            })

        st.session_state.followup_candidates = candidates
        if not candidates:
            st.info(
                "Found primary sends, but they're either too recent or already replied. "
                f"Try a smaller wait window (currently {min_age} days)."
            )

    candidates = st.session_state.get("followup_candidates", [])
    if not candidates:
        st.caption("Click 'Find non-responders' above to scan.")
        return

    st.markdown(f"**Found {len(candidates)} person(s) needing follow-up. Untick anyone to skip:**")
    df = pd.DataFrame(candidates)
    edited = st.data_editor(
        df,
        column_config={
            "send": st.column_config.CheckboxColumn("Send?"),
            "email": "Email",
            "name": "Name",
            "company": "Company",
            "role": "Role",
            "sent_at": "First sent",
            "days_ago": st.column_config.NumberColumn("Days ago"),
            "original_subject": st.column_config.TextColumn("Original subject", width="medium"),
        },
        use_container_width=True,
        hide_index=True,
        disabled=["email", "name", "company", "role", "sent_at", "days_ago", "original_subject"],
        key="followup_editor",
    )

    to_send = edited[edited["send"]].to_dict("records")

    # ---- Step 2: CV ----
    st.markdown("**Step 2 — CV (optional for follow-up)**")
    library_choices: list[str] = []
    name_to_bytes: dict[str, bytes] = {}
    for i in sorted(st.session_state.cv_library_names.keys()):
        nm = (st.session_state.cv_library_names.get(i) or "").strip()
        bts = st.session_state.cv_library.get(i)
        if nm and bts:
            library_choices.append(nm)
            name_to_bytes[nm] = bts
    NO_CV = "🚫 No CV (text-only follow-up)"
    UPLOAD_NEW = "📤 Upload a new CV..."
    cv_options = library_choices + [NO_CV, UPLOAD_NEW]
    cv_choice = st.selectbox("Pick a CV", cv_options, key="followup_cv_choice")
    cv_bytes: bytes | None = None
    if cv_choice == UPLOAD_NEW:
        f_upl = st.file_uploader("Upload CV PDF", type=["pdf"], key="followup_cv_upload")
        if f_upl is not None:
            cv_bytes = f_upl.getvalue()
    elif cv_choice != NO_CV:
        cv_bytes = name_to_bytes.get(cv_choice)
    cv_display = st.text_input(
        "Filename recipients see",
        value=cfg.get("cv_display_filename") or "CV.pdf",
        key="followup_cv_display",
        disabled=(cv_choice == NO_CV),
    )

    # ---- Step 3: message ----
    st.markdown("**Step 3 — Follow-up message** (placeholders: `{name}`, `{company}`, `{role}`)")

    templates = st.session_state.templates
    DEFAULT_FU = "🔄 Default follow-up"
    CUSTOM = "✏️ Custom (write your own)"
    tmpl_options = [DEFAULT_FU] + list(templates.keys()) + [CUSTOM]
    prev_choice = st.session_state.followup_last_tmpl_choice
    default_idx = tmpl_options.index(prev_choice) if prev_choice in tmpl_options else 0
    tmpl_choice = st.selectbox(
        "Template", tmpl_options, index=default_idx, key="followup_tmpl_choice"
    )

    if tmpl_choice != prev_choice:
        if tmpl_choice == DEFAULT_FU:
            st.session_state.followup_subject_text = "Following up: {role} at {company}"
            st.session_state.followup_body_initial = (
                "<p>Dear {name},</p>"
                "<p>I hope this note finds you well. I wanted to follow up on my earlier "
                "email about the <strong>{role}</strong> opportunity at "
                "<strong>{company}</strong>.</p>"
                "<p>I understand things get busy, and I would be happy to share any "
                "additional information that would help.</p>"
                "<p>Looking forward to hearing from you.</p>"
                "<p>Warm regards,<br><strong>CA Harsh Agarwal</strong></p>"
            )
            st.session_state.followup_body_key_n += 1
        elif tmpl_choice in templates:
            st.session_state.followup_subject_text = templates[tmpl_choice]["subject"]
            st.session_state.followup_body_initial = templates[tmpl_choice]["body_html"]
            st.session_state.followup_body_key_n += 1
        st.session_state.followup_last_tmpl_choice = tmpl_choice
        st.rerun()

    subject = st.text_input("Subject", key="followup_subject_text")

    if HAVE_QUILL:
        body = st_quill(
            value=st.session_state.followup_body_initial,
            html=True,
            placeholder="Write your follow-up...",
            toolbar=[
                [{"header": [1, 2, 3, False]}],
                ["bold", "italic", "underline", "strike"],
                [{"color": []}, {"background": []}],
                [{"list": "ordered"}, {"list": "bullet"}],
                [{"align": []}],
                ["link"],
                ["clean"],
            ],
            key=f"followup_body_quill_{st.session_state.followup_body_key_n}",
        ) or ""
    else:
        body = st.text_area(
            "Body (HTML)",
            value=st.session_state.followup_body_initial,
            height=280,
            key=f"followup_body_{st.session_state.followup_body_key_n}",
        )

    # ---- Step 4: send ----
    n_selected = len(to_send)
    st.markdown(f"**Step 4 — Send to {n_selected} selected**")

    send_clicked = st.button(
        f"Send follow-up to {n_selected} selected",
        type="primary",
        use_container_width=True,
        disabled=(n_selected == 0),
    )
    if not send_clicked:
        return

    attachments = [(cv_bytes, cv_display)] if cv_bytes else []
    progress = st.progress(0.0)
    status_line = st.empty()
    results: list[dict[str, str]] = []
    cap = int(cfg.get("daily_cap", 40))
    min_d = int(cfg.get("min_delay_sec", 45))
    max_d = int(cfg.get("max_delay_sec", 120))
    if max_d < min_d:
        min_d, max_d = max_d, min_d
    total = n_selected
    last_idx = total - 1
    sent_this_run = 0

    for i, row in enumerate(to_send):
        recipient_email = str(row.get("email", "") or "").strip()
        company = str(row.get("company", "") or "").strip()
        name = str(row.get("name", "") or "").strip()
        role = str(row.get("role", "") or "").strip()

        status_line.markdown(f"**[{i+1}/{total}]** {recipient_email}")

        if sent_today_count() >= cap:
            for j in range(i, total):
                results.append({
                    "email": str(to_send[j].get("email", "")),
                    "status": "skipped", "info": "Daily cap reached.",
                })
            break

        ctx = build_context({
            "name": name, "company": company, "role": role, "sector": "Follow-up",
        }, cfg)
        sub = render(subject, ctx)
        bod = render(body, ctx)

        ok, info = do_send(
            name, recipient_email, company, role, "Follow-up",
            sub, bod, cfg, attachments=attachments,
        )
        results.append({
            "email": recipient_email,
            "status": "sent" if ok else "failed",
            "info": info,
        })
        if ok:
            sent_this_run += 1
        progress.progress((i + 1) / total)

        if i != last_idx and ok:
            delay = random.randint(min_d, max_d) if max_d > 0 else 0
            if delay > 0:
                status_line.markdown(
                    f"**[{i+1}/{total}]** sleeping {delay}s before next..."
                )
                time.sleep(delay)

    status_line.markdown(f"**Done.** Sent {sent_this_run} follow-up(s) this run.")
    st.dataframe(pd.DataFrame(results), use_container_width=True)
    st.session_state.followup_candidates = []  # force re-scan next time


def tab_replies() -> None:
    st.subheader("Replies from people I've applied to")
    if not st.session_state.connected:
        st.info("Connect Gmail in the sidebar to fetch replies.")
        return

    log_rows = read_log(LOG_PATH)
    sent_index: dict[str, dict[str, str]] = {}
    for row in log_rows:
        if (row.get("status", "") or "").lower() != "sent":
            continue
        email = (row.get("recipient_email", "") or "").strip().lower()
        if email and email not in sent_index:
            sent_index[email] = {
                "name": row.get("recipient_name", ""),
                "company": row.get("company", ""),
                "role": row.get("role", ""),
                "sector": row.get("sector", ""),
                "sent_at": row.get("timestamp", ""),
            }

    if not sent_index:
        st.info("No 'sent' entries in the log yet — nothing to match against.")
        return

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = int(
            st.number_input(
                "Look back (days)", min_value=1, max_value=365, value=30, key="reply_days"
            )
        )
    with c2:
        fetch = st.button("Refresh", type="primary", use_container_width=True)
    with c3:
        st.caption(
            f"Matching against {len(sent_index)} unique recipient(s) from the send log."
        )

    cache_key = f"replies_cache_{days}"
    if fetch or cache_key not in st.session_state:
        with st.spinner("Searching Gmail inbox..."):
            replies = st.session_state.sender.list_replies(
                recipient_emails=list(sent_index.keys()),
                days=days,
            )
        st.session_state[cache_key] = replies

    replies = st.session_state.get(cache_key, [])
    if not replies:
        st.success("No replies found in the look-back window. (Or refresh to check again.)")
        return

    rows = []
    for r in replies:
        meta = sent_index.get(r.get("matched_email", ""), {})
        rows.append(
            {
                "Date": r.get("date", ""),
                "From": r.get("from", ""),
                "Subject": r.get("subject", ""),
                "Snippet": r.get("snippet", ""),
                "Applied as": meta.get("name", ""),
                "Company": meta.get("company", ""),
                "Role": meta.get("role", ""),
                "Sector": meta.get("sector", ""),
                "Sent at": meta.get("sent_at", ""),
                "Open": f"https://mail.google.com/mail/u/0/#inbox/{r.get('thread_id','')}",
            }
        )
    df = pd.DataFrame(rows)

    q = st.text_input("Search (from / subject / company)", key="reply_search").strip().lower()
    if q:
        mask = (
            df["From"].str.lower().str.contains(q, na=False)
            | df["Subject"].str.lower().str.contains(q, na=False)
            | df["Company"].str.lower().str.contains(q, na=False)
        )
        df = df[mask]

    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "Open": st.column_config.LinkColumn("Open in Gmail", display_text="↗ open"),
            "Snippet": st.column_config.TextColumn(width="large"),
        },
        hide_index=True,
    )


def tab_log() -> None:
    st.subheader("Send log")
    rows = read_log(LOG_PATH)
    if not rows:
        st.info("No log entries yet.")
        return
    df = pd.DataFrame(rows)

    statuses = sorted([s for s in df["status"].unique().tolist() if s])
    chosen = st.multiselect("Filter by status", statuses, default=statuses, key="log_status")
    q = st.text_input("Search (name, email, company)", key="log_search").strip().lower()

    filtered = df[df["status"].isin(chosen)] if chosen else df
    if q:
        mask = (
            filtered["recipient_name"].str.lower().str.contains(q, na=False)
            | filtered["recipient_email"].str.lower().str.contains(q, na=False)
            | filtered["company"].str.lower().str.contains(q, na=False)
        )
        filtered = filtered[mask]

    st.dataframe(filtered, use_container_width=True)

    csv_bytes = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name="send_log_filtered.csv",
        mime="text/csv",
    )


def main() -> None:
    st.set_page_config(page_title="Job Application Sender", page_icon="📧", layout="wide")
    require_login()
    ensure_state()
    auto_connect_gmail()
    render_sidebar()

    st.title("Job Application Sender")
    st.caption(
        "Local-only Gmail sender for personalised job applications. "
        "Templates, attachments, delays, and a send log — all on disk."
    )

    t_quick, t_fu, t1, t2, t3, t4, t5 = st.tabs(
        [
            "🚀 Quick Send",
            "🔄 Follow-up",
            "📝 Compose",
            "📂 Bulk Import",
            "📋 Templates",
            "📊 Send Log",
            "📬 Replies",
        ]
    )
    with t_quick:
        tab_quick_send()
    with t_fu:
        tab_followup()
    with t1:
        tab_compose()
    with t2:
        tab_bulk()
    with t3:
        tab_templates()
    with t4:
        tab_log()
    with t5:
        tab_replies()


if __name__ == "__main__":
    main()
