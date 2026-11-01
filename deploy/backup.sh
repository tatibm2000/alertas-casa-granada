#!/usr/bin/env bash
# Copia de seguridad diaria de la base de datos (segura aunque el monitor esté escribiendo).
# Se programa con cron: ver README, paso 9.
set -euo pipefail
APP_DIR="${APP_DIR:-/home/ubuntu/granada-monitor}"
DB="$APP_DIR/data/monitor.sqlite"
OUT="$APP_DIR/backups"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
sqlite3 "$DB" ".backup '$OUT/monitor-$STAMP.sqlite'"
gzip -f "$OUT/monitor-$STAMP.sqlite"
find "$OUT" -name 'monitor-*.sqlite.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup OK: $OUT/monitor-$STAMP.sqlite.gz"
