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

## 8. OAuth token expiry — one-time fix to stop weekly re-auth

By default, OAuth apps in "Testing" mode (where Google places yours after step 2) have a **7-day refresh-token lifetime**. If you don't use the app for a week, the next launch fails with "Gmail auto-connect failed" and you have to re-mint the token.

**The permanent fix is to publish the app.** This sounds scary but for personal use it requires no verification:

1. [console.cloud.google.com](https://console.cloud.google.com) → pick your project (the one called *Gmail API* in your case) → **APIs & Services** → **OAuth consent screen**.
2. You'll see *Publishing status: Testing*. Click **Publish App**.
3. A dialog appears:
   - If your app uses **only** non-sensitive scopes → it's published instantly, you're done.
   - If your scopes include **sensitive** ones (`gmail.send`, `gmail.readonly` both qualify) → Google asks if you want to submit for verification. **You don't have to.** The warning screen recipients see during sign-in just says "Google hasn't verified this app" — you click *Advanced → Continue* once and it works for the lifetime of your account.
4. Status switches to **In production**. Refresh tokens now last indefinitely.

You don't need to submit for verification unless you plan to share the app with others (and even then, it works for unverified users with the one-time warning click).

After publishing:
- Re-run `python generate_cloud_token.py` once locally to mint a fresh token under the new mode
- Paste the new `[gmail_token]` block into Streamlit Cloud → Settings → Secrets
- Done — no more weekly expiry

## 9. Send-time scheduler (optional, ~10 min setup)

The Quick Send and Follow-up tabs have a **📅 Schedule for later** button. To make it actually fire at the scheduled time, you need to set up a free GitHub Actions cron that runs `scheduler_runner.py` every 15 minutes.

### How it works
- When you click **Schedule for later**, the app writes the entire batch (recipients + subject + body + CV as chunked base64) to a `Queue` worksheet in your Google Sheet.
- A GitHub Actions workflow (`.github/workflows/scheduled-sender.yml`) runs every 15 min, reads the Queue, finds anything whose `scheduled_at` is in the past, and sends.
- Status updates land in the Sheet's Queue worksheet (`pending` → `running` → `sent`/`failed`).

### One-time setup

1. Go to **github.com/harsh13agrawal-oss/job-app-sender → Settings → Secrets and variables → Actions → New repository secret** and add three secrets:

   | Name | Value |
   |---|---|
   | `GMAIL_TOKEN_JSON` | Paste your `token.json` content (the JSON file — not the TOML block). You can also generate it again with `python generate_cloud_token.py` and read the JSON before TOML conversion. |
   | `GSHEETS_SA_JSON` | Paste the contents of your service-account JSON (the original `engaged-ground-*.json` file). |
   | `GSHEETS_SHEET_ID` | The sheet ID — same value as in your Streamlit Cloud secret `gsheets_sheet_id`. |

2. Make sure the workflow is enabled. Go to the **Actions** tab on GitHub; if it asks "I understand my workflows, go ahead and enable them" → click that. The first cron run will fire within 15 min.

3. Test it: in the app, schedule a send for ~5 min in the future to your own email. Within ~15 min you should see:
   - The Sheet's Queue worksheet row flip from `pending` → `sent`
   - The email arrives in your Gmail Sent and recipient's inbox

### Notes

- **Free tier coverage** — GitHub Actions gives 2,000 free minutes/month for private repos and unlimited for public repos. Each scheduler run takes < 1 min, so even for a public repo this is essentially free.
- **CV size** — the queue stores the CV as base64 across 8 cells of 35 KB each, so any CV up to ~280 KB works. Most PDFs fit.
- **Reliability** — GitHub may delay cron runs by up to 15 min when busy. So a "send at 9:00" may actually fire 9:00-9:30. Treat scheduled time as a window, not a precise minute.
- **Manual trigger** — go to GitHub → Actions → Scheduled sender → Run workflow to fire the runner immediately without waiting for the cron.
- **Cancel a queued job** — open the Queue worksheet, set `status` to `cancelled` for that row.

## 10. Reply categoriser

The **📬 Replies** tab now classifies each inbound reply into one of: **Interview**, **Info request**, **Rejection**, **Forwarded**, **Auto-reply**, or **Other** — keyword-based rules in `reply_classifier.py`. A summary line above the table shows counts ("4 Interview · 2 Info request · 11 Rejection"), and a Category filter lets you drill in.

Categories are recomputed on every refresh, not stored. To tune the rules (add a keyword, fix a misclassification), edit `reply_classifier.py` and push.

## 11. Troubleshooting

- **"credentials.json not found"** — You haven't completed the OAuth setup in §2, or the file is in the wrong folder. It must be next to `app.py`.
- **Browser opens but says "Access blocked: ... has not completed verification"** — Your Gmail address is not on the *Test users* list. Cloud Console → OAuth consent screen → Test users → Add users.
- **"invalid_grant" / refresh failed** — Delete `token.json` and click *Connect Gmail* again.
- **Daily cap reached but I want to send more** — Increase the cap in the sidebar (max 500), or wait until tomorrow.
- **Attachment not found on disk** — The CV or cover letter path in the sidebar is wrong, or the file was moved. Pre-flight catches this before sending.
- **Bulk send stopped early** — Either the daily cap was hit, or a send errored and was logged with `status=failed`. Check `logs/send_log.csv`.
- **Email shows my Gmail address even though I set a display name** — Gmail enforces the authenticated address in the `From` header; the display name is shown, but the address is fixed to the connected account.
