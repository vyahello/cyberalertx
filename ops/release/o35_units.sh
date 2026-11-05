#!/bin/bash
# =============================================================================
# CyberAlertX O35: run cyberalertx-analytics and the HELD cyberalertx-telegram from the
# active release (/home/cax/cyberalertx/current) instead of the git checkout.
#
#   sudo bash ops/release/o35_units.sh apply          # backup, install, verify, one analytics run
#   sudo bash ops/release/o35_units.sh revert <dir>   # restore the unit files from a backup dir
#   sudo bash ops/release/o35_units.sh check          # read-only verification
#
# apply:
#   1. preflight: the active release has venv/bin/python, server/analytics and
#      cyberalertx/main.py; the Telegram hold drop-in is installed, its timer is
#      disabled and inactive, STAGE_D_AUTHORIZED is absent;
#   2. backs up both unit files and the Telegram drop-in dir to
#      /home/cax/backups/o35-units-<timestamp>/ (mode 700);
#   3. installs server/systemd/cyberalertx-{analytics,telegram}.service from this
#      repository (paths only change: WorkingDirectory and the python path);
#   4. daemon-reload, then verifies paths, the hold (ConditionPathExists still
#      loaded), timers unchanged (analytics enabled, telegram disabled);
#   5. starts cyberalertx-analytics.service ONCE (the same idempotent ingest the
#      03:00 timer runs; duplicates are skipped) and checks it succeeded.
# Never starts, enables or tests Telegram; never creates STAGE_D_AUTHORIZED;
# never touches .env, data/, the database, or any other unit.
# =============================================================================
set -Eeuo pipefail
MODE=${1:-}
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "$HERE/../../server/systemd" && pwd)
if [ "${O35_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${O35_SYSTEMCTL:?}; UNIT_DIR=${O35_UNIT_DIR:?}; CUR=${O35_CURRENT:?}; BK_ROOT=${O35_BACKUPS:?}; MARK=${O35_MARKER:?}
else
  SYSTEMCTL=systemctl; UNIT_DIR=/etc/systemd/system; CUR=/home/cax/cyberalertx/current
  BK_ROOT=/home/cax/backups; MARK=/home/cax/cyberalertx/STAGE_D_AUTHORIZED
fi
fail() { trap - ERR; echo "O35 FAILED ($MODE): $*"; exit 1; }
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR
[ "${O35_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

hold_ok() {
  [ -f "$UNIT_DIR/cyberalertx-telegram.service.d/stage-c-hold.conf" ] || fail "Telegram hold drop-in missing"
  case "$($SYSTEMCTL show -p DropInPaths --value cyberalertx-telegram)" in *stage-c-hold.conf*) ;; *) fail "hold drop-in not loaded";; esac
  $SYSTEMCTL cat cyberalertx-telegram 2>/dev/null | grep -qx "ConditionPathExists=$MARK" \
    || fail "ConditionPathExists=$MARK not in effect"
  [ "$($SYSTEMCTL is-enabled cyberalertx-telegram.timer 2>/dev/null || true)" = disabled ] || fail "Telegram timer is not disabled"
  [ "$($SYSTEMCTL is-active cyberalertx-telegram.timer 2>/dev/null || true)" != active ] || fail "Telegram timer is active"
  [ "$($SYSTEMCTL is-active cyberalertx-telegram.service 2>/dev/null || true)" != active ] || fail "Telegram service is running"
  [ ! -e "$MARK" ] || fail "$MARK exists (Stage D marker); refusing"
}
paths_ok() {   # $1 = expected working directory
  for u in analytics telegram; do
    [ "$($SYSTEMCTL show -p WorkingDirectory --value cyberalertx-$u)" = "$1" ] || fail "cyberalertx-$u WorkingDirectory is not $1"
  done
}

case "$MODE" in
  check)
    hold_ok; paths_ok "$CUR"
    [ "$($SYSTEMCTL is-enabled cyberalertx-analytics.timer 2>/dev/null || true)" = enabled ] || fail "analytics timer not enabled"
    echo "O35 CHECK OK: analytics and telegram run from $CUR; Telegram held (timer disabled, marker absent)";;
  apply)
    [ -x "$CUR/venv/bin/python" ] && [ -f "$CUR/server/analytics/__main__.py" ] && [ -f "$CUR/cyberalertx/main.py" ] \
      || fail "active release lacks venv, server/analytics or cyberalertx/main.py"
    for u in analytics telegram; do [ -f "$SRC/cyberalertx-$u.service" ] || fail "template $SRC/cyberalertx-$u.service missing"
      grep -q "^WorkingDirectory=$CUR$" "$SRC/cyberalertx-$u.service" || fail "template $u does not use $CUR"; done
    hold_ok
    BK=$BK_ROOT/o35-units-$(date +%Y%m%d-%H%M%S); umask 077; mkdir -p "$BK"
    cp -a "$UNIT_DIR/cyberalertx-analytics.service" "$UNIT_DIR/cyberalertx-telegram.service" "$BK/"
    cp -a "$UNIT_DIR/cyberalertx-telegram.service.d" "$BK/"
    for u in analytics telegram; do
      cp "$SRC/cyberalertx-$u.service" "$UNIT_DIR/.cyberalertx-$u.service.o35" && chmod 0644 "$UNIT_DIR/.cyberalertx-$u.service.o35"
      mv -f "$UNIT_DIR/.cyberalertx-$u.service.o35" "$UNIT_DIR/cyberalertx-$u.service"
    done
    $SYSTEMCTL daemon-reload
    paths_ok "$CUR"; hold_ok
    [ "$($SYSTEMCTL is-enabled cyberalertx-analytics.timer 2>/dev/null || true)" = enabled ] || fail "analytics timer not enabled"
    $SYSTEMCTL start cyberalertx-analytics.service || fail "analytics run failed; revert: sudo bash $0 revert $BK"
    [ "$($SYSTEMCTL show -p Result --value cyberalertx-analytics.service)" = success ] || fail "analytics result not success; revert: sudo bash $0 revert $BK"
    trap - ERR
    echo "----- O35 APPLY COMPLETED -----"
    echo "  analytics: runs from $CUR; one ingest run succeeded; timer unchanged (enabled)"
    echo "  telegram:  runs from $CUR when Stage D is authorized; still HELD (drop-in loaded, timer disabled, marker absent)"
    echo "  backup:    $BK"
    echo "  revert:    sudo bash $0 revert $BK";;
  revert)
    BK=${2:?usage: $0 revert <backup-dir>}
    for f in cyberalertx-analytics.service cyberalertx-telegram.service; do [ -f "$BK/$f" ] || fail "$BK/$f missing"; done
    for f in cyberalertx-analytics.service cyberalertx-telegram.service; do
      cp -a "$BK/$f" "$UNIT_DIR/.$f.o35" && mv -f "$UNIT_DIR/.$f.o35" "$UNIT_DIR/$f"; done
    $SYSTEMCTL daemon-reload; hold_ok
    trap - ERR
    echo "----- O35 REVERT COMPLETED: unit files restored from $BK (Telegram still held) -----";;
  *) echo "usage: $0 apply | revert <backup-dir> | check"; exit 2;;
esac
