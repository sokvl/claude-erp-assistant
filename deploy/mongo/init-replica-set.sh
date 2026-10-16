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
const hosts = ["mongo1.localhost:27017", "mongo2.localhost:27018", "mongo3.localhost:27019"];
const password = process.env.MONGO_ROOT_PASSWORD;

db.getSiblingDB("admin").auth("root", password);

try {
  rs.status();
  print("replica set rs0 already initiated");
} catch (error) {
  if (error.codeName !== "NotYetInitialized") throw error;
  rs.initiate({ _id: "rs0", members: [{ _id: 0, host: hosts[0] }] });
  print("initiated replica set rs0");
}

function waitFor(condition, what, seconds) {
  for (let elapsed = 0; !condition(); elapsed++) {
    if (elapsed === seconds) throw new Error(`gave up waiting for ${what} after ${seconds} s`);
    if (elapsed > 0 && elapsed % 30 === 0) print(`  still waiting for ${what} (${elapsed} s)`);
    sleep(1000);
  }
}

waitFor(() => db.hello().primary !== undefined, "a primary", 60);
if (!db.hello().isWritablePrimary) {
  db = connect(`mongodb://root:${encodeURIComponent(password)}@${db.hello().primary}/admin`);
}

const configSettled = () => {
  const reply = db.adminCommand({ replSetGetConfig: 1, commitmentStatus: true });
  return reply.commitmentStatus && !reply.config.members.some((member) => member.newlyAdded);
};

for (const host of hosts) {
  waitFor(configSettled, "the previous configuration change to commit", 120);
  if (!rs.conf().members.some((member) => member.host === host)) {
    rs.add(host);
    print(`added ${host}`);
  }
  const state = () => rs.status().members.find((member) => member.name === host)?.stateStr;
  waitFor(() => ["PRIMARY", "SECONDARY"].includes(state()), `${host} to catch up`, 1800);
}

rs.status().members.forEach((member) => print(`${member.name} ${member.stateStr}`));
JS

CONTAINER="${MONGO_CONTAINER:-invoices_mongo}"
for attempt in $(seq 30); do
  docker exec "$CONTAINER" mongosh --quiet --norc --eval "db.adminCommand({ ping: 1 })" >/dev/null 2>&1 && break
  [ "$attempt" -eq 30 ] && { echo "mongod in $CONTAINER is not answering" >&2; exit 1; }
  sleep 1
done

docker exec -e MONGO_ROOT_PASSWORD "$CONTAINER" mongosh --quiet --norc admin --eval "$SCRIPT"
