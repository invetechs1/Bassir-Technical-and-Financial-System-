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

> ⚠️ The current build has **no authentication layer** — do not expose it to
> the public internet without one. Options: keep it on a VPN/private network,
> add nginx basic-auth, or put it behind an SSO proxy (e.g. oauth2-proxy).

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
