#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${MONGO_ROOT_PASSWORD:?set MONGO_ROOT_PASSWORD in .env}"

read -r -d '' SCRIPT <<'JS' || true
const members = [{ _id: 0, host: "mongo1.localhost:27017" }];

db.getSiblingDB("admin").auth("root", process.env.MONGO_ROOT_PASSWORD);

try {
  rs.status();
  print("replica set rs0 already initiated");
} catch (error) {
  if (error.codeName !== "NotYetInitialized") throw error;
  rs.initiate({ _id: "rs0", members });
  print("initiated replica set rs0");
}

for (let attempt = 0; !db.hello().isWritablePrimary; attempt++) {
  if (attempt === 60) throw new Error("no primary after 60 s");
  sleep(1000);
}
print(`primary: ${db.hello().primary}`);
JS

CONTAINER="${MONGO_CONTAINER:-invoices_mongo}"
for attempt in $(seq 30); do
  docker exec "$CONTAINER" mongosh --quiet --norc --eval "db.adminCommand({ ping: 1 })" >/dev/null 2>&1 && break
  [ "$attempt" -eq 30 ] && { echo "mongod in $CONTAINER is not answering" >&2; exit 1; }
  sleep 1
done

docker exec -e MONGO_ROOT_PASSWORD "$CONTAINER" mongosh --quiet --norc admin --eval "$SCRIPT"
