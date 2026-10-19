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
: "${MONGO_LAKE_PASSWORD:?set MONGO_LAKE_PASSWORD in .env}"

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

function upsertRole(role, privileges) {
  const action = admin.getRole(role) ? "updated" : "created";
  if (action === "updated") {
    admin.updateRole(role, { privileges, roles: [] });
  } else {
    admin.createRole({ role, privileges, roles: [] });
  }
  print(`${action} role ${role}`);
}

upsertRole("lakeInvoiceReader", [{ resource: { db: "invoices_db", collection: "invoices" }, actions: ["find"] }]);

upsert("invoices_app", env.MONGO_APP_PASSWORD, [{ role: "readWrite", db: "invoices_db" }]);
upsert("invoices_test", env.MONGO_TEST_PASSWORD, ["readWriteAnyDatabase", "dbAdminAnyDatabase"]);
upsert("lake_reader", env.MONGO_LAKE_PASSWORD, [{ role: "lakeInvoiceReader", db: "admin" }]);
JS

docker exec \
  -e MONGO_ROOT_PASSWORD -e MONGO_APP_PASSWORD -e MONGO_TEST_PASSWORD -e MONGO_LAKE_PASSWORD \
  "${MONGO_CONTAINER:-invoices_mongo}" mongosh --quiet --norc "mongodb://mongo1.localhost:27017,mongo2.localhost:27018,mongo3.localhost:27019/admin?replicaSet=rs0" --eval "$SCRIPT"
