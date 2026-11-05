#!/bin/bash
# =============================================================================
# CyberAlertX: restore scheduled Telegram publishing on the release architecture.
#
#   sudo bash ops/release/telegram_activate.sh activate     # verify, back up, install, baseline, enable
#   sudo bash ops/release/telegram_activate.sh deactivate   # emergency stop: hold back on, timer off
#   sudo bash ops/release/telegram_activate.sh check        # read-only status
#
# activate (run from the ACTIVE release: /home/cax/cyberalertx/current/ops/release/...):
#   1. preflight: the active release contains the publication engine with `baseline` and
#      `check-telegram`, the unit templates and the hold drop-in;
#   2. read-only Bot API check (bot identity; each configured channel reachable, bot is an
#      administrator allowed to post). Nothing is sent;
#   3. one media run, so current stories have their canonical illustration;
#   4. backup (mode 700): telegram + generate units, timers, the drop-in, the publish
#      ledger and job store;
#   5. install the tracked telegram and generate units (paths on `current`; telegram runs
#      `tools.publish cycle --send --limit 1`); the hold drop-in stays installed;
#   6. baseline: plan (imports the ledger) and cancel Telegram jobs for every article
#      published before now — no backlog, no replay;
#   7. create /home/cax/cyberalertx/STAGE_D_AUTHORIZED (satisfies the hold) and enable the
#      EXISTING timer (schedule unchanged). The first scheduled run is the live check.
# Never sends a test message, never touches Threads, .env, data other than the job store,
# or any other unit.
# =============================================================================
set -Eeuo pipefail
MODE=${1:-}
if [ "${TA_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${TA_SYSTEMCTL:?}; UNIT_DIR=${TA_UNIT_DIR:?}; CUR=${TA_CURRENT:?}; BK_ROOT=${TA_BACKUPS:?}
  MARK=${TA_MARKER:?}; DATA=${TA_DATA:?}; RUN_AS=${TA_RUN_AS:?}
else
  SYSTEMCTL=systemctl; UNIT_DIR=/etc/systemd/system; CUR=/home/cax/cyberalertx/current
  BK_ROOT=/home/cax/backups; MARK=/home/cax/cyberalertx/STAGE_D_AUTHORIZED; DATA=/home/cax/cax/data
  RUN_AS="sudo -u cax bash -c"
fi
APP() { $RUN_AS ". '$CUR/ops/release/loadenv.sh' && loadenv /home/cax/cax/.env && cd '$CUR' && venv/bin/python -m $*"; }
fail() { trap - ERR; echo "TELEGRAM ${MODE^^} FAILED: $*"; exit 1; }
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR
[ "${TA_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

status() {
  echo "  service:  $($SYSTEMCTL is-active cyberalertx-telegram.service 2>/dev/null || true)"
  echo "  timer:    $($SYSTEMCTL is-enabled cyberalertx-telegram.timer 2>/dev/null || true)/$($SYSTEMCTL is-active cyberalertx-telegram.timer 2>/dev/null || true)"
  echo "  hold:     drop-in $( [ -f "$UNIT_DIR/cyberalertx-telegram.service.d/stage-c-hold.conf" ] && echo installed || echo MISSING ), marker $( [ -e "$MARK" ] && echo present || echo absent )"
  echo "  command:  $($SYSTEMCTL cat cyberalertx-telegram 2>/dev/null | sed -n 's/^ExecStart=//p' | head -1)"
}

case "$MODE" in
  check) status ;;
  deactivate)
    rm -f "$MARK"
    $SYSTEMCTL disable --now cyberalertx-telegram.timer >/dev/null 2>&1 || true
    trap - ERR
    echo "----- TELEGRAM DEACTIVATED: marker removed (hold in force), timer disabled -----"; status ;;
  activate)
    for f in server/systemd/cyberalertx-telegram.service server/systemd/cyberalertx-generate.service \
             server/systemd/cyberalertx-telegram.service.d/stage-c-hold.conf ops/release/loadenv.sh; do
      [ -f "$CUR/$f" ] || fail "active release lacks $f (deploy the release first)"
    done
    grep -q "tools.publish cycle --send" "$CUR/server/systemd/cyberalertx-telegram.service" || fail "telegram template is not the publication engine"
    grep -q "baseline" "$CUR/cyberalertx/tools/publish.py" || fail "release lacks the baseline command"
    [ "$($SYSTEMCTL show -p WorkingDirectory --value cyberalertx-api)" = "$CUR" ] || fail "api does not run from $CUR"
    echo "== Bot API check (read-only)"; APP cyberalertx.tools.publish check-telegram || fail "Telegram check failed: nothing changed"
    echo "== media run (canonical illustrations)"; APP cyberalertx.tools.media run --max-calls 300 >/dev/null || fail "media run failed: nothing changed"
    BK=$BK_ROOT/telegram-activation-$(date +%Y%m%d-%H%M%S); umask 077; mkdir -p "$BK/units"
    cp -a "$UNIT_DIR"/cyberalertx-telegram.* "$UNIT_DIR"/cyberalertx-generate.* "$BK/units/"
    for f in telegram_published.jsonl publish_jobs.json; do [ -f "$DATA/$f" ] && cp -a "$DATA/$f" "$BK/"; done
    (cd "$BK" && find . -type f -print0 | xargs -0 sha256sum > SHA256SUMS)
    for u in cyberalertx-telegram.service cyberalertx-generate.service; do
      install -m 0644 "$CUR/server/systemd/$u" "$UNIT_DIR/.$u.ta" && mv -f "$UNIT_DIR/.$u.ta" "$UNIT_DIR/$u"
    done
    mkdir -p "$UNIT_DIR/cyberalertx-telegram.service.d"
    install -m 0644 "$CUR/server/systemd/cyberalertx-telegram.service.d/stage-c-hold.conf" \
      "$UNIT_DIR/cyberalertx-telegram.service.d/stage-c-hold.conf"
    $SYSTEMCTL daemon-reload
    $SYSTEMCTL cat cyberalertx-telegram | grep -q "tools.publish cycle --send --limit 1" || fail "unit not installed; restore from $BK"
    case "$($SYSTEMCTL show -p DropInPaths --value cyberalertx-telegram)" in *stage-c-hold.conf*) ;; *) fail "hold drop-in not loaded";; esac
    echo "== baseline: no backlog"; APP cyberalertx.tools.publish baseline --before "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" \
      || fail "baseline failed; marker NOT created, timer NOT enabled; units backed up in $BK"
    touch "$MARK"; chmod 0644 "$MARK"
    $SYSTEMCTL enable --now cyberalertx-telegram.timer >/dev/null
    [ "$($SYSTEMCTL is-active cyberalertx-telegram.timer)" = active ] || fail "timer not active"
    trap - ERR
    echo "----- TELEGRAM ACTIVATED -----"; status
    echo "  next run: $($SYSTEMCTL show -p NextElapseUSecRealtime --value cyberalertx-telegram.timer)"
    echo "  backup:   $BK"
    echo "  stop:     sudo bash $0 deactivate" ;;
  *) echo "usage: $0 activate | deactivate | check"; exit 2 ;;
esac
