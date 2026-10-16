#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

W="${1:?usage: $0 1|majority}"
SECONDS_TOTAL=30
ISOLATE_AT=5
HEAL_AT=20
LOGS="${CAP_LOGS:-/tmp/cap_lab}"

set -a
. ./.env
set +a
: "${MONGO_ROOT_PASSWORD:?}" "${MONGO_TEST_PASSWORD:?}"

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
run="split_$(openssl rand -hex 4)_w$W"
mkdir -p "$LOGS"
echo "primary is $node ($container), run $run, w=$W"

trap 'scripts/cap/partition.sh heal "$node" >/dev/null 2>&1 || true' EXIT

docker run --rm --name cap_probe --network "container:$container" \
  -v "$PWD/scripts/cap:/lab:ro,z" -v "$LOGS:/logs:z" -e MONGO_TEST_PASSWORD \
  --entrypoint sh claude-app:latest -c \
  "python /lab/cap_lab.py --uri \"mongodb://invoices_test:\$MONGO_TEST_PASSWORD@localhost:$port/?authSource=admin&directConnection=true\" \
   write --run $run --w $W --seconds $SECONDS_TOTAL --out /logs/$run.json" &
probe=$!

sleep "$ISOLATE_AT"
scripts/cap/partition.sh isolate "$node"
sleep $((HEAL_AT - ISOLATE_AT))
scripts/cap/partition.sh heal "$node"
wait "$probe"

for _ in $(seq 120); do
  state=$(root_eval "print(rs.status().members.find(m => m.name === '$primary').stateStr)")
  [ "$state" = SECONDARY ] || [ "$state" = PRIMARY ] && break
  sleep 1
done
echo "old primary $node is now $state, new primary $(root_eval 'print(db.hello().primary)')"

python3 - "$LOGS/$run.json" "$ISOLATE_AT" "$HEAL_AT" <<'PY'
import json, sys
log = json.load(open(sys.argv[1]))["log"]
isolate, heal = float(sys.argv[2]), float(sys.argv[3])
phases = {"before isolate": (0, isolate), "isolated": (isolate, heal), "after heal": (heal, 1e9)}
for name, (start, end) in phases.items():
    entries = [e for e in log if start <= e["at"] < end]
    acked = [e for e in entries if e["outcome"] == "acked"]
    last = f", last acked at {acked[-1]['at']:.1f}s" if acked else ""
    errors = sorted({e["outcome"] for e in entries if e["outcome"] != "acked"})
    print(f"  {name:<15} attempted {len(entries):>3}  acked {len(acked):>3}{last}  errors {errors or '-'}")
PY

uuid=$(root_eval "const info = db.getSiblingDB('cap_lab_$run').getCollectionInfos({name: 'orders'})[0]; print(info ? info.info.uuid.toUUID().toHexString() : '')")

./venv/bin/python scripts/cap/cap_lab.py check --log "$LOGS/$run.json" 2>&1 | grep -v RuntimeWarning

echo "rollback files on $node:"
docker exec "$container" sh -c "
  dir=/data/db/rollback/$uuid
  [ -n '$uuid' ] && [ -d \"\$dir\" ] || { echo '  none'; exit 0; }
  for f in \"\$dir\"/*.bson; do echo \"  \$(basename \"\$f\"): \$(bsondump --quiet \"\$f\" | wc -l) orders\"; done
  rm -rf \"\$dir\""
