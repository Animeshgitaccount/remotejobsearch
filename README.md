# Remote Job Digest

Emails you a daily digest of remote **consultant / business analyst / strategy /
ops / analytics** roles across **US, Europe, ANZ, and worldwide**. Runs free on
GitHub Actions, sends via Gmail.

Sources: Remotive, RemoteOK, Jobicy, Himalayas.

---

## One-time setup (~15 min)

### 1. Create a Gmail App Password
The digest logs into Gmail using an **app password**, not your normal password.

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create one named "job-digest" → copy the 16-character code.

### 2. Put the code on GitHub
1. Create a **new private repo** on GitHub, e.g. `remote-job-digest`.
2. Upload these files (`digest.py`, `seen_jobs.json`, `README.md`, and the
   `.github/workflows/daily-digest.yml` folder).
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
   Add three secrets:
   | Name             | Value                                  |
   |------------------|----------------------------------------|
   | `GMAIL_USER`     | your.email@gmail.com                   |
   | `GMAIL_APP_PASS` | the 16-char app password (no spaces)   |
   | `MAIL_TO`        | where to receive it (can be same email)|

### 3. Test it now
Repo → **Actions** tab → "Daily Remote Job Digest" → **Run workflow**.
Check your inbox in ~1 minute. The first run emails everything matching today;
after that you only get *new* roles.

### 4. Done
It now runs automatically every day at **07:30 IST**. To change the time, edit
the `cron` line in the workflow (it's in UTC — 02:00 UTC = 07:30 IST).

---

## Tuning

- **Too many / too few jobs:** edit `INCLUDE_KEYWORDS` / `EXCLUDE_KEYWORDS` in
  `digest.py`.
- **Different regions:** edit `REGION_TERMS`.
- **Add a source:** write a `fetch_x()` returning the normalized dict and add it
  to `FETCHERS`.
