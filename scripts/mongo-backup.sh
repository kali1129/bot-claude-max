#!/bin/bash
# Daily MongoDB backup with 30-day retention. Installed at:
#   /usr/local/bin/mongo-backup.sh
# Cron:  0 3 * * * root /usr/local/bin/mongo-backup.sh >> /var/log/mongo-backup.log 2>&1
set -euo pipefail
BACKUP_DIR="/opt/trading-bot/backups/mongo"
RETENTION_DAYS=30
DATE=$(date -u +%Y-%m-%d_%H-%M)
mkdir -p "$BACKUP_DIR"
TMP=$(mktemp -d)
docker exec mongodb mongodump --quiet --archive 2>/dev/null > "$TMP/dump.archive"
SIZE=$(stat -c%s "$TMP/dump.archive")
if [ "$SIZE" -lt 100 ]; then
  echo "[backup] FAIL: dump size $SIZE bytes -- too small"
  rm -rf "$TMP"; exit 1
fi
gzip "$TMP/dump.archive"
mv "$TMP/dump.archive.gz" "$BACKUP_DIR/$DATE.archive.gz"
rm -rf "$TMP"
find "$BACKUP_DIR" -name "*.archive.gz" -mtime +$RETENTION_DAYS -delete
echo "[backup] OK $DATE -- $(du -h $BACKUP_DIR/$DATE.archive.gz | cut -f1)"
