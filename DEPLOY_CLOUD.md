# Deploy to Streamlit Cloud — step-by-step

This puts your local app on the internet at a `https://<name>.streamlit.app` URL with a username/password login. Send log persists to a Google Sheet you own. CVs are uploaded each session (they never live on the server's disk).

Estimated time: **45 minutes** the first time. After that, redeploying takes seconds.

You'll do work in **five** places:
1. **GitHub** — host your code
2. **Google Cloud** — service account for the Sheet
3. **Google Sheets** — the actual log spreadsheet
4. **Your PC** — generate the Gmail refresh token
5. **Streamlit Cloud** — deploy and paste secrets

---

## 0. Before you start

- ✅ `credentials.json` is already in the project folder (Desktop OAuth client — what you have works).
- ✅ The app works locally (you've seen the UI at `http://localhost:8501`).
- ✅ You have a GitHub account (or you're about to create one at [github.com/signup](https://github.com/signup)).

---

## 1. Push the code to a private GitHub repo

```powershell
cd "C:\Users\91930\Documents\Documents\Harsh\Claude Code\job_app_sender"
git init
git add .
git status            # ← confirm credentials.json, token.json, config.json, templates.json, cvs/, logs/ are NOT listed
git commit -m "Initial commit"
```

Then on github.com:
- **New repository** → name it `job-app-sender` (or whatever) → set to **Private** → don't add README/license (the repo already has files) → **Create**.

Copy the two commands GitHub shows under *…or push an existing repository*, e.g.:
```powershell
git remote add origin https://github.com/<your-username>/job-app-sender.git
git branch -M main
git push -u origin main
```

You'll be asked to log in to GitHub the first time.

> **Important:** double-check `git status` shows a clean tree and that `credentials.json`, `token.json`, and your CVs are gone from the repo on GitHub. The `.gitignore` handles this — but verify.

---

## 2. Create a Google Sheet for the send log

1. Go to [sheets.google.com](https://sheets.google.com) → **Blank**.
2. Rename it to e.g. *Job App Sender Log*.
3. Copy the **spreadsheet ID** from the URL (`https://docs.google.com/spreadsheets/d/<THIS_PART>/edit`).
4. Leave it open — you'll share it with a service account in step 4.

---

## 3. Create a Google Cloud service account (so the app can write to that sheet)

In the same Google Cloud project where you set up the Gmail OAuth client:

1. [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → **Library** → enable **Google Sheets API**.
2. APIs & Services → **Credentials** → **Create Credentials** → **Service account**.
3. Name it e.g. `job-app-sender-sheets` → **Create and continue** → Role: **Editor** (or leave blank) → **Done**.
4. Click the service account row → **Keys** tab → **Add Key** → **Create new key** → **JSON** → downloads a `.json` file. **Keep this file safe** — it's a private key.

Now share the sheet with the service account:
- Open the JSON file you downloaded — find the `client_email` field, e.g. `job-app-sender-sheets@your-project.iam.gserviceaccount.com`.
- In your Google Sheet → **Share** → paste that email → role **Editor** → **Send** (uncheck "notify").

---

## 4. Generate the Gmail refresh-token bundle (one-time, on your PC)

In your project folder, with the venv active:
```powershell
.\.venv\Scripts\Activate.ps1
python generate_cloud_token.py
```

This opens your browser → sign in with the **Gmail you want to send from** → approve both *Send email* and *Read email*. The script then prints a TOML block starting with `[gmail_token]`. **Copy the entire block** — you'll paste it into Streamlit secrets next.

---

## 5. Deploy to Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **Sign in with GitHub**.
2. **New app** → pick your `job-app-sender` repo → branch `main` → main file path `app.py` → app URL: choose something like `harsh-jobsender` → **Deploy!**

The build will start. It may **fail on the first run** because secrets aren't set yet — that's fine, you'll fix it next.

3. While it builds, click **Settings** (top right) → **Secrets**. Paste in this block, filling in your values:

```toml
app_password = "PICK_A_STRONG_PASSWORD"
gsheets_sheet_id = "PASTE_THE_SHEET_ID_FROM_STEP_2"

[gmail_token]
# ← paste the entire block from generate_cloud_token.py here
# (replaces this comment and lives under the [gmail_token] header)

[gsheets_service_account]
# ← paste the contents of the service-account JSON from step 3 here
# but in TOML format. Convert it like this:
# Open the JSON file → for each field, write:  key = "value"
# Multi-line "private_key" → use triple quotes:
# private_key = """-----BEGIN PRIVATE KEY-----
# ...lines...
# -----END PRIVATE KEY-----
# """
```

> **Tip for the service account TOML:** the easiest way to convert the JSON is to ask any LLM "convert this JSON to TOML" — paste the JSON, it gives you the TOML block.

4. **Save** secrets. The app reboots automatically and should come up clean. If not, click **Manage app** → **Reboot**.

5. Go to your app URL (e.g. `https://harsh-jobsender.streamlit.app`) → enter the password → you should see the UI. Sidebar should say "Connected as your-gmail@gmail.com" (auto-connected via the secret).

6. **Upload your CVs** — sidebar → "Upload CV PDFs (per sector)" expander → upload one PDF per sector you'll use. Same for cover letters. These live in browser memory only.

7. Compose tab → fill recipient → Preview → Send. Check the Google Sheet — a new row should appear.

---

## 6. Day-to-day

- Open `https://<your-app>.streamlit.app` from any device → enter password → upload CVs for the session → send.
- Streamlit Cloud sleeps your app after ~7 days of inactivity. First load after sleep takes 30–60s to wake up; that's normal.
- The Google Sheet is the source of truth for the send log. Edit it directly if you ever need to.

---

## Troubleshooting

- **"Gmail auto-connect failed"** in the sidebar → your refresh token is stale or the secret is malformed. Re-run `generate_cloud_token.py` locally and replace the `[gmail_token]` block.
- **"APIError: The caller does not have permission"** when writing to the Sheet → you forgot to share the Sheet with the service-account email (step 3 final substep).
- **Login screen never appears** → you didn't set `app_password` in secrets. Without it, the app runs unprotected (don't do that — anyone with the URL gets in).
- **Sheet rows look weird** (commas in places they shouldn't be) → don't worry, `gspread` quotes properly. The Sheet is meant to be read, not edited by hand.
