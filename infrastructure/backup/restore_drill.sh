#!/usr/bin/env bash
# Monthly restore drill: restore the newest dump into a scratch container and
# verify row counts. An untested backup is a rumor.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
LATEST="$(ls -t "${BACKUP_DIR}"/*.dump.gz 2>/dev/null | head -1)"
[ -n "${LATEST}" ] || { echo "no backups found in ${BACKUP_DIR}"; exit 1; }

echo "drilling restore of ${LATEST}"
gunzip -kf "${LATEST}"
DUMP="${LATEST%.gz}"

docker run -d --name tp-restore-drill -e POSTGRES_PASSWORD=drill \
  timescale/timescaledb:2.17.2-pg16 >/dev/null
trap 'docker rm -f tp-restore-drill >/dev/null' EXIT

until docker exec tp-restore-drill pg_isready -U postgres >/dev/null 2>&1; do sleep 2; done
sleep 3

docker exec tp-restore-drill psql -U postgres -c "CREATE DATABASE trading"
docker exec -i tp-restore-drill pg_restore -U postgres -d trading --no-owner < "${DUMP}"

echo "--- row counts ---"
docker exec tp-restore-drill psql -U postgres -d trading -t -c "
  SELECT 'instruments: '  || count(*) FROM instruments
  UNION ALL SELECT 'ticks: '        || count(*) FROM ticks
  UNION ALL SELECT 'option_chain: '|| count(*) FROM option_chain;"

rm -f "${DUMP}"
echo "restore drill PASSED"
