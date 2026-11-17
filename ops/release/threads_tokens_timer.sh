#!/bin/bash
# =============================================================================
# CyberAlertX: Threads token maintenance timer (verify + refresh; never publishes).
#
#   sudo bash ops/release/threads_tokens_timer.sh install     # back up, install units, enable timer, run once
#   sudo bash ops/release/threads_tokens_timer.sh uninstall   # disable timer, remove the two units
#   sudo bash ops/release/threads_tokens_timer.sh check       # read-only status
#
# Run from the ACTIVE release ($APP_ROOT/current/ops/release/...). Installs only
# cyberalertx-threads-tokens.{service,timer}; touches no other unit, not .env,
# not THREADS_ENABLED, not Telegram. The one run after install refreshes a token
# only if it is due (>= 24 h old, < 30 days left); otherwise it only verifies.
# =============================================================================
set -Eeuo pipefail
MODE=${1:-}
if [ "${TT_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${TT_SYSTEMCTL:?}; UNIT_DIR=${TT_UNIT_DIR:?}; CUR=${TT_CURRENT:?}; BK_ROOT=${TT_BACKUPS:?}
else
  SYSTEMCTL=systemctl; UNIT_DIR=/etc/systemd/system; CUR=/home/cax/cyberalertx/current; BK_ROOT=/home/cax/backups
fi
UNITS="cyberalertx-threads-tokens.service cyberalertx-threads-tokens.timer"
fail() { trap - ERR; echo "THREADS TOKEN TIMER ${MODE^^} FAILED: $*"; exit 1; }
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR
[ "${TT_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

status() {
  echo "  timer:   $($SYSTEMCTL is-enabled cyberalertx-threads-tokens.timer 2>/dev/null || true)/$($SYSTEMCTL is-active cyberalertx-threads-tokens.timer 2>/dev/null || true)"
  echo "  next:    $($SYSTEMCTL show -p NextElapseUSecRealtime --value cyberalertx-threads-tokens.timer 2>/dev/null || true)"
  echo "  last:    $($SYSTEMCTL show -p Result --value cyberalertx-threads-tokens.service 2>/dev/null || true)"
}

case "$MODE" in
  check) status ;;
  install)
    for u in $UNITS; do [ -f "$CUR/server/systemd/$u" ] || fail "active release lacks server/systemd/$u (deploy it first)"; done
    grep -q '"maintain"' "$CUR/cyberalertx/tools/threads.py" || fail "active release lacks 'tools.threads maintain'"
    grep -q "threads_publish\|tools.publish" "$CUR/server/systemd/cyberalertx-threads-tokens.service" \
      && fail "service template must not publish"
    BK=$BK_ROOT/threads-tokens-timer-$(date +%Y%m%d-%H%M%S); umask 077; mkdir -p "$BK"
    for u in $UNITS; do [ -f "$UNIT_DIR/$u" ] && cp -a "$UNIT_DIR/$u" "$BK/"; done
    for u in $UNITS; do install -m 0644 "$CUR/server/systemd/$u" "$UNIT_DIR/.$u.tt" && mv -f "$UNIT_DIR/.$u.tt" "$UNIT_DIR/$u"; done
    $SYSTEMCTL daemon-reload
    $SYSTEMCTL enable --now cyberalertx-threads-tokens.timer >/dev/null
    $SYSTEMCTL start cyberalertx-threads-tokens.service || fail "first run failed: journalctl -u cyberalertx-threads-tokens -n 30 (timer stays installed; uninstall to revert)"
    trap - ERR
    echo "----- THREADS TOKEN TIMER INSTALLED -----"; status
    echo "  backup:  $BK"
    echo "  revert:  sudo bash $0 uninstall" ;;
  uninstall)
    $SYSTEMCTL disable --now cyberalertx-threads-tokens.timer >/dev/null 2>&1 || true
    for u in $UNITS; do rm -f "$UNIT_DIR/$u"; done
    $SYSTEMCTL daemon-reload
    trap - ERR
    echo "----- THREADS TOKEN TIMER REMOVED (tokens and .env untouched) -----" ;;
  *) echo "usage: $0 install | uninstall | check"; exit 2 ;;
esac
