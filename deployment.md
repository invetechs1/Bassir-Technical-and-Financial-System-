# دليل النشر — نظام عزوم للعروض الفنية والمالية
# Deployment Guide (for DevOps)

## Requirements
- Python 3.10+ (tested on 3.11/3.12) — or simply Docker (see "Live deployment")
- `pip install -r requirements.txt` (includes `cryptography` — mandatory: secrets are
  encrypted at rest and the server **refuses** to store them in plaintext without it —
  and `Pillow` for logo validation/WebP→PNG conversion)
- Outbound HTTPS to `api.anthropic.com` (AI + model auto-update), `graph.facebook.com`
  (WhatsApp notifications, optional) and your SMTP host (email notifications, optional)
- Optional pages: `tenders.etimad.sa` (Etimad, Pro plan+) and `forsah.sa`
  (Forsah, needs the headless browser below)
- ~1 GB disk (SQLite DB + uploads + exports grow over time)

## Quick start (any Linux server)

```bash
git clone https://github.com/invetechs1/Bassir-Technical-and-Financial-System-.git azoom
cd azoom
./run.sh            # creates .venv, installs deps, starts on port 8000
```

Then open: `http://<server-ip>:8000`

## Production setup (recommended)

### 1. Environment

```bash
cp .env.example .env
# Edit .env:
#   ANTHROPIC_API_KEY=sk-ant-...   ← enables AI generation (optional but recommended)
#   PORT=8000
```

Without `ANTHROPIC_API_KEY` the system runs with the smart-template engine
(fully functional, lower quality drafting than Claude).

### 2. Systemd service

`/etc/systemd/system/azoom.service`:

```ini
[Unit]
Description=Azoom Proposals System
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/azoom
EnvironmentFile=/opt/azoom/.env
ExecStart=/opt/azoom/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now azoom
```

### 3. Reverse proxy + HTTPS (nginx)

```nginx
server {
    listen 443 ssl;
    server_name azoom.example.com;
    client_max_body_size 50M;          # proposal file uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_read_timeout 600s;       # AI generation can take minutes
    }
}
```

### 4. Authentication (built in)

The system requires login. There is **no fixed default password** any more:

- Set `AZOOM_ADMIN_PASSWORD` (8+ chars) in `.env` before the first start, **or**
- leave it unset — a random password is generated once and written to
  `data/INITIAL_ADMIN_PASSWORD.txt` (mode 600) and printed in the startup log.

The first admin username is `azoom`. Change the password after the first login
(الإعدادات → تغيير كلمة المرور) and delete the note file. Sessions are HMAC-signed
HttpOnly cookies valid for 12 hours (marked `Secure` automatically over HTTPS);
passwords are PBKDF2-SHA256 hashes.

Older installs that still use the historical default (`Azoom@2026`) print a
security warning at startup — rotate it immediately.

Brute-force protection (in-process, per user and per IP): 8 failed logins per user /
40 per IP per 10 minutes → HTTP 429 with `Retry-After`. Public self-signup: 3 per IP
and 30 total per hour. Tunable through env vars: `LOGIN_MAX_FAILS_USER`,
`LOGIN_MAX_FAILS_IP`, `SIGNUP_MAX_PER_IP_HOUR`, `SIGNUP_MAX_PER_HOUR`,
`GENERATE_MAX_PER_HOUR` (per-company AI generations), `MAX_UPLOAD_MB` (default 50).

**Behind nginx/Docker: proxies on a private/loopback address are trusted automatically; set `TRUSTED_PROXY=1`** (or `0` to disable trust) in `.env` so the real client IP
(`X-Forwarded-For`, last entry) is used by the limiters — never set it when the app is exposed
directly, or clients could spoof their address. Add
`proxy_set_header X-Forwarded-Proto $scheme;` to the nginx `location` (and
`X-Forwarded-For $remote_addr`) so cookies get the `Secure` flag. The limiters
are in-memory: with `--workers N` each worker counts separately (use a single
worker, or front with nginx `limit_req`, for strict global limits).

## OCR for scanned PDFs (recommended)

Scanned (image-only) proposal PDFs can't be parsed as text. Install the OCR
tools and the system reads them automatically on upload:

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-ara poppler-utils   # both are required for scanned PDFs
sudo systemctl restart azoom
```

No Python packages needed — the system calls `tesseract`/`pdftoppm` directly.
Re-upload previously failed files after installing.

## Forsah platform (forsah.sa) — headless browser

The Forsah projects page logs in with the company account and scrapes the six
activity categories. Forsah is a JavaScript app, so the server needs the
headless browser engine (one-time):

```bash
.venv/bin/pip install -q -r requirements.txt      # installs playwright
.venv/bin/playwright install --with-deps chromium # downloads the browser
sudo systemctl restart azoom
```

Credentials are entered on the «مشاريع منصة فرصة» page and stored only in the
local database. The browser session is cached in `data/forsah_state.json`.

## Multi-company (SaaS) & roles

The system is multi-tenant: each company has fully isolated prices, proposals,
library, repository, documents, settings, and platform credentials. Existing
single-company databases migrate automatically on first start after updating —
all current AZOOM data becomes company #1, nothing is lost.

- Roles per membership: `owner` / `admin` / `editor` / `viewer`. The five
  admin pages (prices, library, repository, analytics, archive) are enforced
  server-side, not just hidden in the UI.
- The `azoom` account is the platform admin: it can create new companies with
  their own owner accounts from «الشركات والمستخدمون».
- Plan limits (trial/basic/pro/enterprise) are enforced before generation,
  invitations, and new price items.
- Forsah passwords are stored encrypted (Fernet key auto-created at
  `data/secret.key` — back it up with `data/`).

## Billing & self-signup (SaaS layer)

- Public signup at `/signup`: creates a 14-day trial company with its owner.
- Plan gates return **402** (not 403): Etimad/Forsah and the style engine need
  Pro or Enterprise; expired trials become read-only for 30 days, then suspended
  (data kept). All computed live — no cron needed.
- Subscriptions: the platform admin upgrades/downgrades a company, sets a
  negotiated monthly price (`custom_price`) and status (active / read-only /
  suspended) from «الشركات والمستخدمون» (`PUT /api/companies/{id}`). Moving a trial
  to a paid plan clears the trial end; going back to trial is refused.
- Monthly invoices are issued **automatically** by a background scheduler (checked
  every 6 hours; a unique index guarantees one invoice per company per period), or
  on demand via «إصدار فواتير الشهر» / `POST /api/platform/invoices/issue`.
  Trials are skipped; an enterprise company without an agreed price is skipped and
  reported under `unpriced` until you set its `custom_price`.

## Notification channels (email / WhatsApp)

Configured per company in الإعدادات (admins only; secrets are encrypted and never
sent back to the browser — the UI shows "saved" and only overwrites when you type a new one).

- **Email**: SMTP host/port and encryption — `starttls` (587), `ssl` (465) or none.
- **WhatsApp Cloud API**: Meta only allows a business-initiated message outside the
  24-hour customer window when it uses an **approved template**. Create a template
  with one text variable `{{1}}` in Meta Business Manager and enter its name (and
  language) in the settings; without a template the message is sent as free text and
  Meta will reject it outside the 24h window. The last channel error is shown to the
  admin in the settings page.
- Member phones are normalized to E.164 (`+9665XXXXXXXX`); invalid numbers/emails are rejected.

## AI engine

- Both generation engines (Claude and the template engine) pass through the same
  company style layer (style bank + banned-phrase scrub) and use the company's own
  name — no AZOOM branding for other tenants.
- The Claude model auto-updates every 6 hours from the Anthropic Models API (trial
  request first); a manual pin by the platform admin always wins and disables the
  auto-switch/notifications. Analysis → approval in the agents flow builds the
  proposal **once** (the analyzed proposal is what gets saved).

## Data & backups

All state lives in `data/`:

| Path | Contents |
|---|---|
| `data/azoom.db` | SQLite DB: prices, proposals, archive, repo, docs, tenders, settings |
| `data/uploads/` | Uploaded project files |
| `data/exports/` | Generated Word/Excel files |
| `data/etimad_cookies.json` | Etimad session (created by the Nafath login script) |

Backup = copy the `data/` directory. To reset to factory seeds, delete
`data/azoom.db` and restart (seeds reload automatically: 640 price items,
4 reference proposals, content library, company docs).

## Updating a running deployment

```bash
cd /opt/azoom
git pull origin main
.venv/bin/pip install -q -r requirements.txt   # in case deps changed
sudo systemctl restart azoom
```

Schema migrations are automatic (`CREATE TABLE IF NOT EXISTS` on startup);
existing data is preserved.

## Etimad / Nafath (runs on a desktop, not the server)

The Nafath login needs a visible browser + the owner's phone:

```bash
pip install playwright && playwright install chromium
python scripts/etimad_nafath_login.py
```

It saves `data/etimad_cookies.json` — copy it to the server's `data/` dir if
the login was done on another machine. Fetching the public tenders list
(`POST /api/etimad/fetch`) needs **no login**, only network access to
`tenders.etimad.sa` from the server.

## Health check

`GET /api/status` → `{"ok": true, "ai_enabled": ..., "proposals": n, "price_items": n}`

## Full system check (after every deploy/update)

```bash
.venv/bin/python scripts/system_check.py
# or inside the running container:
docker exec azoom-proposals python scripts/system_check.py
```

Runs 267 checks: auth and brute-force limits, settings/secret handling, roles and
tenant isolation, plan gates and lifecycle, proposal generation (template and Claude
paths), Word/Excel exports (incl. 24 concurrent exports for two tenants), the agents
flow, invoicing, notification channels, model updater, and the first-run password.

By default it runs against a **temporary isolated database** (`AZOOM_DATA_DIR`) that is
deleted afterwards — it never touches production data, never leaves test users or
companies behind, and needs no knowledge of the live admin password. Exit code 0 =
all green. To deliberately run against the current database (needs the `azoom`
password to be `Azoom@2026`): `python scripts/system_check.py --current-db`.

## Live deployment

- **URL**: https://pricing-system.bassir.net/
- **Runs as**: Docker container `azoom-proposals` on `13.140.138.252:8003`,
  reverse-proxied to this domain over TLS (Let's Encrypt cert, auto-renewing,
  issued 2026-08-17).
- **Server path**: `/opt/azoom-proposals/` — `azoom-proposals.tar` (last
  built image), `deploy.sh` (redeploy script — removes the old container/image
  for this project only, loads the new tar, runs it with `--restart
  unless-stopped` and `data/` bind-mounted for persistence), `data/` (SQLite
  DB, uploads, exports), `backups/` (nightly tar snapshots, kept 14 days,
  via a 2am cron running `backup.sh`).
- **Login**: the live admin password has been rotated — get it from whoever ran
  the last deploy; it is intentionally not stored in this repo. New installs use
  `AZOOM_ADMIN_PASSWORD` or a generated `data/INITIAL_ADMIN_PASSWORD.txt`.
- **Container env** (`.env` on the server): `ANTHROPIC_API_KEY`, `TRUSTED_PROXY=1`
  (the container sits behind the nginx reverse proxy).
- `ANTHROPIC_API_KEY` is configured in the server's `.env` — AI generation
  (`engine=claude`) is live. Not yet configured: the Etimad/Nafath desktop
  login (`data/etimad_cookies.json`).

## Redeploying to production (build → ship → run)

Run from the repo root on your machine.

### 1. Build the image

```bash
docker build -t azoom-proposals:latest .
```

### 2. (Recommended) Sanity-check the image before shipping it

```bash
docker run --rm azoom-proposals:latest sh -c "python scripts/system_check.py"
```

Should print `===== النتيجة: 267/267 =====` at the end (it uses a throwaway database
inside the container). Don't ship if it doesn't.

### 3. Save it to a tar file

```bash
docker save azoom-proposals:latest -o dist/azoom-proposals.tar
```

### 4. Upload the tar to the server

```bash
scp dist/azoom-proposals.tar root@13.140.138.252:/opt/azoom-proposals/
```

### 5. Run the server-side deploy script

```bash
ssh root@13.140.138.252 "cd /opt/azoom-proposals && bash deploy.sh"
```

`deploy.sh` (already on the server) stops and removes the old
`azoom-proposals` container/image only, loads the new tar, and starts the
container on port 8003 with `--restart unless-stopped` and `data/` bind-mounted
— existing DB/uploads/exports are untouched. It reuses `.env` on the server
automatically if present (`ANTHROPIC_API_KEY`), so nothing needs to be re-entered.

### 6. Verify

```bash
curl -s https://pricing-system.bassir.net/api/status
ssh root@13.140.138.252 "docker exec azoom-proposals python scripts/system_check.py" 2>&1 | tail -5
```

The check runs on a scratch database, so it is safe on the live container and needs
no password — it should end with `267/267`.
