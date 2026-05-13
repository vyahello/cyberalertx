#!/usr/bin/env bash
# Daily backup of the JSON state under data/.
#
# Run by cron: see /etc/cron.d/cax-backup (created by setup.sh).
# Or manually: sudo -u cax /usr/local/bin/cax-backup
#
# Strategy:
#   - tar.gz of /home/cax/cax/data/ → ~/backups/data-YYYYMMDD.tar.gz
#   - Rotate: keep last 14 days; older snapshots are deleted.
#   - Off-site (S3 / Backblaze) — out of scope; bolt on if needed.
#
# Note: this backs up the JSON authoritative store. PG is a SEPARATE
# story (Supabase has its own daily snapshots in their UI).

set -euo pipefail

APP_USER="${APP_USER:-cax}"
APP_DIR="${APP_DIR:-/home/${APP_USER}/cax}"
BACKUP_DIR="/home/${APP_USER}/backups"
RETAIN_DAYS=14

mkdir -p "${BACKUP_DIR}"

DATE="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="${BACKUP_DIR}/data-${DATE}.tar.gz"

tar -czf "${ARCHIVE}" -C "${APP_DIR}" data/

# Rotate
find "${BACKUP_DIR}" -name 'data-*.tar.gz' -mtime "+${RETAIN_DAYS}" -delete

echo "✓ Backup ${ARCHIVE} ($(du -h "${ARCHIVE}" | cut -f1))"
