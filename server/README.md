# Server — deploy & debug

Production deployment artifacts + operational reference. Drop these
files on a fresh Ubuntu 24.04 VPS to bring CyberAlertX up. Refer here
for routine ops (deploy, restart, debug, backup).

The narrative deploy guide is in the [main README](../README.md). This
folder is the **quick-reference**: cmd → result, debug recipe → fix.

```
server/
├── README.md                       this file
├── systemd/
│   ├── cyberalertx-api.service     FastAPI on 127.0.0.1:8000
│   ├── cyberalertx-run.service     APScheduler ingest every 15 min
│   └── cyberalertx-frontend.service  Next.js on 127.0.0.1:3000
├── nginx/
│   └── cyberalertx.conf            reverse proxy + SSL
├── setup.sh                        one-time VPS bootstrap (run as root)
├── deploy.sh                       update workflow (run as app user)
└── backup.sh                       daily data/ archive (run from cron)
```

---

## Conventions used in these files

| Setting | Default |
|---|---|
| App user | `cax` |
| App dir | `/home/cax/cax` |
| Python venv | `/home/cax/cax/venv` |
| Frontend build | `/home/cax/cax/frontend/.next` |
| API port (internal) | `127.0.0.1:8000` |
| Frontend port (internal) | `127.0.0.1:3000` |
| Domain | `cyberalertx.com` |
| SSL cert | `/etc/ssl/cyberalertx/origin.{crt,key}` (Cloudflare Origin) |

If you deploy under different paths, `sed` the relevant files before
copying to `/etc/`. Or set `APP_USER` / `APP_DIR` env vars when running
`setup.sh`.

---

## Initial deploy (one-time, ~90 min)

Run `setup.sh` AS ROOT on a fresh VPS:

```bash
ssh root@<VPS_IP>
curl -fsSL https://raw.githubusercontent.com/vyahello/cyberalertx/main/server/setup.sh -o /tmp/setup.sh
bash /tmp/setup.sh
```

(Or `git clone` first, then `bash server/setup.sh` from the cloned repo.)

`setup.sh` handles: user creation, SSH hardening, firewall, Node 20,
Python venv, frontend build, deps install. **Doesn't touch secrets** —
you finish manually:

```bash
# Switch to app user
su - cax
cd cax

# 1. Create .env (manual paste from your dev .env)
nano .env
chmod 600 .env

# 2. Postgres
python -m cyberalertx.tools.pg_migrate
# Optional — sync historical data from dev machine
# Run THIS from your dev machine, not the VPS:
#   rsync -avz data/ cax@<VPS_IP>:/home/cax/cax/data/
python -m cyberalertx.tools.import_to_postgres
python -m cyberalertx.tools.import_ai_cache_to_postgres
python -m cyberalertx.tools.compare_storage   # exit 0 = OK

# 3. systemd units
sudo cp /home/cax/cax/server/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cyberalertx-api cyberalertx-run cyberalertx-frontend

# 4. nginx
sudo cp /home/cax/cax/server/nginx/cyberalertx.conf /etc/nginx/sites-available/cyberalertx
sudo ln -sf /etc/nginx/sites-available/cyberalertx /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 5. SSL — Cloudflare Origin Certificate (paste from CF dashboard)
sudo mkdir -p /etc/ssl/cyberalertx
sudo nano /etc/ssl/cyberalertx/origin.crt
sudo nano /etc/ssl/cyberalertx/origin.key
sudo chmod 600 /etc/ssl/cyberalertx/origin.key
sudo systemctl reload nginx

# 6. Daily backup cron
sudo cp /home/cax/cax/server/backup.sh /usr/local/bin/cax-backup
sudo chmod +x /usr/local/bin/cax-backup
echo "0 3 * * * cax /usr/local/bin/cax-backup" | sudo tee /etc/cron.d/cax-backup

# Verify
curl https://cyberalertx.com/healthz
```

---

## Update workflow

After pushing code to git:

```bash
ssh cax@cyberalertx.com
cd ~/cax
./server/deploy.sh
```

`deploy.sh` does:
1. `git pull`
2. `pip install -r requirements.txt`
3. `npm ci && npm run build`
4. `systemctl restart cyberalertx-api cyberalertx-frontend`

(`cyberalertx-run` keeps cycling — its code is re-loaded automatically
within minutes. If you specifically changed ingest / pipeline code,
add `cyberalertx-run` to the restart list inside deploy.sh.)

---

## AI render (paid — manual trigger only)

```bash
ssh cax@cyberalertx.com
cd ~/cax && source venv/bin/activate

# Preview first — shows cost surface, no API calls
python -m cyberalertx.main generate --limit 5 --use-llm --dry-run

# Real render
python -m cyberalertx.main generate --limit 5 --use-llm
```

Typical cost at Haiku 4.5: ~$0.01-0.04 per post. `--limit 5` ≈ $0.05-0.20.

`generate --use-llm` is the **only** path that calls Anthropic. The
API server and the ingest scheduler never do.

---

## Service control

| Action | Command |
|---|---|
| Status (all) | `systemctl status cyberalertx-api cyberalertx-run cyberalertx-frontend` |
| Start | `sudo systemctl start cyberalertx-api` |
| Stop | `sudo systemctl stop cyberalertx-api` |
| Restart | `sudo systemctl restart cyberalertx-api` |
| Reload (no downtime if supported) | `sudo systemctl reload cyberalertx-api` |
| Enable at boot | `sudo systemctl enable cyberalertx-api` |
| Disable at boot | `sudo systemctl disable cyberalertx-api` |
| nginx reload | `sudo nginx -t && sudo systemctl reload nginx` |

---

## Logs

```bash
# Live tail (Ctrl+C to exit)
sudo journalctl -u cyberalertx-api -f
sudo journalctl -u cyberalertx-run -f
sudo journalctl -u cyberalertx-frontend -f
sudo journalctl -u nginx -f

# Last N lines
sudo journalctl -u cyberalertx-api -n 100 --no-pager

# Since a time
sudo journalctl -u cyberalertx-run --since "1 hour ago"
sudo journalctl -u cyberalertx-run --since "2026-05-13 09:00"

# Errors only
sudo journalctl -u cyberalertx-api -p err --no-pager

# nginx access / error logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## Health checks

```bash
# Internal (on VPS)
curl http://127.0.0.1:8000/healthz                 # backend
curl -I http://127.0.0.1:3000                      # frontend
curl -k -H "Host: cyberalertx.com" https://127.0.0.1/healthz   # nginx routing

# External (from anywhere)
curl https://cyberalertx.com/healthz
curl -I https://cyberalertx.com/en
curl https://cyberalertx.com/posts?language=en&limit=3

# DNS sanity
dig cyberalertx.com +short                          # should be Cloudflare IPs
dig cyberalertx.com NS +short                       # should be *.ns.cloudflare.com

# JSON ↔ PG parity
sudo -u cax bash -c 'cd /home/cax/cax && source venv/bin/activate && python -m cyberalertx.tools.compare_storage'
```

---

## Debug recipes

### `/healthz` returns 404 with `dps_site_id` cookie

Cloudflare DNS for `@` still points at GoDaddy parking IP (`13.x` /
`76.x`). Fix in Cloudflare → DNS → Records → set A `@` → Hetzner VPS
IP → Proxied. Delete the parking record.

### `/posts` returns 200 but feed is empty

`data/items.json` is empty on this box. Either wait 15 min for first
`cyberalertx-run` cycle, or rsync from dev machine:
```bash
# From dev:
rsync -avz data/ cax@cyberalertx.com:/home/cax/cax/data/
ssh cax@cyberalertx.com 'sudo systemctl restart cyberalertx-api cyberalertx-frontend'
```

### Frontend says `failed: This operation was aborted`

Next.js SSR fetch to backend timed out. Cause: dual-write mode + empty
local JSON cache → PG fallback per item × 15 items × 150ms Supabase
latency. Fix: ensure `data/threat_posts.json` exists (rsync from dev,
or run `generate --use-llm` to populate).

### nginx test passes but `https://...` returns 502

Backend process died. Check:
```bash
sudo systemctl status cyberalertx-api
sudo journalctl -u cyberalertx-api -n 50
```
Most common: `.env` missing or `CYBERALERTX_PG_URL` malformed. Fix
`.env`, then `sudo systemctl restart cyberalertx-api`.

### `dual-write: PG threat-post set FAILED` repeats in logs

Postgres unreachable. Network blip → JSON path stays authoritative,
PG catches up next render. If persistent: check Supabase status,
verify `CYBERALERTX_PG_URL` in `.env`, test:
```bash
sudo -u cax bash -c 'cd /home/cax/cax && source venv/bin/activate && python -c "from cyberalertx.storage.pg.engine import get_engine; from sqlalchemy import text; print(get_engine().connect().execute(text(\"SELECT 1\")).scalar())"'
```

### RAM pressure on 2GB VPS

Check who's eating:
```bash
sudo systemd-cgtop
free -h
ps aux --sort=-rss | head
```
If Next.js (`npm start`) over 600MB:
```bash
sudo systemctl restart cyberalertx-frontend
```
Add swap if recurring:
```bash
sudo fallocate -l 2G /swap
sudo chmod 600 /swap
sudo mkswap /swap
sudo swapon /swap
echo '/swap none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Feed shows English title on `/ua/threat/{id}`

Stale cache entry from before the title-language validator was added.
Delete it from PG, regenerate:
```bash
sudo -u cax bash -c 'cd /home/cax/cax && source venv/bin/activate && python -c "
from sqlalchemy import text
from cyberalertx.storage.pg.engine import get_engine
with get_engine().begin() as c:
    c.execute(text(\"DELETE FROM threat_posts WHERE fingerprint=:fp AND locale=:loc\"), {\"fp\":\"<FINGERPRINT>\",\"loc\":\"ua\"})
"'
rm /home/cax/cax/data/threat_posts.json   # forces full reload
python -m cyberalertx.main generate --limit 5 --use-llm
```

### Cloudflare cache serves stale content

Purge in Dashboard → Caching → Configuration → Purge Everything.
Or single URL: Purge Files → enter URL.

---

## Backup / restore

### Automated (daily)

`backup.sh` runs from cron (set up by `setup.sh`). Archives at
`/home/cax/backups/data-YYYYMMDD-HHMMSS.tar.gz`. Keeps 14 days.

### Manual snapshot

```bash
sudo -u cax /usr/local/bin/cax-backup
ls -la /home/cax/backups/
```

### Restore from snapshot

```bash
ssh cax@cyberalertx.com
sudo systemctl stop cyberalertx-api cyberalertx-frontend cyberalertx-run
cd ~/cax
mv data/ data.before-restore/
tar xzf ~/backups/data-20260513-030000.tar.gz
sudo systemctl start cyberalertx-api cyberalertx-frontend cyberalertx-run
```

Postgres data lives on Supabase — restore via their dashboard
(Project Settings → Database → Backups).

---

## Off-server admin

| Want to | Run on dev machine |
|---|---|
| Update prod after code change | `git push && ssh cax@cyberalertx.com 'cd ~/cax && ./server/deploy.sh'` |
| Trigger AI render | `ssh cax@cyberalertx.com 'cd ~/cax && source venv/bin/activate && python -m cyberalertx.main generate --limit 5 --use-llm'` |
| Pull prod logs | `ssh cax@cyberalertx.com 'sudo journalctl -u cyberalertx-api -n 200 --no-pager'` |
| Pull prod data backup | `scp cax@cyberalertx.com:~/backups/data-*.tar.gz ~/Downloads/` |
| Sync local → prod data | `rsync -avz data/ cax@cyberalertx.com:/home/cax/cax/data/` |

---

## Monitoring (recommended free options)

| Tool | What | Setup |
|---|---|---|
| [UptimeRobot](https://uptimerobot.com) | HTTP probe every 5 min | Free 50 monitors; alert email |
| Supabase dashboard | DB health, queries/sec | Built-in |
| Cloudflare Analytics | Traffic, cache hit rate | Built-in (free plan) |
| `htop` / `journalctl` | Live VPS state | SSH session |

Probe URL: `https://cyberalertx.com/healthz`. Expected: 200 + JSON
body with `"ok": true`. Alert if 3 consecutive failures.

---

## Cost reference

| Item | Cost / month |
|---|---|
| Hetzner CPX11 or CX22 | €4.50 (~$5) |
| Supabase free tier | $0 (500MB DB, 2GB transfer) |
| Cloudflare free tier | $0 (unlimited bandwidth, basic DDoS) |
| Anthropic Haiku — manual generate | ~$3-15 (10-50 posts/day) |
| GoDaddy domain renewal | ~$15/year amortized to $1.25/mo |
| **Total** | **~$10-25/mo** |

Scale up: bump VPS to CX32 (8GB RAM, €8/mo) only if Next.js OOMs or
ingest interval drops below 5 min. Supabase Pro ($25/mo) only after
~50k items in `news_items`.
