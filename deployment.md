# دليل النشر — نظام عزوم للعروض الفنية والمالية
# Deployment Guide (for DevOps)

## Requirements
- Python 3.10+ (tested on 3.11)
- Outbound HTTPS access to `tenders.etimad.sa` (for the Etimad tenders page)
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

The system requires login. First-run default credentials:

```
username: azoom
password: Azoom@2026
```

**Change the password immediately** after first login (الإعدادات → تغيير كلمة
المرور). Sessions are HMAC-signed HttpOnly cookies valid for 12 hours;
passwords are stored as PBKDF2-SHA256 hashes. Still serve the app over HTTPS
(nginx config above) so credentials never travel in plaintext.

## OCR for scanned PDFs (recommended)

Scanned (image-only) proposal PDFs can't be parsed as text. Install the OCR
tools and the system reads them automatically on upload:

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-ara poppler-utils
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
```

Runs 92 checks covering every endpoint and function: auth, seeds, settings,
prices CRUD + CSV import/export, library, company docs, proposal generation
(similarity + financial math), Word/Excel export (incl. the official footer),
knowledge repository (upload, reference creation, market benchmark), the
opportunity analyzer, analytics, and Etimad error handling. Exit code 0 =
all green. Safe to run repeatedly on a live database.

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
- **Login**: default `azoom` / `Azoom@2026` has been rotated — get the
  current password from whoever ran the last deploy; it is intentionally
  not stored in this repo.
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

Should print `===== النتيجة: 92/92 =====` at the end. Don't ship if it doesn't.

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

The `system_check.py` run against the live container will show one expected,
non-regression failure on the hardcoded default-password check (the live
password has been rotated) — everything else should be green.

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

Should print `===== النتيجة: 92/92 =====` at the end. Don't ship if it doesn't.

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

The `system_check.py` run against the live container will show one expected,
non-regression failure on the hardcoded default-password check (the live
password has been rotated) — everything else should be green.
