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
│   ├── cyberalertx-telegram.timer         Every 6h (+15m), publishes to TG channels
│   ├── cyberalertx-analytics.service      visitor-stats ingest one-shot (fires from timer)
│   └── cyberalertx-analytics.timer        daily 03:00, pulls new log lines into the store
├── nginx/
│   ├── cyberalertx.conf                   reverse proxy + SSL
│   └── analytics-log-format.conf          http-level JSON log_format (goes in conf.d/)
├── logrotate/
│   └── cyberalertx-access                 365-day rotation for the dedicated log
├── analytics/                             visitor analytics package (python -m server.analytics)
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

## Social previews (Open Graph)

The link card that Telegram / X / Slack / LinkedIn show when someone shares a
page comes from the page's `og:*` meta tags. These are **baked at build /
render time**, and three independent caches sit in front of them — so a change
isn't visible until all three are busted. Skipping a step is the usual reason
"I fixed it but it still shows the old card".

### What controls the card

| Page | Card source |
|---|---|
| `/{locale}` (home) | `app/[locale]/layout.tsx` → `generateMetadata` (per-locale image + tagline) |
| `/{locale}/threat/{id}` | `app/[locale]/threat/[id]/page.tsx` → `generateMetadata` (article title + summary + locale image) |

Per-locale images live at `frontend/public/brand/og-image.png` (EN) and
`og-image-ua.png` (UA), generated from the SVG masters by `npm run brand:png`.

### Prerequisite — `NEXT_PUBLIC_SITE_URL`

OG image URLs must be **absolute** for crawlers to fetch them. Next.js builds
them from `metadataBase`, which reads `NEXT_PUBLIC_SITE_URL`. If it's unset the
base falls back to `http://localhost:3000` and every preview image 404s for the
outside world.

```bash
# Must print the production URL:
grep NEXT_PUBLIC_SITE_URL <app-dir>/.env <app-dir>/frontend/.env* 2>/dev/null
# If missing, add it where the frontend service reads env, then rebuild:
#   NEXT_PUBLIC_SITE_URL=https://<your-domain>
```

### Deploy an OG / metadata change (bust all three caches)

```bash
# 1. Rebuild — OG tags are emitted at build/render time, not runtime.
cd <app-dir> && git pull
cd frontend && npm run build
sudo systemctl restart cyberalertx-frontend

# 2. Confirm the origin emits the right tags (bypasses every cache):
curl -s https://<your-domain>/ua/threat/<fingerprint> \
  | grep -iE 'og:(title|description|image|locale)'
#   expect: UA title + summary, og:image …/og-image-ua.png, og:locale uk_UA

# 3. Purge Cloudflare — it caches the HTML (with the old tags).
#    Dashboard → Caching → Configuration → Purge Everything (or single URL).

# 4. Refresh the messenger's OWN preview cache — the step people miss.
#    Telegram caches previews per-URL, basically forever. To force a re-fetch:
#      • Telegram: DM @WebpageBot the exact URL → it re-crawls + clears the cache
#      • X:        https://cards-dev.twitter.com/validator
#      • Facebook/LinkedIn: their post/link inspectors re-scrape on demand
```

If `curl` (step 2) shows the correct tags but the share preview is still old,
the origin is fine — it's purely a messenger/CDN cache (steps 3–4).

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
# NOTE: after the analytics change below, cyberalertx traffic is NOT in
# access.log any more — it goes to its own file. The other vhosts still use
# access.log exactly as before.
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/cyberalertx-access.jsonl     # this site, JSON per line
```

---

## Visitor analytics

Self-hosted audience stats, read straight from the nginx access logs by
`python -m server.analytics`. No tracker, no third-party JavaScript, no
cookies, no data leaving the box. Log lines are parsed, classified, and
appended to a local SQLite store (`data/analytics.sqlite3`), which is what
makes "all time, by month, by day" answerable at all — logrotate only keeps
14 days, so a stateless log reader could never see further back than that.
A daily timer at 03:00 does the ingest; you just read reports.

**What it measures:** pageviews and their EN/UA split, top articles and entry
pages, acquisition channel (Telegram, search, social, direct), browser / OS /
device type, country, time-of-day and day-of-week patterns, 404s and 5xx,
latency percentiles, and a full accounting of bot and scanner traffic —
including scrapers that wear a browser User-Agent and are only detectable
across requests (see "The behavioural automation filter" below).

**What it cannot measure**, by design or by physics — the report says so itself
rather than guessing:

| Not measured | Why |
|---|---|
| Individual people | Visitors are salted daily hashes. The salt rotates at 04:00, so cross-day identity is not computable — "returning visitors" and retention curves are never printed. |
| Anything on legacy logs needing a client IP | Before the nginx change below, every request shows a *Cloudflare edge* IP, not a visitor. Unique-visitor counts are **suppressed, never estimated**, for those days. |
| Time on the last page of a visit | Nothing marks its end. Reported as "measured span", never "time on site". |
| Cached locale switches | Next.js App Router serves back/forward from its Router Cache and emits no request. No correction multiplier is applied — that would be inventing data. |
| iPhone / iPad models | Never exposed server-side. Brave counts as Chrome; iPads count as macOS. |

**Scoping — this touches one vhost only.** Other sites share this nginx
instance and this box. The change below
is confined to the cyberalertx `server` block: the http-level `access_log` is
untouched, so those three keep writing to `/var/log/nginx/access.log` with
byte-identical behaviour, and `/etc/logrotate.d/nginx` is never modified. The
tool reads only cyberalertx's own log, never signals or restarts a service, and
never writes to, truncates or rotates a log file.

### One-time: enable the extended log (nginx)

Everything the tool needs beyond the legacy format comes from one `log_format`
plus three directives in the vhost. Every failure mode here is a parse-time
`emerg` that `nginx -t` catches **before** the reload, and a failed reload
leaves the running config untouched — there is no window where any of the four
sites is down.

```bash
# 0. Snapshot to diff against afterwards.
sudo nginx -t
sudo nginx -T > /root/nginx-dump-before.txt

# 1. Back up the vhost. NOT into conf.d/ or sites-enabled/ — both are globbed
#    and a stray backup file would be loaded as config.
sudo cp -a /etc/nginx/sites-available/cyberalertx \
           /root/cyberalertx.vhost.bak.$(date +%F-%H%M%S)

# 2. Pre-create the log 0640 www-data:adm. Do NOT skip: nginx's master runs as
#    root and would otherwise create it root:root 0644 — world-readable, and it
#    now holds real visitor IPs — until the first nightly rotate fixes it.
sudo install -o www-data -g adm -m 0640 /dev/null \
     /var/log/nginx/cyberalertx-access.jsonl

# 3. Install the log_format, then test with nothing referencing it yet.
#    Defining a format is inert, so this step cannot affect any vhost.
sudo cp <app-dir>/server/nginx/analytics-log-format.conf \
        /etc/nginx/conf.d/cyberalertx-log.conf
sudo nginx -t

# 4. Install the vhost, then test. THIS IS THE GATE — a failure changes nothing.
sudo cp <app-dir>/server/nginx/cyberalertx.conf /etc/nginx/sites-available/cyberalertx
sudo nginx -t

# 5. Reload — NOT restart. restart drops in-flight connections on all four sites.
sudo systemctl reload nginx

# 6. Install the rotate config and dry-run it (-d changes nothing).
sudo cp <app-dir>/server/logrotate/cyberalertx-access /etc/logrotate.d/cyberalertx-access
sudo logrotate -d /etc/logrotate.d/cyberalertx-access
sudo logrotate -d /etc/logrotate.d/nginx 2>&1 | grep -i cyberalertx   # expect NO match

# 7. Verify the new log, through Cloudflare (not the origin).
curl -sI https://<your-domain>/en > /dev/null
sudo tail -n 1 /var/log/nginx/cyberalertx-access.jsonl | python3 -m json.tool

# 8. Verify the other three vhosts are untouched.
sudo tail -n 5 /var/log/nginx/access.log
# Repeat for each sibling vhost in /etc/nginx/sites-enabled/ — each must
# still answer exactly as it did before the reload.
curl -skI https://<sibling-vhost>/ | head -1

# 9. Confirm the diff is only what was intended.
sudo nginx -T > /root/nginx-dump-after.txt
sudo diff -u /root/nginx-dump-before.txt /root/nginx-dump-after.txt

# 10. Grant log read access to the analytics tool (see "Log access" below).
sudo usermod -aG adm <user>
```

Reading step 7's output:

| Symptom | Meaning | Fix |
|---|---|---|
| `ip` equals `pip` | `real_ip` is not firing | Check the `set_real_ip_from` block landed inside the `listen 443` server block |
| `ip` is your public IP (`curl -s https://ifconfig.me`), `pip` is a Cloudflare IP | Correct | — |
| `ray` populated, `cc` empty or `-` | **Cloudflare IP Geolocation is OFF** | Turn it on — see the note below. Country data is blank until you do |
| `ray` empty on your own request | You hit the origin directly, bypassing Cloudflare | Re-test against `https://<your-domain>`, not the VPS IP |
| The log stays empty while traffic flows | Traffic is arriving over IPv6 and being served by another vhost | See the IPv6 note below |

`nginx -t` prints two `[warn] protocol options redefined for 0.0.0.0:443 ...
sites-enabled/hoba` lines. Those are **pre-existing** and unrelated to this
change; they appear before it too.

**Rollback.** Remove the format and restore the vhost **together**, then test
once. Removing the format while the vhost still references it yields
`[emerg] unknown log format "cax_json"` and the reload is refused.

```bash
# Remove the format and restore the backed-up vhost in one go.
sudo rm -f /etc/nginx/conf.d/cyberalertx-log.conf
sudo cp -a /root/cyberalertx.vhost.bak.<TIMESTAMP> /etc/nginx/sites-available/cyberalertx

# Test, then reload only if the test passed.
sudo nginx -t && sudo systemctl reload nginx

# Prove you are back where you started (expect no output).
sudo diff -u /root/nginx-dump-before.txt <(sudo nginx -T)

# Optional: drop the rotate config too.
sudo rm -f /etc/logrotate.d/cyberalertx-access
```

The store keeps every event already ingested, so a rollback costs you new
extended fields going forward, not your history.

### Cloudflare: turn on IP Geolocation

The `country` dimension comes from the `CF-IPCountry` header, which Cloudflare
only sends when the **"Add visitor location headers"** Managed Transform (the
IP Geolocation toggle) is **ON**. It is free on every plan and needs no
Transform Rule of your own.

Cloudflare dashboard → your domain → **Rules → Settings → Add visitor location
headers** → enable.

Until it is on, `cc` is empty on every line and the report labels country as
unavailable rather than plotting a misleading zero. Three values are *not*
countries and are handled as such: `XX` (Cloudflare has no data), `T1` (Tor),
and empty (did not traverse Cloudflare, or the toggle is off).

### Daily use

```bash
cd <app-dir> && source venv/bin/activate

# Nightly, from the timer: pull every new log line into the store.
python -m server.analytics ingest

# Same, but show what would happen and write nothing.
python -m server.analytics ingest --dry-run

# The default: last 30 days, terminal report.
python -m server.analytics

# Last 7 days, by day, with period-over-period deltas.
python -m server.analytics report --since 7d --compare

# Monthly view of everything ever stored, plus the all-time summary.
python -m server.analytics report --since all --by month --all-time

# One specific month.
python -m server.analytics report --since 2026-08-01 --until 2026-08-31

# Machine-readable, for piping.
python -m server.analytics report --since 7d --json > /tmp/audience.json

# A local HTML page to open in a browser.
python -m server.analytics report --since 30d --html data/analytics/report.html

# Cross-check the store against the raw logs, ignoring the database.
python -m server.analytics report --since 7d --from-logs

# What does the store actually hold?
python -m server.analytics status
```

The timer does the ingest for you:

```bash
# Enable the nightly ingest (once).
sudo systemctl enable --now cyberalertx-analytics.timer

# When does it next fire?
systemctl list-timers --no-pager | grep analytics

# Run it by hand right now.
sudo systemctl start cyberalertx-analytics.service
sudo journalctl -u cyberalertx-analytics.service -n 50 --no-pager
```

### Flags

Global — accepted by every subcommand:

| Flag | What it does | Example |
|---|---|---|
| `--db PATH` | The persistent store (default: `data/analytics.sqlite3`). | `--db /tmp/scratch.sqlite3` |
| `--tz ZONE` | Reporting timezone, IANA name (default: `Europe/Kyiv`). The log line's own offset is the instant; this is the wall clock it is shown in. | `--tz UTC` |
| `--no-color` | Force colour off. Also honoured: `NO_COLOR` (any value), `TERM=dumb`, non-tty stdout. | `--no-color` |
| `--color {auto,always,never}` | Colour policy (default: `auto`). `always` for `less -R`. `--no-color` wins. | `--color always` |
| `--ascii` | ASCII fallback for bars, sparklines and the heatmap. Auto-enabled when stdout is not UTF-8. | `--ascii` |
| `-v`, `-vv` | `-v` → INFO, `-vv` → DEBUG (default: WARNING). Goes to stderr, so `> report.txt` stays clean. | `-vv` |
| `-q`, `--quiet` | Suppress `[analytics]` progress lines. Errors still print. | `-q` |

`ingest` — reads logs, writes events. Additive; never modifies a log:

| Flag | What it does | Example |
|---|---|---|
| `--log PATH` | An explicit log file, plain or `.gz`. Repeatable. Highest-priority source. | `--log /var/log/nginx/cyberalertx-access.jsonl` |
| `--log-dir DIR` | Scanned for `cyberalertx-access.jsonl*` and `access.log*` (default: `/var/log/nginx`). | `--log-dir /var/log/nginx` |
| `--archive-dir DIR` | Scanned for date-named `*.log.gz` / `*.log` (default: `data/nginx-archive`). | `--archive-dir data/nginx-archive` |
| `--since WHEN` | Skip records older than this (default: `all`). | `--since 7d` |
| `--until WHEN` | Skip records newer than this (default: `now`). | `--until yesterday` |
| `--reingest` | Ignore the already-seen-file fast path and re-read everything. Safe and idempotent — a per-line unique index still blocks double-counting. Slow, not destructive. | `--reingest` |
| `--dry-run` | Parse, classify, count; write nothing. Prints what *would* be inserted. | `ingest --dry-run` |
| `--batch-size N` | Rows per transaction (default: `2000`). Tune only for memory. | `--batch-size 500` |

`report`:

| Flag | What it does | Example |
|---|---|---|
| `--since WHEN` | Start of the window, inclusive (default: `30d`). | `--since 2026-08-01` |
| `--until WHEN` | End of the window, inclusive (default: `now`). | `--until today` |
| `--by {day,week,month,year}` | Bucket for "Traffic over time" (default: `day`). | `--by month` |
| `--all-time` | Adds the all-time summary, covering the whole store regardless of `--since`. | `--all-time` |
| `--compare` | Period-over-period deltas against the preceding complete period. Partial periods are excluded. | `--since 7d --compare` |
| `--top N` | Rows per table before the `+N more` line (default: `10`). | `--top 25` |
| `--host HOST` | Vhost filter, repeatable or comma-separated (default: your two site hosts). `all` disables filtering and the report says so loudly. | `--host all` |
| `--include-bots` | Fold bot and agent traffic into the audience numbers. Every headline label flips to `(BOTS INCLUDED)`. | `--include-bots` |
| `--hard-only` | Count only hard navigations — reproduces the naive document-only number for cross-checking. | `--hard-only` |
| `--automation-threshold N` | Pageview floor for the behavioural automation filter (default: `100`). See "The behavioural automation filter" below before lowering it — under it you start deleting real returning readers. | `--automation-threshold 150` |
| `--no-automation-filter` | Switch that filter off entirely. Audience numbers then include any scraper wearing a plausible browser UA; the report says loudly that the filter did not run. | `--no-automation-filter` |
| `--rolling-salt N` | One salt across N days, enabling cross-day identity. Never silent: the report prints a privacy note when it is on. | `--rolling-salt 7` |
| `--json` | Emit the whole report as JSON on stdout instead of the terminal render. | `--json > /tmp/a.json` |
| `--html PATH` | Also write a self-contained HTML report. Opens offline; makes zero network requests. | `--html data/analytics/report.html` |
| `--from-logs` | Bypass the store and read logs directly for this one report. Slower, and limited to what logrotate still holds. | `--from-logs` |
| `--log`, `--log-dir`, `--archive-dir` | As for `ingest`. Only meaningful with `--from-logs`. | `--from-logs --log-dir /var/log/nginx` |

`status` takes no flags beyond the globals. It prints date coverage, row counts,
per-day capabilities (which dimensions actually existed that day), last ingest
time, and the database size on disk.

`--since` / `--until` accept: `7d`, `12h`, `6w`, `3m`, `1y`, `45min`; an ISO
date (`2026-08-19`, both ends inclusive); an ISO datetime; `today`, `yesterday`,
`now`, `all`.

Exit codes: `0` success — **including "nothing matched"**, since the end state
is what you asked for; `1` a real error (unreadable logs, corrupt database,
unwritable `--html`); `2` bad input (an unparseable `--since`, `--since` after
`--until`, no log files found at all).

### Expected numbers

```bash
# Sanity-check the tool against known-good ground truth.
python -m server.analytics report --since 15d
```

**Expected: roughly 155 human pageviews per day**, about 2 300 over 15 days
(~3.1% of raw log lines), split roughly **EN 77% / UA 23%**. Most raw lines are
not audience — around 79% never traversed Cloudflare at all and are
direct-to-origin probes.

Those figures are **after** the behavioural automation filter. Run the same
window with `--no-automation-filter` and the tool reports ~4 180 pageviews at
EN 72% / UA 28% instead: two scraper user-agents accounted for 1 857 pageviews,
44.4% of the pre-filter audience, and they harvested both editions, which is
what diluted the EN skew. If you are comparing against an older report, check
which of the two numbers it was.

**If the tool reports thousands of daily visitors, it is wrong.** In order,
check: (1) Cloudflare provenance filtering — anything whose peer IP is outside
Cloudflare's ranges is a probe, not a person; (2) the `/healthz` exclusion,
which must be by **path**, since the monitor wears a real Chrome User-Agent and
a real Referer and hits ~60×/day; (3) prefetch filtering, without which the
EN/UA split drifts to 50/50 by construction.

### The behavioural automation filter

Classification is per request: Cloudflare provenance, then the User-Agent
signature, then the path. That catches everything that announces itself and
everything that skips the proxy, and it is structurally blind to the one thing
that separates a scraper from a reader here — what a single client did across
two thousand requests and fifteen days.

Measured on this site's own logs: one forged `iPhone OS 13_2_3` User-Agent (an
OS from 2019) arrived through Cloudflare from 788 different edge addresses, hit
380 paths on a ~10-minute cycle with no daily rhythm at all, fetched the `/en`
and `/ua` copy of the same article, and **never once requested a `/_next/`
chunk**. Every individual request looked like a person. With a second identity
polling `/` → `/en` around the clock it held 1 857 of 4 181 reported pageviews.

So after the per-request rules, a whole-window pass groups requests by
User-Agent and demotes an identity out of the audience **only when all three**
hold:

1. it produced **≥ 100 human pageviews** in the window (`--automation-threshold`);
2. it fetched **exactly zero** static assets across the whole window;
3. it was active on **≥ 5 days**.

Below **10 days** of data the pass suppresses itself and changes nothing, and
says so in the report.

**The asymmetry, and why the floor is high.** Fetching an asset *proves* a
browser; never fetching one is evidence only *at volume*. Cloudflare serves
`/_next/static` from the edge (immutable, cached a year) and the browser cache
serves it again, so a returning reader's page requests reach the origin alone:
61–64% of ordinary reader User-Agents here fetch **no** asset at all. Zero
assets is the *normal* condition of a real reader. Over 15 days the largest
innocent zero-asset User-Agent held 42 pageviews and the smaller of the two
scraper pools held 415 — a 9.9× gap with nothing inside it. A floor of 20 would
have destroyed 931 genuine pageviews across 32 real reader populations.
**Do not lower `--automation-threshold` without re-measuring that gap.**

**How it fails, in both directions** — the report prints all of this in its
footnotes, every run:

| Failure | Direction |
|---|---|
| The verdict is per **User-Agent string**, not per person, so a demoted string takes any real reader sending that exact string with it. | Deletes readers |
| A scraper that fetches **one asset per window** defeats the test entirely — one fetch exempts an identity. | Keeps bots |
| It is scoped to the report's window, so a different `--since` can reach a different verdict about the same User-Agent. | Both |
| Fetching assets never *whitelists* anything: `Baiduspider-render` fetches `/_next/static/chunks/*.js`, and the signature catalogue still outranks behaviour. | — |

It is a **report-time** judgement and is never written back into the store:
stored rows keep the per-request verdict, so `ingest --reingest` stays
reproducible and the rule can be revised as evidence accrues. The subtraction
appears as its own row in the DATA QUALITY funnel, and every demoted
User-Agent is named with its evidence under `SUSPECTED AUTOMATION (DEMOTED)` in
the automated appendix.

### Log access (the `adm` group)

nginx logs are `0640 www-data:adm`, so reading them needs `adm` membership:

```bash
# One time, then log out and back in.
sudo usermod -aG adm <user>
```

**Group membership only applies to NEW login sessions.** After running it, log
out and back in — or, for the current shell only, `newgrp adm`. Check with
`id -nG`. The systemd unit gets there its own way, via
`SupplementaryGroups=adm`, so the nightly timer works whether or not you ever
add yourself. If it is missing, the tool tells you exactly this and exits 1
rather than silently reporting zero.

### Legacy vs extended logs — read this before trusting a trend

The tool reads **both** the old combined-format `access.log` and the new
extended JSON log, in the same run and the same report, detecting the format
**per line** (a rotated file spans the reload boundary and legitimately holds
both). Every report opens with a `DATA COVERAGE` banner naming the exact date
range held and which dimensions were unavailable for part of it.

For days before the nginx change, these are **suppressed with a stated reason,
not zeroed**: country, unique visitors, sessions, bounce, pages/visit, duration,
the language × locale matrix, all client-hint dimensions, the
hard/soft/prefetch split, and all latency. Still available on legacy days:
pageviews, locale split, top articles, entry pages, 404s, acquisition channel,
browser/OS/device from the User-Agent, time-of-day — and, importantly,
Cloudflare provenance and forged-crawler detection, which work on old logs with
no nginx change at all.

**The one trap:** legacy lines carry no prefetch header, so `?_rsc=` requests
are excluded from legacy pageviews entirely, making them hard navigations only —
a **lower bound**. The day the nginx change lands, the pageview series steps up
for methodological reasons. That is a measurement change, not growth, and the
report labels it. Do not read that step as a traffic win.

### Reading the numbers

Three caveats worth carrying in your head, all of which the report also prints
in its footer:

* **Bots are excluded, and the subtraction is shown.** The bot percentage is a
  share of *requests reaching the origin*, not of all traffic — Cloudflare
  already absorbed an unknown amount at the edge.
* **Bounce rate is an upper bound.** App Router back/forward navigation emits no
  request, so some engaged visits are indistinguishable from a single-page one.
* **Visitor counts undercount.** Carrier NAT (Kyivstar, Vodafone, lifecell)
  merges several people behind one address, so the true figure is *higher* than
  reported. The bias has a known direction, which is why the number is still
  worth printing.

One condition to be aware of and **not** to fix: the vhost listens on IPv4 only,
and over IPv6 another vhost owns the default. Harmless today, because Cloudflare
only reaches the origin over IPv6 if an AAAA record exists. But **if an AAAA
origin record is ever added, cyberalertx traffic silently starts being served by
another vhost and vanishes from this log.** The symptom is the new log staying
empty while traffic flows. Do not "fix" it by adding `listen [::]:443` to this
vhost — it sorts first alphabetically and would steal the IPv6 default from
whichever sibling vhost currently holds it.

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

### 9. Audience numbers are still plausible

```bash
sudo -u <user> bash -c 'cd <app-dir> && source venv/bin/activate \
  && python -m server.analytics report --since 7d'
```

Expected: ~290 human pageviews/day, EN/UA roughly 71/29. A sudden jump into
the thousands means the bot filter broke, not that the site went viral —
check Cloudflare provenance filtering, the `/healthz` path exclusion, and
prefetch filtering, in that order. Also confirm the nightly ingest is
actually running:

```bash
systemctl list-timers --no-pager | grep analytics
sudo journalctl -u cyberalertx-analytics.service --since "48 hours ago" | tail -20
```

A gap in ingest is unrecoverable once logrotate drops the source file, so
`python -m server.analytics status` reporting missing days is worth acting
on the same week.

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
| Pull the audience report | `ssh <user>@<your-domain> 'cd <app-dir> && source venv/bin/activate && python -m server.analytics report --since 7d'` |
| Check the analytics store | `ssh <user>@<your-domain> 'cd <app-dir> && source venv/bin/activate && python -m server.analytics status'` |
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
