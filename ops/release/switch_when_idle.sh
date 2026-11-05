#!/bin/bash
# =============================================================================
# CyberAlertX: switch the active release only while no writer is working.
#
#   sudo bash ops/release/switch_when_idle.sh <release-id> [max-wait-seconds, default 600]
#
# Writers that can be mid-write during a switch:
#   * cyberalertx-generate.service (one-shot, fired hourly by its timer): busy while active;
#   * cyberalertx-run (ingest loop): busy while its journal shows an apscheduler
#     "Running job" line with no later "executed successfully"/"raised" line.
# It waits (bounded) for both to be idle, then hands over to release_switch.sh,
# which does the switch, restarts and health checks.
#
# Fails closed: if the target is not a valid release, if the writer state cannot
# be determined, or if writers are still busy after the wait, it exits non-zero
# WITHOUT switching. It never stops or kills a writer, never runs migrations and
# never enables publishing. Interrupting it (Ctrl-C) before the hand-over leaves
# `current` unchanged.
#
# Source of truth: this file. Host copy: /home/cax/stagec-tools/switch_when_idle.sh
# (it replaces the cutover-day d1_switch.sh, which did the same without the
# validation, lock and fail-closed checks).
# =============================================================================
set -Eeuo pipefail
TARGET=${1:-}; MAXWAIT=${2:-600}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ "${SW_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${SW_SYSTEMCTL:?}; JOURNALCTL=${SW_JOURNALCTL:?}; SWITCH=${SW_SWITCH:?}; ROOT=${SW_ROOT:?}; SLEEP=${SW_SLEEP:-true}
  NOW=${SW_NOW:-date +%s}
else
  SYSTEMCTL=systemctl; JOURNALCTL=journalctl; SWITCH="bash $HERE/release_switch.sh"; ROOT=/home/cax/cyberalertx; SLEEP="sleep 5"
  NOW="date +%s"
fi
log() { printf '%s [switch-when-idle] %s\n' "$(date '+%F %T')" "$*"; }
abort() { log "ABORTED, nothing switched: $*"; exit 3; }
trap 'log "interrupted before the hand-over; nothing switched"; exit 130' INT TERM
[ "${SW_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
[ -n "$TARGET" ] || { echo "usage: $0 <release-id> [max-wait-seconds]"; exit 2; }
case "$TARGET" in */*|.*|*" "*) abort "release id must be a plain directory name";; esac
[ -d "$ROOT/releases/$TARGET" ] || abort "no release $ROOT/releases/$TARGET"
grep -qE '^commit=[0-9a-f]{40}$' "$ROOT/releases/$TARGET/RELEASE" || abort "release records no commit"
case "$MAXWAIT" in ''|*[!0-9]*) abort "max wait must be a number of seconds";; esac

writers_busy() {          # prints the busy writers; returns 2 when the state is unknown
  local busy="" gen pid last
  gen=$($SYSTEMCTL is-active cyberalertx-generate.service 2>/dev/null || true)
  case "$gen" in active|activating|deactivating) busy="generate running";; inactive|failed) ;; *) echo "generate state '$gen'"; return 2;; esac
  [ "$($SYSTEMCTL is-active cyberalertx-run 2>/dev/null || true)" = active ] || { echo "${busy:+$busy, }run not active"; [ -z "$busy" ] && return 0 || return 1; }
  pid=$($SYSTEMCTL show -p MainPID --value cyberalertx-run 2>/dev/null || true)
  case "$pid" in ''|0|*[!0-9]*) echo "run MainPID unknown"; return 2;; esac
  last=$($JOURNALCTL -b "_PID=$pid" -o cat --no-pager 2>/dev/null \
         | grep -E 'apscheduler\.executors[^]]*\] (Running job|Job .*(executed successfully|raised an exception))|scheduler started' \
         | tail -1) || { echo "run journal unreadable"; return 2; }
  [ -n "$last" ] || { echo "run journal has no scheduler lines"; return 2; }
  case "$last" in *"Running job"*) busy="${busy:+$busy, }ingest cycle running";; esac
  echo "$busy"; [ -z "$busy" ]
}

end=$(( $($NOW) + MAXWAIT ))
while :; do
  set +e; state=$(writers_busy); rc=$?; set -e
  [ "$rc" = 2 ] && abort "cannot determine writer state ($state)"
  [ "$rc" = 0 ] && break
  [ "$($NOW)" -lt "$end" ] || abort "writers still busy after ${MAXWAIT}s ($state)"
  log "waiting: $state"; $SLEEP
done
log "writers idle; handing over to release_switch.sh $TARGET"
trap - INT TERM
exec $SWITCH "$TARGET"
