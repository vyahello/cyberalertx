#!/usr/bin/env bash
# Update the running app on the VPS.
#
# Run AS THE APP USER (cax) from the app dir:
#     cd ~/cax && ./server/deploy.sh
#
# What it does:
#   1. git pull (assumes you've pushed from dev)
#   2. pip install -r requirements.txt (catches new deps)
#   3. npm ci + npm run build (frontend)
#   4. systemctl restart api + frontend (run keeps cycling)
#
# Does NOT touch:
#   - .env (manual; never automated)
#   - data/ (runtime state)
#   - migrations — run `python -m cyberalertx.tools.pg_migrate` manually if added
#
# Exit non-zero on any failure so cron/scripts pick up issues.

set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of where called from
APP_DIR="$(pwd)"

echo "→ Deploying ${APP_DIR}"

# ----- 1. Latest code -------------------------------------------------
git pull --ff-only

# ----- 2. Backend deps ------------------------------------------------
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ----- 3. Frontend build ----------------------------------------------
cd frontend
npm ci --quiet
npm run build
cd ..

# ----- 4. Restart user services --------------------------------------
# `run` doesn't need restart on code change — it'll re-import on next
# cycle. Add it if you've changed pipeline / ingest logic specifically.
sudo systemctl restart cyberalertx-api cyberalertx-frontend

echo "✓ Deployed at $(date -Iseconds)"
