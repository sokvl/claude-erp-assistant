#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

SECONDS_TOTAL=30
ISOLATE_AT=3
HEAL_AT=20
LOGS="${CAP_LOGS:-/tmp/cap_lab}"

set -a
. ./.env
set +a
: "${MONGO_ROOT_PASSWORD:?}" "${MONGO_TEST_PASSWORD:?}" "${MONGO_TEST_URI:?}"

root_eval() {
  docker exec -e MONGO_ROOT_PASSWORD invoices_mongo2 mongosh --quiet --norc \
    "mongodb://mongo1.localhost:27017,mongo2.localhost:27018,mongo3.localhost:27019/admin?replicaSet=rs0" \
    --eval "db.auth('root', process.env.MONGO_ROOT_PASSWORD); $1"
}

healthy=$(root_eval 'print(rs.status().members.filter(m => m.health === 1).length)')
[ "$healthy" = 3 ] || { echo "only $healthy of 3 nodes are healthy, heal them first" >&2; exit 1; }
primary=$(root_eval 'print(db.hello().primary)')
node="${primary%%.*}"
port="${primary##*:}"
container=$([ "$node" = mongo1 ] && echo invoices_mongo || echo "invoices_$node")
run="clients_$(openssl rand -hex 4)"
mkdir -p "$LOGS"
echo "primary is $node ($container), run $run; isolate at ${ISOLATE_AT}s, heal at ${HEAL_AT}s"

trap 'scripts/cap/partition.sh heal "$node" >/dev/null 2>&1 || true' EXIT

./venv/bin/python scripts/cap/cap_lab.py write --run "${run}_c" --w majority --seconds "$SECONDS_TOTAL" \
  --out "$LOGS/${run}_c.json" 2>&1 | grep -v RuntimeWarning &
app_client=$!

docker run --rm --name cap_diverge --network "container:$container" \
  -v "$PWD/scripts/cap:/lab:ro,z" -e MONGO_TEST_PASSWORD \
  --entrypoint sh claude-app:latest -c \
  "python /lab/cap_lab.py --uri \"mongodb://invoices_test:\$MONGO_TEST_PASSWORD@localhost:$port/?authSource=admin&directConnection=true\" \
   diverge --run ${run}_d --diverge-at $((ISOLATE_AT + 1)) --recheck-at $((ISOLATE_AT + 12))" &
diverger=$!

sleep "$ISOLATE_AT"
scripts/cap/partition.sh isolate "$node"
sleep $((HEAL_AT - ISOLATE_AT))
scripts/cap/partition.sh heal "$node"
wait "$diverger" "$app_client"

for _ in $(seq 120); do
  state=$(root_eval "print(rs.status().members.find(m => m.name === '$primary').stateStr)")
  [ "$state" = SECONDARY ] || [ "$state" = PRIMARY ] && break
  sleep 1
done
echo "old primary $node is now $state, new primary $(root_eval 'print(db.hello().primary)')"
echo "D after heal, the whole set with majority reads sees $(root_eval "print(db.getSiblingDB('cap_lab_${run}_d').orders.countDocuments({}))") orders"

echo "C, client connected to the whole set:"
python3 - "$LOGS/${run}_c.json" <<'PY'
import json, sys
log = json.load(open(sys.argv[1]))["log"]
acked = [e["at"] for e in log if e["outcome"] == "acked"]
gap, start = max((later - earlier, earlier) for earlier, later in zip(acked, acked[1:]))
errors = sorted({e["outcome"] for e in log if e["outcome"] != "acked"})
print(f"  longest stretch without an acknowledged write: {gap:.1f}s (from {start:.1f}s), errors {errors or '-'}")
PY

uuids=$(root_eval "['${run}_c', '${run}_d'].forEach(r => { const i = db.getSiblingDB('cap_lab_' + r).getCollectionInfos({name: 'orders'})[0]; if (i) print(i.info.uuid.toUUID().toHexString()); })")
./venv/bin/python scripts/cap/cap_lab.py check --log "$LOGS/${run}_c.json" 2>&1 | grep -v RuntimeWarning | sed 's/^/  /'
root_eval "db.getSiblingDB('cap_lab_${run}_d').dropDatabase(); print('dropped cap_lab_${run}_d')"

echo "rollback files on $node:"
for uuid in $uuids; do
  docker exec "$container" sh -c "
    dir=/data/db/rollback/$uuid
    [ -d \"\$dir\" ] || exit 0
    for f in \"\$dir\"/*.bson; do echo \"  $uuid/\$(basename \"\$f\"): \$(bsondump --quiet \"\$f\" | wc -l) orders\"; done
    rm -rf \"\$dir\""
done
