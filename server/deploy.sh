#!/usr/bin/env bash
# Update the running app on the VPS.
#
# Run AS THE APP USER (cax) from the app dir:
#     cd ~/cax && ./server/deploy.sh
#
# What it does:
#   1. fetch + hard-reset to origin/main (mirrors GitHub exactly)
#   2. pip install -r requirements.txt (catches new deps)
#   3. npm ci + npm run build (frontend)
#   4. systemctl restart api + frontend (run keeps cycling)
#
# Does NOT touch:
#   - .env (manual; never automated)
#   - data/ (runtime state)
#   - migrations — run `python -m cyberalertx.tools.pg_migrate` manually if added
#
# The box is a deploy mirror, not a dev checkout: step 1 is a hard reset, not
# a `git pull --ff-only`. A plain ff-only pull aborts the moment the box's
# local main diverges from origin (e.g. a stray on-box commit), which silently
# wedges every future deploy. Hard-resetting to origin/main is self-healing —
# the box always lands exactly where GitHub is. This DISCARDS any local commits
# or tracked-file edits made directly on the box; .env / data/ / venv / build
# artifacts are gitignored, so runtime state and secrets are never affected.
# If you must hotfix on the box, commit and push it to origin/main instead.
#
# Exit non-zero on any failure so cron/scripts pick up issues.

set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, regardless of where called from
APP_DIR="$(pwd)"

echo "→ Deploying ${APP_DIR}"

# ----- 1. Latest code -------------------------------------------------
# Mirror origin/main exactly. Hard reset (not ff-only pull) so a diverged
# box can't wedge the deploy — see header note. `--prune` clears stale
# remote refs; the reset targets the freshly fetched ref.
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
git fetch --prune origin "${DEPLOY_BRANCH}"
git checkout --quiet "${DEPLOY_BRANCH}"
git reset --hard "origin/${DEPLOY_BRANCH}"

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
