#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY in the environment or .env}"
OUT=deploy/vault

vault() {
  docker compose exec -T -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="${VAULT_DEV_ROOT_TOKEN:-dev-root-token}" \
    vault vault "$@"
}

vault secrets enable transit >/dev/null 2>&1 || true
vault write -f transit/keys/app-jwt type=ed25519 >/dev/null

printf '%s' "$ANTHROPIC_API_KEY" | vault kv put secret/invoices-app \
  ANTHROPIC_API_KEY=- MONGO_URI="${APP_MONGO_URI:-mongodb://mongo:27017}" >/dev/null

vault policy write invoices-app - >/dev/null <<'POLICY'
path "secret/data/invoices-app" { capabilities = ["read"] }
path "transit/keys/app-jwt" { capabilities = ["read"] }
path "transit/sign/app-jwt" { capabilities = ["update"] }
POLICY

vault auth enable approle >/dev/null 2>&1 || true
vault write auth/approle/role/invoices-app \
  token_policies=invoices-app token_ttl=1h token_max_ttl=24h secret_id_ttl=0 >/dev/null

umask 077
vault read -field=role_id auth/approle/role/invoices-app/role-id > "$OUT/role_id"
vault write -f -field=secret_id auth/approle/role/invoices-app/secret-id > "$OUT/secret_id"

echo "Vault ready: transit key app-jwt, secret/invoices-app, AppRole invoices-app"
echo "Wrote $OUT/role_id and $OUT/secret_id; start the app with: docker compose up -d app"
