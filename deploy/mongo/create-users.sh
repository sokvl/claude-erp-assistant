#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${MONGO_ROOT_PASSWORD:?set MONGO_ROOT_PASSWORD in .env}"
: "${MONGO_APP_PASSWORD:?set MONGO_APP_PASSWORD in .env}"
: "${MONGO_TEST_PASSWORD:?set MONGO_TEST_PASSWORD in .env}"

read -r -d '' SCRIPT <<'JS' || true
const admin = db.getSiblingDB("admin");
const env = process.env;

let signedIn = false;
try {
  signedIn = admin.auth("root", env.MONGO_ROOT_PASSWORD).ok === 1;
} catch (error) {}
if (!signedIn) {
  admin.createUser({ user: "root", pwd: env.MONGO_ROOT_PASSWORD, roles: ["root"] });
  admin.auth("root", env.MONGO_ROOT_PASSWORD);
  print("created root");
}

function upsert(user, pwd, roles) {
  const action = admin.getUser(user) ? "updated" : "created";
  if (action === "updated") {
    admin.updateUser(user, { pwd, roles });
  } else {
    admin.createUser({ user, pwd, roles });
  }
  print(`${action} ${user}`);
}

upsert("invoices_app", env.MONGO_APP_PASSWORD, [{ role: "readWrite", db: "invoices_db" }]);
upsert("invoices_test", env.MONGO_TEST_PASSWORD, ["readWriteAnyDatabase", "dbAdminAnyDatabase"]);
JS

docker exec \
  -e MONGO_ROOT_PASSWORD -e MONGO_APP_PASSWORD -e MONGO_TEST_PASSWORD \
  "${MONGO_CONTAINER:-invoices_mongo}" mongosh --quiet --norc admin --eval "$SCRIPT"
