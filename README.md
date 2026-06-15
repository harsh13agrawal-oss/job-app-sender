# Job Application Sender

A small local Streamlit app that sends personalised job-application emails through your own Gmail account using the Gmail API. Designed for sending CV + cover letter to recruiters and hiring teams across multiple sectors (Finance/PE/IB, Consulting, Tech/Corporate Finance, General).

Everything is local: templates, configuration, and the send log live on disk in this folder. No emails are sent except through your authenticated Gmail account.

---

## 1. Install

```powershell
cd job_app_sender
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell. For cmd.exe use: .venv\Scripts\activate.bat
pip install -r requirements.txt
```

Python 3.10 or newer is required.

---

## 2. Google Cloud OAuth setup (one-time)

The app talks to Gmail via the Gmail API, not SMTP. You will need a `credentials.json` file from a Google Cloud project that you own. This is the one part the app cannot automate.

1. **Create a project** at [console.cloud.google.com](https://console.cloud.google.com/).
2. **Enable the Gmail API**: in the Cloud Console, search "Gmail API" and click *Enable*.
3. **Configure the OAuth consent screen**:
   - User type: **External**.
   - App name, support email, developer contact: your own details.
   - On the *Test users* page, **add your own Gmail address as a Test user**. While the app is in Testing mode, only listed test users can use it — which is fine since you are the only user.
   - Scopes: you do not need to add scopes manually here; the app requests them at runtime.
4. **Create an OAuth client ID**:
   - APIs & Services → *Credentials* → *Create Credentials* → *OAuth client ID*.
   - Application type: **Desktop app**.
   - Download the JSON file and save it as **`credentials.json`** in this `job_app_sender/` folder.

The first time you click *Connect Gmail* in the app, a browser tab will open, you'll sign in with the same Gmail you added as a test user, and approve the requested scopes (`gmail.send` and `gmail.readonly`). A `token.json` file will be saved next to `credentials.json` so you don't need to repeat this — until the refresh token expires (then the app will prompt you again).

---

## 3. Place your CV and cover letter PDFs

Drop your PDFs anywhere on disk — typically inside `cvs/`:

```
cvs/
  Harsh - Finance PE IB.pdf
  Harsh - Consulting.pdf
  Harsh - Tech CorpFin.pdf
  Harsh - General.pdf
  cover - Finance PE IB.pdf
  ...
```

You will paste the full file paths into the app sidebar (per-sector CV path and per-sector cover letter path). The recipient never sees these paths — only the **display filename** you set in the sidebar (e.g. `Harsh Agarwal - CV.pdf`).

---

## 4. Run

```powershell
streamlit run app.py
```

A browser tab opens at `http://localhost:8501`.

### First-run walkthrough

1. **Sidebar → Connect Gmail.** Browser tab opens; sign in; approve. Status flips to "Connected as your@gmail.com".
2. **Fill in sender identity** (display name, phone, LinkedIn URL).
3. **Paste CV / cover letter paths** for each sector. Set the display filenames you want recipients to see.
4. **Set send behavior**: BCC self (recommended), min/max delay seconds, daily cap.
5. **Click Save settings.** A `config.json` is written next to `app.py`.
6. **Compose tab → fill recipient details → Preview → Send.** A row is appended to `logs/send_log.csv`.
7. For bulk: prepare a CSV using the columns below, upload it in the **Bulk Import** tab, and click **Send all**. The app sleeps a randomised amount between sends and stops cleanly at the daily cap.
8. **Replies tab** — once you've sent a few applications, the **📬 Replies** tab will search your Gmail inbox for messages from anyone in the send log. Pick a look-back window (default 30 days), click **Refresh**, and the table shows each reply alongside the company/role you applied for. Click *↗ open* to jump to the thread in Gmail.

---

## 5. CSV column reference

The bulk-import file (CSV or XLSX) must have these columns. Column names are lowercased on load, so casing doesn't matter.

| Column      | Required | Notes |
|-------------|----------|-------|
| `name`      | Yes      | Recipient's name (used for `{name}`). |
| `email`     | Yes      | Recipient's email address. |
| `company`   | Yes      | Used for `{company}` and duplicate detection. |
| `role`      | Yes      | Used for `{role}` and the subject line. |
| `sector`    | Yes      | One of: `Finance / PE / IB`, `Consulting`, `Tech / Corporate Finance`, `General / Other`. Decides which CV/cover letter is attached. |
| `template`  | No       | Template name to use. Defaults to the `sector` value. |
| `custom1`   | No       | Firm-specific hook (e.g. a thesis, a deal, a person). |
| `custom2`   | No       | Closing line / availability note. |

See `sample_recipients.csv` for a working example.

---

## 6. Deliverability tips

- Keep daily volume well under Gmail's daily limit (the app's default cap of 40 is conservative).
- Always BCC yourself so you have an outbound copy in your Sent folder thread.
- Keep the body plain — the app deliberately ships no tracking pixels, no images, no marketing footer.
- Randomised delays (default 45–120s between sends) help avoid being flagged as bulk.
- The app always sends multipart text + HTML — never HTML-only.

---

## 7. Project structure

```
job_app_sender/
├── app.py                  # Streamlit entrypoint (sidebar + 4 tabs)
├── email_sender.py         # GmailSender — OAuth + send
├── template_manager.py     # Templates + placeholder rendering
├── log_manager.py          # CSV-backed send log
├── config.json             # Created on first save in the sidebar
├── templates.json          # Created on first run; editable in the UI
├── credentials.json        # You supply this (Google Cloud OAuth client)
├── token.json              # Created after first Gmail connect
├── requirements.txt
├── README.md
├── sample_recipients.csv   # Example bulk file
├── cvs/                    # Your CV PDFs go here
└── logs/
    └── send_log.csv        # Append-only log of every send / skip / failure
```

---

## 8. Troubleshooting

- **"credentials.json not found"** — You haven't completed the OAuth setup in §2, or the file is in the wrong folder. It must be next to `app.py`.
- **Browser opens but says "Access blocked: ... has not completed verification"** — Your Gmail address is not on the *Test users* list. Cloud Console → OAuth consent screen → Test users → Add users.
- **"invalid_grant" / refresh failed** — Delete `token.json` and click *Connect Gmail* again.
- **Daily cap reached but I want to send more** — Increase the cap in the sidebar (max 500), or wait until tomorrow.
- **Attachment not found on disk** — The CV or cover letter path in the sidebar is wrong, or the file was moved. Pre-flight catches this before sending.
- **Bulk send stopped early** — Either the daily cap was hit, or a send errored and was logged with `status=failed`. Check `logs/send_log.csv`.
- **Email shows my Gmail address even though I set a display name** — Gmail enforces the authenticated address in the `From` header; the display name is shown, but the address is fixed to the connected account.
