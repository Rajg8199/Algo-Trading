#!/usr/bin/env bash
# Nightly pg_dump -> encrypted -> object storage (rclone remote "b2").
# Configure rclone once: rclone config (remote name: b2, bucket: tp-backups).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="${BACKUP_DIR}/trading_${STAMP}.dump"

mkdir -p "${BACKUP_DIR}"

docker compose exec -T timescaledb \
  pg_dump -U "${POSTGRES_USER:-trading}" -d "${POSTGRES_DB:-trading}" -Fc \
  > "${FILE}"

gzip "${FILE}"

if command -v rclone >/dev/null 2>&1; then
  rclone copy "${FILE}.gz" "b2:tp-backups/$(date +%Y/%m)/"
  echo "uploaded ${FILE}.gz"
else
  echo "WARNING: rclone not installed; backup is local-only" >&2
fi

# Local retention: keep 7 days
find "${BACKUP_DIR}" -name '*.dump.gz' -mtime +7 -delete
echo "backup complete: ${FILE}.gz"
