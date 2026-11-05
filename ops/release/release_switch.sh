#!/bin/bash
# =============================================================================
# CyberAlertX: make an existing IMMUTABLE release the active one.
#
#   sudo bash ops/release/release_switch.sh <release-id>
#
# Use it to activate a newly built release (forward) or to go back to an
# earlier one (rollback): it is the same operation. It does NOT build a
# release, run database migrations, touch publishing, or edit .env.
#
#   0. Preflight: the target release exists and is complete (RELEASE records a
#      commit, venv python, frontend build, data -> the persistent data dir);
#      the api, run, generate units run from `current`, frontend from
#      `current/frontend`. One switch at a time (lock).
#   1. Switch `current` atomically (symlink to a temp name + rename).
#   2. Restart api, frontend, run; wait for health (API /healthz 200, site 200).
#      On failure: report, and print the exact command that switches back.
#      `current` is NOT switched back automatically.
# Untouched: .env, systemd units and drop-ins, timers (generate picks up
# `current` at its next run), Telegram hold, analytics, data/, the database.
#
# Source of truth: this file in the repository. Installed on the host as
# /home/cax/stagec-tools/release_switch.sh (docs/operations/OPERATIONS.md).
# Its predecessor, release_rollback.sh, did the same with misleading output.
# =============================================================================
set -Eeuo pipefail
TARGET=${1:-}
if [ "${RB_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${RB_SYSTEMCTL:?}; CURL=${RB_CURL:?}; ROOT=${RB_ROOT:?}; WAIT=${RB_WAIT:-3}; DATA=${RB_DATA:?}
  SLEEP=${RB_SLEEP:-true}
else
  SYSTEMCTL=systemctl; CURL=curl; ROOT=/home/cax/cyberalertx; WAIT=90; DATA=/home/cax/cax/data; SLEEP="sleep 1"
fi
CUR=$ROOT/current; REL=$ROOT/releases/$TARGET; LOCK=$ROOT/.release-switch.lock
fail() { trap - ERR; echo "RELEASE SWITCH FAILED: $*"; echo "  active release: $(readlink "$CUR" 2>/dev/null || echo '?')"; exit 1; }
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR
commit_of() { sed -n 's/^commit=//p' "$1/RELEASE" 2>/dev/null | head -1; }
[ "${RB_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
[ -n "$TARGET" ] || { echo "usage: $0 <release-id>   (ls $ROOT/releases)"; exit 2; }
case "$TARGET" in */*|.*|*" "*) fail "release id must be a plain directory name";; esac

exec 9>"$LOCK"
flock -n 9 || fail "another release switch is running (lock $LOCK)"

# ---- 0. preflight ------------------------------------------------------------------------------
[ -d "$REL" ] && [ ! -L "$REL" ] || fail "no release directory $REL"
grep -qE '^commit=[0-9a-f]{40}$' "$REL/RELEASE" || fail "$REL/RELEASE records no commit"
[ -x "$REL/venv/bin/python" ] || fail "release venv missing"
[ -f "$REL/frontend/.next/BUILD_ID" ] || fail "release frontend build missing"
[ "$(readlink "$REL/data")" = "$DATA" ] || fail "release data link is '$(readlink "$REL/data")', expected $DATA"
for u in api run generate; do
  [ "$($SYSTEMCTL show -p WorkingDirectory --value cyberalertx-$u)" = "$CUR" ] || fail "cyberalertx-$u does not run from $CUR"
done
[ "$($SYSTEMCTL show -p WorkingDirectory --value cyberalertx-frontend)" = "$CUR/frontend" ] || fail "frontend does not run from $CUR/frontend"
PREV=$(readlink "$CUR" || true)
[ "$PREV" != "$REL" ] || { echo "ACTIVE RELEASE UNCHANGED: current already points to $REL"; exit 0; }
PREV_ID=$(basename "${PREV:-none}"); PREV_COMMIT=$(commit_of "$PREV"); NEW_COMMIT=$(commit_of "$REL")
if [ -n "$PREV" ] && [[ "$TARGET" < "$PREV_ID" ]]; then KIND="rollback to an earlier release"; else KIND="forward to a newer release"; fi
echo "preflight OK: $PREV_ID (${PREV_COMMIT:0:7}) -> $TARGET (${NEW_COMMIT:0:7}), $KIND"

# ---- 1. atomic switch --------------------------------------------------------------------------
ln -sfn "$REL" "$CUR.switch-tmp" && mv -T "$CUR.switch-tmp" "$CUR" || fail "could not switch current"
[ "$(readlink "$CUR")" = "$REL" ] || fail "current is not $REL after switch"

# ---- 2. restart + health -----------------------------------------------------------------------
BACK="sudo bash $0 $PREV_ID"
$SYSTEMCTL restart cyberalertx-api cyberalertx-frontend cyberalertx-run \
  || fail "restart failed after the switch; to go back: $BACK"
ok=0; a=; s=; for _ in $(seq "$WAIT"); do
  a=$($CURL -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/healthz || true)
  s=$($CURL -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:3000/en || true)
  [ "$a" = 200 ] && [ "$s" = 200 ] && { ok=1; break; }; $SLEEP; done
[ "$ok" = 1 ] || fail "not healthy after the switch (api=$a site=$s); to go back: $BACK"
trap - ERR
echo "----- RELEASE SWITCH COMPLETED ($KIND) -----"
echo "  previous release: $PREV_ID (commit ${PREV_COMMIT:-?})"
echo "  active release:   $TARGET (commit $NEW_COMMIT)"
echo "  health:           api /healthz $a, site /en $s"
echo "  restarted:        cyberalertx-api, cyberalertx-frontend, cyberalertx-run"
echo "  unchanged:        .env, units and drop-ins, timers, Telegram hold, analytics, data, database"
echo "  to go back:       $BACK"
