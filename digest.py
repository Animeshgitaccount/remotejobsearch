#!/usr/bin/env python3
"""
Daily remote-job digest.
Pulls consultant / business-analyst / strategy / ops / analytics roles from
free remote-job APIs, filters to US / Europe / ANZ (or worldwide), dedupes
against previously sent jobs, and emails a formatted digest via Gmail SMTP.

Config via environment variables (set as GitHub Actions secrets):
  GMAIL_USER      - your gmail address (also the recipient by default)
  GMAIL_APP_PASS  - 16-char Gmail app password (NOT your login password)
  MAIL_TO         - optional; recipient if different from GMAIL_USER
"""

import os
import json
import smtplib
import datetime
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------------------------------------------------------------------
# 1. CONFIG
# ---------------------------------------------------------------------------

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
MAIL_TO = os.environ.get("MAIL_TO", GMAIL_USER)

SEEN_FILE = "seen_jobs.json"          # persisted across runs by the workflow
MAX_SEEN = 4000                       # cap the memory file size
MAX_JOBS_IN_EMAIL = 40                # don't send a wall of text

# Broad match: consultant / BA / strategy / ops / analytics
INCLUDE_KEYWORDS = [
    "business analyst", "business analysis", "consultant", "consulting",
    "strategy", "strategic", "operations", "ops ", "operational",
    "analytics", "data analyst", "insights analyst",
    "program manager", "project manager", "product operations",
    "revenue operations", "revops", "biz ops", "bizops",
    "management consultant", "solutions consultant",
]

# Cut the obvious noise
EXCLUDE_KEYWORDS = [
    "software engineer", "software developer", "backend", "frontend",
    "full stack", "full-stack", "devops engineer", "sre",
    "sales development", "sdr ", "account executive", "cold calling",
    "warehouse", "driver", "nurse", "customer support agent",
    "senior software", "staff engineer", "android", "ios developer",
]

# Region gate: keep if any of these appear in location/region/candidate_required
REGION_TERMS = [
    # global / open
    "worldwide", "anywhere", "global", "remote",
    # US / North America
    "usa", "u.s.", "united states", "america", "north america", "canada",
    # Europe
    "europe", "european", "emea", "uk", "united kingdom", "england",
    "ireland", "germany", "france", "netherlands", "spain", "portugal",
    "poland", "sweden", "denmark", "norway", "finland", "italy", "belgium",
    "switzerland", "austria", "czech", "romania", "estonia", "greece",
    # ANZ
    "australia", "new zealand", "anz", "oceania", "apac",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (remote-job-digest/1.0)"}
TIMEOUT = 25


# ---------------------------------------------------------------------------
# 2. FETCHERS  (each returns a list of normalized dicts)
#    normalized: {id, title, company, location, url, source, tags}
# ---------------------------------------------------------------------------

def _get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_remotive():
    out = []
    try:
        data = _get_json("https://remotive.com/api/remote-jobs?limit=200")
        for j in data.get("jobs", []):
            out.append({
                "id": f"remotive-{j.get('id')}",
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "location": j.get("candidate_required_location", ""),
                "url": j.get("url", ""),
                "source": "Remotive",
                "tags": " ".join(j.get("tags", []) or []),
            })
    except Exception as e:
        print("Remotive fetch failed:", e)
    return out


def fetch_remoteok():
    out = []
    try:
        data = _get_json("https://remoteok.com/api")
        for j in data:
            if not isinstance(j, dict) or "id" not in j:
                continue  # first element is legal notice
            out.append({
                "id": f"remoteok-{j.get('id')}",
                "title": j.get("position", "") or j.get("title", ""),
                "company": j.get("company", ""),
                "location": j.get("location", "") or "Remote",
                "url": j.get("url", ""),
                "source": "RemoteOK",
                "tags": " ".join(j.get("tags", []) or []),
            })
    except Exception as e:
        print("RemoteOK fetch failed:", e)
    return out


def fetch_jobicy():
    out = []
    try:
        data = _get_json("https://jobicy.com/api/v2/remote-jobs?count=100")
        for j in data.get("jobs", []):
            out.append({
                "id": f"jobicy-{j.get('id')}",
                "title": j.get("jobTitle", ""),
                "company": j.get("companyName", ""),
                "location": j.get("jobGeo", "") or "Anywhere",
                "url": j.get("url", ""),
                "source": "Jobicy",
                "tags": " ".join(j.get("jobIndustry", []) or []),
            })
    except Exception as e:
        print("Jobicy fetch failed:", e)
    return out


def fetch_himalayas():
    out = []
    try:
        data = _get_json("https://himalayas.app/jobs/api?limit=100")
        for j in data.get("jobs", []):
            loc = j.get("locationRestrictions") or []
            out.append({
                "id": f"himalayas-{j.get('guid', j.get('title'))}",
                "title": j.get("title", ""),
                "company": j.get("companyName", ""),
                "location": ", ".join(loc) if loc else "Worldwide",
                "url": j.get("applicationLink", "") or j.get("guid", ""),
                "source": "Himalayas",
                "tags": " ".join(j.get("categories", []) or []),
            })
    except Exception as e:
        print("Himalayas fetch failed:", e)
    return out


FETCHERS = [fetch_remotive, fetch_remoteok, fetch_jobicy, fetch_himalayas]


# ---------------------------------------------------------------------------
# 3. FILTER
# ---------------------------------------------------------------------------

def matches(job):
    hay = f"{job['title']} {job['tags']}".lower()

    if not any(k in hay for k in INCLUDE_KEYWORDS):
        return False
    if any(k in hay for k in EXCLUDE_KEYWORDS):
        return False

    region_hay = f"{job['location']} {job['tags']}".lower()
    if not any(t in region_hay for t in REGION_TERMS):
        return False

    return True


# ---------------------------------------------------------------------------
# 4. DEDUPE / PERSISTENCE
# ---------------------------------------------------------------------------

def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    seen = list(seen)[-MAX_SEEN:]
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f)


# ---------------------------------------------------------------------------
# 5. EMAIL
# ---------------------------------------------------------------------------

def build_html(jobs):
    today = datetime.date.today().strftime("%A, %d %B %Y")
    rows = []
    for j in jobs:
        rows.append(f"""
          <tr>
            <td style="padding:12px 10px;border-bottom:1px solid #eee;">
              <a href="{j['url']}" style="font-size:15px;font-weight:600;
                 color:#1a5f7a;text-decoration:none;">{j['title']}</a><br>
              <span style="color:#333;font-size:13px;">{j['company'] or 'Company undisclosed'}</span>
              &nbsp;·&nbsp;
              <span style="color:#666;font-size:13px;">{j['location']}</span><br>
              <span style="color:#999;font-size:11px;">via {j['source']}</span>
            </td>
          </tr>""")
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         max-width:640px;margin:0 auto;">
      <h2 style="color:#1a5f7a;margin-bottom:2px;">Remote Roles Digest</h2>
      <p style="color:#888;font-size:13px;margin-top:0;">{today}
         &nbsp;·&nbsp; {len(jobs)} new matching role(s)</p>
      <table style="width:100%;border-collapse:collapse;">{''.join(rows)}</table>
      <p style="color:#aaa;font-size:11px;margin-top:20px;">
        Consultant / BA / strategy / ops / analytics · US · Europe · ANZ · worldwide.
        Sources: Remotive, RemoteOK, Jobicy, Himalayas.
      </p>
    </div>"""


def send_email(jobs):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🌍 {len(jobs)} new remote role(s) — {datetime.date.today():%d %b}"
    msg["From"] = GMAIL_USER
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(build_html(jobs), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, [MAIL_TO], msg.as_string())
    print(f"Sent {len(jobs)} jobs to {MAIL_TO}")


# ---------------------------------------------------------------------------
# 6. MAIN
# ---------------------------------------------------------------------------

def main():
    if not GMAIL_USER or not GMAIL_APP_PASS:
        raise SystemExit("Missing GMAIL_USER / GMAIL_APP_PASS env vars.")

    all_jobs = []
    for fn in FETCHERS:
        got = fn()
        print(f"{fn.__name__}: {len(got)} raw")
        all_jobs.extend(got)

    matched = [j for j in all_jobs if matches(j)]
    print(f"Matched filter: {len(matched)}")

    seen = load_seen()
    fresh = [j for j in matched if j["id"] not in seen]
    print(f"New (unseen): {len(fresh)}")

    # de-dupe within this run by URL too
    seen_urls, unique = set(), []
    for j in fresh:
        if j["url"] and j["url"] not in seen_urls:
            seen_urls.add(j["url"])
            unique.append(j)
    fresh = unique[:MAX_JOBS_IN_EMAIL]

    if fresh:
        send_email(fresh)
    else:
        print("No new roles today — no email sent.")

    for j in matched:
        seen.add(j["id"])
    save_seen(seen)


if __name__ == "__main__":
    main()
