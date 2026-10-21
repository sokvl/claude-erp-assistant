#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${MONGO_ROOT_PASSWORD:?set MONGO_ROOT_PASSWORD in .env}"

CONTAINER="${MONGO_CONTAINER:-invoices_mongo}"
KEEP="${BACKUP_KEEP:-7}"
DIR="backups"
FILE="$DIR/auto-$(date -u +%Y%m%d-%H%M).archive.gz"
CONFIG="/tmp/backup-$$.yaml"
URI="mongodb://mongo1.localhost:27017,mongo2.localhost:27018,mongo3.localhost:27019/?replicaSet=rs0"

umask 077
mkdir -p "$DIR"
trap 'docker exec "$CONTAINER" rm -f "$CONFIG" >/dev/null 2>&1 || true' EXIT

printf 'password: "%s"\n' "$MONGO_ROOT_PASSWORD" | docker exec -i "$CONTAINER" sh -c "umask 077 && cat > $CONFIG"

started=$(date +%s)
docker exec "$CONTAINER" mongodump --quiet --config "$CONFIG" --uri "$URI" \
  --username root --authenticationDatabase admin \
  --readPreference secondary --oplog --archive --gzip > "$FILE.partial"
gzip -t "$FILE.partial"
mv "$FILE.partial" "$FILE"
echo "wrote $FILE ($(du -h "$FILE" | cut -f1), $(( $(date +%s) - started )) s)"

ls -1t "$DIR"/auto-*.archive.gz | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
  echo "removed $old"
done
