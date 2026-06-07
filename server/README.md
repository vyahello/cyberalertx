# Server — deploy & debug

Production deployment artifacts + operational reference. Drop these
files on a fresh Ubuntu 24.04 VPS to bring CyberAlertX up. Refer here
for routine ops (deploy, restart, debug, backup).

The narrative deploy guide is in the [main README](../README.md). This
folder is the **quick-reference**: cmd → result, debug recipe → fix.

```
server/
├── README.md                              this file
├── systemd/
│   ├── cyberalertx-api.service            FastAPI on 127.0.0.1:8000
│   ├── cyberalertx-run.service            APScheduler ingest every 15 min
│   ├── cyberalertx-frontend.service       Next.js on 127.0.0.1:3000
│   ├── cyberalertx-generate.service       AI render one-shot (fires from timer)
│   ├── cyberalertx-generate.timer         Every 6h, runs the generate one-shot
│   ├── cyberalertx-telegram.service       Telegram publish one-shot (fires from timer)
│   └── cyberalertx-telegram.timer         Every 6h (+15m), publishes to TG channels
├── nginx/
│   └── cyberalertx.conf                   reverse proxy + SSL
├── scripts/
│   └── refresh_feed.py                    editorial reset: prune store + regen AI
├── setup.sh                               one-time VPS bootstrap (run as root)
├── deploy.sh                              update workflow (run as app user)
└── backup.sh                              daily data/ archive (run from cron)
```

---

## Placeholders used in this document

Replace these with your own values when running the commands below.

| Placeholder | Meaning | Example |
|---|---|---|
| `<user>` | Unix user that owns the app | `deploy`, `cyberalertx`, etc. |
| `<app-dir>` | Working directory of the app | `/home/<user>/cyberalertx` |
| `<your-domain>` | Production domain (DNS A record) | `example.com` |
| `<vps-ip>` | Public IP of the VPS | `203.0.113.42` |
| `<your-fork>` | GitHub org/user hosting your fork | `acme/cyberalertx` |
| `<fingerprint>` | 16-hex `news_items.fingerprint` of a post | `a1b2c3d4e5f60718` |

## Project defaults (don't change unless you're customising)

| Setting | Value |
|---|---|
| Python venv | `<app-dir>/venv` |
| Frontend build | `<app-dir>/frontend/.next` |
| API port (internal) | `127.0.0.1:8000` |
| Frontend port (internal) | `127.0.0.1:3000` |
| SSL cert | `/etc/ssl/cyberalertx/origin.{crt,key}` (Cloudflare Origin) |
| Store cap | 20 items (newest by `published_at`, auto-pruned) |
| Feed display | 15 newest + 5 trending (by danger) |
| AI render cadence | every 6h via systemd timer (2 items per fire) |

If you deploy under different paths, `sed` the relevant files before
copying to `/etc/`. Or set `APP_USER` / `APP_DIR` env vars when running
`setup.sh`.

---

## What runs on the server

Four long-lived services + one timer-driven oneshot. All under systemd,
all logs to journald, all gated by the same `.env` at `<app-dir>/.env`.

| Unit | Type | Cadence | What it does | Calls Anthropic? |
|---|---|---|---|---|
| `cyberalertx-api` | simple | always-on | FastAPI on `127.0.0.1:8000`; reads JSON + PG, serves `/posts`, `/healthz`, etc. | No |
| `cyberalertx-run` | simple | always-on | APScheduler in-process; runs ingest cycle every 15 min (RSS fetch → filter → rank → upsert). Auto-prunes store to 20 items on each upsert. | No |
| `cyberalertx-frontend` | simple | always-on | Next.js production server on `127.0.0.1:3000`. SSR + ISR (60s window). | No |
| `cyberalertx-generate.service` | oneshot | fires from timer | Runs `generate --limit 2 --use-llm` — top-2 newest uncached items get an AI render. | **Yes** |
| `cyberalertx-generate.timer` | timer | every 6h (00, 06, 12, 18 UTC) | Activates the generate one-shot. Persistent (catches up after reboots). | n/a |
| `cyberalertx-telegram.service` | oneshot | fires from timer | Runs `publish-telegram` — sends qualifying *already-rendered* posts to the EN/UA Telegram channels. Idempotent via `data/telegram_published.jsonl`. | No |
| `cyberalertx-telegram.timer` | timer | every 6h, +15m (00:15, 06:15, 12:15, 18:15 UTC) | Activates the publish one-shot 15 min after generate, so freshly rendered posts go out same cycle. Persistent. | n/a |

Memory budget on a small VPS (~2 GB RAM):

| Service | Typical RSS |
|---|---|
| `cyberalertx-frontend` (Next.js) | ~250-450 MB |
| `cyberalertx-api` (uvicorn) | ~60-120 MB |
| `cyberalertx-run` | ~55-80 MB |
| `cyberalertx-generate.service` (transient, only while rendering) | ~80 MB peak |

Watch with `systemd-cgtop` if you suspect drift.

---

## Initial deploy (one-time, ~90 min)

Run `setup.sh` AS ROOT on a fresh VPS:

```bash
ssh root@<vps-ip>
curl -fsSL https://raw.githubusercontent.com/<your-fork>/cyberalertx/main/server/setup.sh -o /tmp/setup.sh
bash /tmp/setup.sh
```

(Or `git clone` first, then `bash server/setup.sh` from the cloned repo.)

`setup.sh` handles: user creation, SSH hardening, firewall, Node 20,
Python venv, frontend build, deps install. **Doesn't touch secrets** —
you finish manually:

```bash
# Switch to app user
su - <user>
cd <app-dir>

# 1. Create .env (manual paste from your dev .env)
nano .env
chmod 600 .env

# 2. Postgres
python -m cyberalertx.tools.pg_migrate
# Optional — sync historical data from dev machine
# Run THIS from your dev machine, not the VPS:
#   rsync -avz data/ <user>@<vps-ip>:<app-dir>/data/
python -m cyberalertx.tools.import_to_postgres
python -m cyberalertx.tools.import_ai_cache_to_postgres
python -m cyberalertx.tools.compare_storage   # exit 0 = OK

# 3. systemd units (services + timer)
sudo cp <app-dir>/server/systemd/*.service /etc/systemd/system/
sudo cp <app-dir>/server/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cyberalertx-api cyberalertx-run cyberalertx-frontend
# AI auto-render every 6h:
sudo systemctl enable --now cyberalertx-generate.timer

# 4. nginx
sudo cp <app-dir>/server/nginx/cyberalertx.conf /etc/nginx/sites-available/cyberalertx
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
sudo cp <app-dir>/server/backup.sh /usr/local/bin/<user>-backup
sudo chmod +x /usr/local/bin/<user>-backup
echo "0 3 * * * <user> /usr/local/bin/<user>-backup" | sudo tee /etc/cron.d/<user>-backup

# Verify
curl https://<your-domain>/healthz
```

---

## Update workflow

After pushing code to git:

```bash
ssh <user>@<your-domain>
cd <app-dir>
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

## AI render — two paths

The AI layer is gated by `--use-llm`. The API server and the ingest
scheduler **never** call Anthropic. Only two paths trigger Anthropic:

### 1. Automatic — `cyberalertx-generate.timer` (every 6h)

Fires `generate --limit 2 --use-llm`. Idempotent: if the top-2 newest
items are already cached, the fire is a no-op (cache hits skip, zero
API calls). Real cost is bounded by NEW items arriving since the last
fire — i.e., by news-cycle volume, not by timer frequency.

Inspect the timer:

```bash
# Next + last fire
sudo systemctl list-timers --no-pager | grep generate

# Detailed status
sudo systemctl status cyberalertx-generate.timer
sudo systemctl status cyberalertx-generate.service

# Trigger a fire manually (e.g., to test or pull a backlog)
sudo systemctl start cyberalertx-generate.service

# See what each fire did
sudo journalctl -u cyberalertx-generate.service --since "24h ago"

# Pause / resume the auto-render entirely
sudo systemctl disable --now cyberalertx-generate.timer
sudo systemctl enable --now  cyberalertx-generate.timer
```

Tightening the cadence: edit `cyberalertx-generate.timer` →
`OnCalendar=*-*-* 00,04,08,12,16,20:00:00` for every 4h, or change
`--limit 2` → `--limit 3` in `cyberalertx-generate.service`. Then
`sudo systemctl daemon-reload && sudo systemctl restart cyberalertx-generate.timer`.

### 2. Manual — ad-hoc render or batch refresh

```bash
ssh <user>@<your-domain>
cd <app-dir> && source venv/bin/activate

# Preview first — shows cost surface, no API calls
python -m cyberalertx.main generate --limit 5 --use-llm --dry-run

# Real render
python -m cyberalertx.main generate --limit 5 --use-llm
```

Typical cost at Haiku 4.5: ~$0.008-0.015 per `(fingerprint, locale)`
pair. `--limit 5` → ~7 API calls (5 items × ~1.5 locales) ≈ $0.05-0.10.

### Delete a post — `delete_post`

Sometimes a non-security item slips through the relevance filter and
shows up in the feed. Remove it from every store with one command:

```bash
ssh <user>@<your-domain>
cd <app-dir> && source venv/bin/activate

# By URL (paste from browser)
python -m cyberalertx.tools.delete_post https://<your-domain>/ua/threat/<fingerprint>

# By fingerprint (16 hex chars)
python -m cyberalertx.tools.delete_post <fingerprint>

# Multiple at once
python -m cyberalertx.tools.delete_post <fingerprint> <fingerprint2>

# Preview first (no writes)
python -m cyberalertx.tools.delete_post --dry-run https://<your-domain>/ua/threat/<fingerprint>
```

The tool removes the fingerprint from `items.json`, `threat_posts.json`,
PG `news_items`, and PG `threat_posts`. Idempotent — running twice is
safe.

The live page refreshes within ~60s (Next.js ISR window). Cloudflare
might serve cached HTML for a few minutes more; purge in the dashboard
if you need it gone instantly.

### Editorial reset — `refresh_feed.py`

Use after a prompt change to force every visible item into the new
style. Destructive — prunes store and wipes AI cache.

```bash
ssh <user>@<your-domain>
cd <app-dir> && source venv/bin/activate

# Dry-run — show what would change
python -m server.scripts.refresh_feed --dry-run

# Prune to 20 newest, wipe AI cache, regenerate via Anthropic
python -m server.scripts.refresh_feed --regen

# Just prune (no regen — let the timer rebuild gradually)
python -m server.scripts.refresh_feed
```

Cost of `--regen` at default 20-cap: ~20 items × 1.5 locales × $0.009 ≈
**~$0.30** on Haiku. Do this rarely — once per prompt iteration.

---

## Telegram publishing

Sends high-signal, already-AI-rendered posts to Telegram channels. Like AI
render, it's a **timer-fired one-shot** — decoupled from ingest and from the
render path. It never calls Anthropic (it only publishes posts `generate`
already rendered) and is idempotent via a JSONL ledger
(`data/telegram_published.jsonl`), so re-runs and reboot catch-ups never
double-post.

### What gets published

A post is sent to a channel iff **all** hold:
- it has a persisted AI render in that channel's locale (`generate` ran for it);
- `source_tier ∈ {trusted, verified}`;
- `threat_level ≥ CYBERALERTX_TELEGRAM_MIN_LEVEL` (default `High`) **OR**
  `actionability_level == urgent_action`;
- it isn't already in the publish ledger.

EN channel = English-source items only. UA channel = English-source (UA
translation) **plus** Ukrainian-source items — same asymmetric rule as the site.

### One-time setup

1. **Create the bot + channels.** In Telegram, talk to **@BotFather** →
   `/newbot` → copy the token. Create your channel(s), then **add the bot as an
   administrator** of each (required for `sendMessage` to a channel).
2. **Add secrets to `<app-dir>/.env`** (then `chmod 600 .env`):
   ```bash
   CYBERALERTX_TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
   CYBERALERTX_TELEGRAM_CHANNEL_EN=@your_en_channel      # or a numeric -100… id
   CYBERALERTX_TELEGRAM_CHANNEL_UA=@your_ua_channel      # optional — omit to disable UA
   # Optional tuning:
   # CYBERALERTX_TELEGRAM_MIN_LEVEL=High                 # Low|Medium|High|Critical
   # CYBERALERTX_TELEGRAM_LIMIT=5                         # max sends per channel per fire
   # CYBERALERTX_PUBLIC_BASE_URL=https://cyberalertx.com  # deep-link base
   ```
3. **Preview before going live** (no messages sent):
   ```bash
   cd <app-dir> && source venv/bin/activate
   python -m cyberalertx.main publish-telegram --dry-run
   # narrow it: --language en   |   cap it: --limit 2
   ```
4. **Send for real once** to confirm formatting in-channel:
   ```bash
   python -m cyberalertx.main publish-telegram --limit 1
   ```
5. **Install + enable the timer:**
   ```bash
   sudo cp <app-dir>/server/systemd/cyberalertx-telegram.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now cyberalertx-telegram.timer
   ```

### Control & inspect

| Action | Command |
|---|---|
| Show next fire | `systemctl list-timers --no-pager \| grep telegram` |
| Trigger now | `sudo systemctl start cyberalertx-telegram.service` |
| Last fire result | `sudo journalctl -u cyberalertx-telegram.service --since "24h ago"` |
| Pause publishing | `sudo systemctl disable --now cyberalertx-telegram.timer` |
| What's been sent | `tail <app-dir>/data/telegram_published.jsonl` |

To re-publish a post that was already sent (e.g. after fixing its render),
delete its line from `data/telegram_published.jsonl` and fire the service.

---

## Service control

Long-lived services:

| Action | Command |
|---|---|
| Status (all) | `systemctl status cyberalertx-api cyberalertx-run cyberalertx-frontend` |
| Start | `sudo systemctl start cyberalertx-api` |
| Stop | `sudo systemctl stop cyberalertx-api` |
| Restart | `sudo systemctl restart cyberalertx-api` |
| Enable at boot | `sudo systemctl enable cyberalertx-api` |
| Disable at boot | `sudo systemctl disable cyberalertx-api` |
| nginx reload | `sudo nginx -t && sudo systemctl reload nginx` |

AI generate timer:

| Action | Command |
|---|---|
| Show next fire | `systemctl list-timers --no-pager \| grep generate` |
| Timer status | `systemctl status cyberalertx-generate.timer` |
| Last fire result | `systemctl status cyberalertx-generate.service` |
| Trigger fire now | `sudo systemctl start cyberalertx-generate.service` |
| Pause auto-render | `sudo systemctl disable --now cyberalertx-generate.timer` |
| Resume auto-render | `sudo systemctl enable --now cyberalertx-generate.timer` |
| Adjust cadence | edit `/etc/systemd/system/cyberalertx-generate.timer` then `daemon-reload + restart cyberalertx-generate.timer` |

---

## Logs

```bash
# Live tail (Ctrl+C to exit)
sudo journalctl -u cyberalertx-api -f
sudo journalctl -u cyberalertx-run -f
sudo journalctl -u cyberalertx-frontend -f
sudo journalctl -u cyberalertx-generate.service -f    # AI render fires
sudo journalctl -u nginx -f

# Last N lines
sudo journalctl -u cyberalertx-api -n 100 --no-pager

# Since a time
sudo journalctl -u cyberalertx-run --since "1 hour ago"
sudo journalctl -u cyberalertx-run --since "YYYY-MM-DD HH:MM"

# Errors only
sudo journalctl -u cyberalertx-api -p err --no-pager

# Ingest cycles count (should be ~4/hour from cyberalertx-run)
sudo journalctl -u cyberalertx-run --since "1 hour ago" | grep -c "cycle complete"

# AI generate fires (should be 4/day from the timer)
sudo journalctl -u cyberalertx-generate.service --since "24 hours ago" | grep "Started"

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
curl -k -H "Host: <your-domain>" https://127.0.0.1/healthz   # nginx routing

# External (from anywhere)
curl https://<your-domain>/healthz
curl -I https://<your-domain>/en
curl https://<your-domain>/posts?language=en&limit=3

# DNS sanity
dig <your-domain> +short                           # should be your CDN IPs
dig <your-domain> NS +short                        # should match your DNS provider

# JSON ↔ PG parity
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate && python -m cyberalertx.tools.compare_storage'
```

---

## What to watch (daily-ish checks)

A 60-second sweep that catches most production issues:

### 1. All four services active

```bash
systemctl is-active cyberalertx-api cyberalertx-run cyberalertx-frontend
systemctl is-active cyberalertx-generate.timer
```

Expected: `active` × 4. Anything else → `systemctl status <unit>` for the
red line.

### 2. Store at the right size (20)

```bash
curl -s https://<your-domain>/healthz | jq '{
  stored_items,
  latest_published_at,
  latest_urgent_at,
  minutes_since_last_urgent
}'
```

Expected: `stored_items == 20` (the configured cap). If `>20`, the new
config (`max_items_retained=20`) hasn't taken effect — `git pull` +
`sudo systemctl restart cyberalertx-run`, or the cap env var on `.env`
overrides it.

`latest_published_at` < 4h old in a normal news cycle. > 12h means RSS
sources are quiet OR the ingest service is stuck — drill into
`cyberalertx-run` logs.

### 3. Ingest is actually cycling

```bash
sudo journalctl -u cyberalertx-run --since "1 hour ago" \
  | grep -c "cycle complete"
```

Expected: 3-4 (one every ~15 min). If `0` → APScheduler is dead
(the `next_run_time=None` bug class). Restart it:
`sudo systemctl restart cyberalertx-run`.

### 4. AI auto-render is firing on schedule

```bash
sudo systemctl list-timers --no-pager | grep generate
# Shows NEXT and LAST. LAST should be within the last 6h.

sudo journalctl -u cyberalertx-generate.service --since "24h ago" \
  | grep -E "Started|generated_by"
```

Expected: 3-4 entries per day (every 6h cadence). Each entry should
end with `generated_by: anthropic:claude-haiku-...=N` for N>=0.

If `N=0` consistently — cache is already warm (fine). If timer log
has `failed` / `timeout` → check `.env` ANTHROPIC_API_KEY and rate
limits via Anthropic console.

### 5. AI render success rate

```bash
sudo -u <user> jq '.counters | {
  attempted: .ai_renders_attempted,
  success: .ai_renders_success,
  fallback: .ai_fallback_count,
  validation_rejects: .ai_validation_rejects,
  provider_errors: .ai_provider_errors
}' <app-dir>/data/quality_metrics.json
```

Healthy: `success / attempted` >= 0.7. Lower → look at
`.top_failure_messages` in the same file to see which validator is
biting (russism, cliché, foreign script, title language).

### 6. Disk + memory headroom

```bash
df -h /home/<user>        # > 1 GB free
free -h                   # > 100 MB available
sudo systemd-cgtop -n 1 -m | head -8
```

Frontend Next.js drifting > 600 MB → `sudo systemctl restart
cyberalertx-frontend` (cheap, no user impact past one ISR window).

### 7. JSON ↔ PG drift

```bash
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate \
  && python -m cyberalertx.tools.compare_storage'
```

Exit code 0 = synced. Non-zero = a dual-write missed (network blip).
Re-run; if persistent, see "PG threat-post set FAILED" recipe below.

### 8. Cost so far (Anthropic)

Open https://console.anthropic.com → Usage. Cross-check against:

```bash
sudo -u <user> jq '.counters.ai_renders_success' \
  <app-dir>/data/quality_metrics.json
```

× $0.009 ≈ ~ to-date spend on Haiku. Wildly different → check the
console for model fallthrough (someone set `CYBERALERTX_AI_MODEL` to
Sonnet/Opus by accident).

---

## Debug recipes

### `/healthz` returns 404 with unexpected cookies

Your CDN's DNS for `@` still points at the registrar's parking IP
(common ranges include `13.x` / `76.x` for some registrars). Fix in
your DNS provider → Records → set A `@` → `<vps-ip>` → Proxied. Delete
the parking record.

### `/posts` returns 200 but feed is empty

`data/items.json` is empty on this box. Either wait 15 min for first
`cyberalertx-run` cycle, or rsync from dev machine:
```bash
# From dev:
rsync -avz data/ <user>@<your-domain>:<app-dir>/data/
ssh <user>@<your-domain> 'sudo systemctl restart cyberalertx-api cyberalertx-frontend'
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
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate && python -c "from cyberalertx.storage.pg.engine import get_engine; from sqlalchemy import text; print(get_engine().connect().execute(text(\"SELECT 1\")).scalar())"'
```

### RAM pressure on a small VPS (~2GB)

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

### Feed shows English title on `/ua/threat/<fingerprint>`

Stale cache entry from before the title-language validator was added.
Delete it from PG, regenerate:
```bash
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate && python -c "
from sqlalchemy import text
from cyberalertx.storage.pg.engine import get_engine
with get_engine().begin() as c:
    c.execute(text(\"DELETE FROM threat_posts WHERE fingerprint=:fp AND locale=:loc\"), {\"fp\":\"<fingerprint>\",\"loc\":\"ua\"})
"'
rm <app-dir>/data/threat_posts.json   # forces full reload
python -m cyberalertx.main generate --limit 5 --use-llm
```

### Cloudflare cache serves stale content

Purge in Dashboard → Caching → Configuration → Purge Everything.
Or single URL: Purge Files → enter URL.

### AI generate timer doesn't fire

Symptom: `list-timers` shows the timer but `LAST` is hours-old or
`n/a`; `journalctl -u cyberalertx-generate.service` is empty.

Likely causes:
1. Timer is disabled — `sudo systemctl status cyberalertx-generate.timer`
   should say `Active: active (waiting)`. If `inactive` →
   `sudo systemctl enable --now cyberalertx-generate.timer`.
2. The `.service` unit has a syntax error — try a manual fire to see
   it: `sudo systemctl start cyberalertx-generate.service`; then
   `sudo systemctl status cyberalertx-generate.service`.
3. Missing `ANTHROPIC_API_KEY` in `<app-dir>/.env`. Fix the env,
   then `sudo systemctl start cyberalertx-generate.service` to retry.

### Feed shows fewer than 15 items on /en or /ua

Two common causes:
1. The store has < 15 items renderable in that locale. Verify:
   `curl -s https://<your-domain>/healthz | jq .stored_items` —
   should be 20. If it's lower, ingest hasn't caught up after a wipe;
   `sudo systemctl start cyberalertx-run` and wait 15 min.
2. UA-side: AI translation hasn't been generated for new items yet,
   and the half-translation gate hides them. Either wait for the next
   `cyberalertx-generate.timer` fire (≤ 6h), or trigger manually:
   `sudo systemctl start cyberalertx-generate.service`.

### Store grew above 20 items

The auto-prune in `JsonNewsStore._flush()` runs on each upsert, but
the prune sort and the cap come from `cyberalertx/config.py` +
`CYBERALERTX_MAX_ITEMS` env. If `stored_items > 20`:

```bash
# Verify the running config picked up max_items=20
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate \
  && python -c "from cyberalertx.config import SETTINGS; print(SETTINGS.max_items_retained)"'

# If it prints 5000 — old code is loaded. git pull + restart:
cd <app-dir> && git pull
sudo systemctl restart cyberalertx-run cyberalertx-api

# Force a prune right now:
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate \
  && python -m server.scripts.refresh_feed'
```

---

## Backup / restore

### Automated (daily)

`backup.sh` runs from cron (set up by `setup.sh`). Archives at
`/home/<user>/backups/data-YYYYMMDD-HHMMSS.tar.gz`. Keeps 14 days.

### Manual snapshot

```bash
sudo -u <user> /usr/local/bin/<user>-backup
ls -la /home/<user>/backups/
```

### Restore from snapshot

```bash
ssh <user>@<your-domain>
sudo systemctl stop cyberalertx-api cyberalertx-frontend cyberalertx-run
cd <app-dir>
mv data/ data.before-restore/
tar xzf ~/backups/data-YYYYMMDD-HHMMSS.tar.gz
sudo systemctl start cyberalertx-api cyberalertx-frontend cyberalertx-run
```

Postgres data lives on Supabase — restore via their dashboard
(Project Settings → Database → Backups).

---

## Off-server admin

| Want to | Run on dev machine |
|---|---|
| Update prod after code change | `git push && ssh <user>@<your-domain> 'cd <app-dir> && ./server/deploy.sh'` |
| Trigger AI render | `ssh <user>@<your-domain> 'sudo systemctl start cyberalertx-generate.service'` |
| Manual generate with custom limit | `ssh <user>@<your-domain> 'cd <app-dir> && source venv/bin/activate && python -m cyberalertx.main generate --limit 5 --use-llm'` |
| Delete a post that slipped through | `ssh <user>@<your-domain> 'cd <app-dir> && source venv/bin/activate && python -m cyberalertx.tools.delete_post <URL_or_fingerprint>'` |
| Editorial reset (after prompt change) | `ssh <user>@<your-domain> 'cd <app-dir> && source venv/bin/activate && python -m server.scripts.refresh_feed --regen'` |
| Pull prod logs | `ssh <user>@<your-domain> 'sudo journalctl -u cyberalertx-api -n 200 --no-pager'` |
| Check AI timer next-fire | `ssh <user>@<your-domain> 'systemctl list-timers --no-pager \| grep generate'` |
| Pull prod data backup | `scp <user>@<your-domain>:~/backups/data-*.tar.gz ~/Downloads/` |
| Sync local → prod data | `rsync -avz data/ <user>@<your-domain>:<app-dir>/data/` |

---

## Monitoring (recommended free options)

| Tool | What | Setup |
|---|---|---|
| [UptimeRobot](https://uptimerobot.com) | HTTP probe every 5 min | Free 50 monitors; alert email |
| Supabase dashboard | DB health, queries/sec | Built-in |
| Cloudflare Analytics | Traffic, cache hit rate | Built-in (free plan) |
| `htop` / `journalctl` | Live VPS state | SSH session |

Probe URL: `https://<your-domain>/healthz`. Expected: 200 + JSON
body with `"ok": true`. Alert if 3 consecutive failures.

---

## Cost reference

| Item | Cost / month |
|---|---|
| Small VPS (~2 GB RAM) | ~$5 |
| Supabase free tier | $0 (500MB DB, 2GB transfer) |
| Cloudflare free tier | $0 (unlimited bandwidth, basic DDoS) |
| Cloudflare Worker (RSS proxy) | $0 (free tier covers ~50k req/day) |
| Anthropic Haiku — auto-render every 6h (test cadence) | ~$1-3 (~5-15 new items/day × ~$0.013) |
| Anthropic Haiku — every 4h `--limit 3` (production cadence) | ~$3-6 |
| Domain (varies by TLD/registrar) | ~$1-2 amortized |
| **Total at test cadence** | **~$8-12/mo** |
| **Total at production cadence** | **~$10-15/mo** |

Cost driver = **new items per day**, not timer frequency (cache hits
skip). Lift the cap by going Sonnet 4.6 (~3× cost) or bumping
`--limit`; both are env / unit-file edits.

Scale up: bump to a larger VPS tier (8 GB RAM, ~$8/mo) only if Next.js
OOMs or ingest interval drops below 5 min. Supabase Pro ($25/mo) only
after ~50k items in `news_items` (won't happen with the 20-cap).
