#!/bin/bash
# =============================================================================
# CyberAlertX: temporary JSON-only override for the API (recovery switch).
#
#   sudo bash ops/release/api_json_reads.sh apply     # API reads/writes JSON only; restart API
#   sudo bash ops/release/api_json_reads.sh revert    # remove the override;        restart API
#
# Use `apply` if the dual-mode read path (O27) misbehaves in production: it adds
# a drop-in to cyberalertx-api that loads /home/cax/stagec-tools/api-json-backend.env
# (exactly `CYBERALERTX_STORAGE_BACKEND=json`) after .env. Only the API changes;
# run/generate keep dual-writing. While applied, editor decisions are saved to
# JSON only: re-sync Postgres before reverting (docs/release/O28_RECONCILIATION_RUNBOOK.md).
# .env is never edited.
#
# Source of truth: this file. Host copy: /home/cax/stagec-tools/c8_api_json_reads.sh
# (Stage C name; same behaviour). Applied 4 Nov 2026 17:28, reverted 5 Nov 09:50.
# =============================================================================
set -Eeuo pipefail
MODE=${1:-}
if [ "${C8_TEST:-0}" = 1 ]; then SYSTEMCTL=${C8_SYSTEMCTL:?}; CURL=${C8_CURL:?}; UNIT_DIR=${C8_UNIT_DIR:?}; ENVF=${C8_ENVF:?}; WAIT=${C8_WAIT:-3}
else SYSTEMCTL=systemctl; CURL=curl; UNIT_DIR=/etc/systemd/system; ENVF=/home/cax/stagec-tools/api-json-backend.env; WAIT=60; fi
D=$UNIT_DIR/cyberalertx-api.service.d; F=$D/stage-c-json-reads.conf
BODY="[Service]
# Stage C hotfix: API reads/writes the JSON store only (see c8_api_json_reads.sh)
EnvironmentFile=$ENVF"
fail() { trap - ERR; echo "FAILED ($MODE): $*"; echo "  api=$($SYSTEMCTL is-active cyberalertx-api 2>/dev/null || true) dropin=$([ -f "$F" ] && echo present || echo absent)"; exit 1; }
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR
[ "${C8_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
case "$MODE" in apply|revert) ;; *) echo "usage: $0 apply|revert"; exit 2;; esac
[ "$($SYSTEMCTL show -p WorkingDirectory --value cyberalertx-api)" = /home/cax/cyberalertx/current ] || fail "API is not running from the release"

if [ "$MODE" = apply ]; then
  [ -f "$ENVF" ] && [ "$(cat "$ENVF")" = "CYBERALERTX_STORAGE_BACKEND=json" ] || fail "$ENVF must contain exactly CYBERALERTX_STORAGE_BACKEND=json"
  mkdir -p "$D"; tmp=$(mktemp "$D/.c8.XXXXXX"); printf '%s\n' "$BODY" > "$tmp"; chmod 0644 "$tmp"; mv -f "$tmp" "$F"
  [ "$(cat "$F")" = "$BODY" ] || fail "drop-in content differs"
else
  rm -f "$F"; rmdir "$D" 2>/dev/null || true
fi
$SYSTEMCTL daemon-reload || fail "daemon-reload"
case " $($SYSTEMCTL show -p DropInPaths --value cyberalertx-api) " in
  *stage-c-json-reads.conf*) [ "$MODE" = apply ] || fail "drop-in still loaded";;
  *) [ "$MODE" = revert ] || fail "drop-in not loaded";; esac
$SYSTEMCTL restart cyberalertx-api || fail "restart API"
ok=0; for i in $(seq "$WAIT"); do
  [ "$($CURL -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/healthz || true)" = 200 ] && { ok=1; break; }; sleep 1; done
[ "$ok" = 1 ] || fail "API not healthy after restart"
t=$($CURL -s -o /dev/null -w '%{time_total}' --max-time 15 'http://127.0.0.1:8000/posts?language=ua&limit=40&cached_only=1' || echo timeout)
trap - ERR
echo "----- $MODE COMPLETED: API healthy; UA 40-post feed answered in ${t}s -----"
