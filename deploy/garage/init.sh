#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

CONTAINER="${GARAGE_CONTAINER:-invoices_garage}"
CAPACITY="${GARAGE_CAPACITY:-20G}"
BUCKETS=(lake-bronze lake-silver lake-gold)

garage() { docker exec "$CONTAINER" /garage "$@" 2>/dev/null; }

ensure_env_key() {
  local id_var="$1" secret_var="$2"
  if ! grep -q "^$id_var=" .env; then
    printf '%s=GK%s\n%s=%s\n' "$id_var" "$(openssl rand -hex 12)" "$secret_var" "$(openssl rand -hex 32)" >> .env
    echo "generated $id_var and $secret_var into .env"
  fi
}

ensure_env_key LAKE_WRITER_KEY_ID LAKE_WRITER_SECRET
ensure_env_key LAKE_READER_KEY_ID LAKE_READER_SECRET
set -a
. ./.env
set +a

version=$(garage layout show | sed -n 's/^Current cluster layout version: //p')
if [ "$version" = 0 ]; then
  node=$(garage node id -q | cut -d@ -f1)
  garage layout assign -z dc1 -c "$CAPACITY" "$node" >/dev/null
  garage layout apply --version 1 >/dev/null
  echo "assigned $CAPACITY to node ${node:0:16} (layout version 1)"
else
  echo "layout already at version $version"
fi

for bucket in "${BUCKETS[@]}"; do
  if garage bucket info "$bucket" >/dev/null; then
    echo "bucket $bucket exists"
  else
    garage bucket create "$bucket" >/dev/null
    echo "created bucket $bucket"
  fi
done

import_key() {
  local name="$1" id="$2" secret="$3"
  if garage key info "$id" >/dev/null; then
    echo "key $name exists"
  else
    garage key import --yes -n "$name" "$id" "$secret" >/dev/null
    echo "imported key $name"
  fi
}

import_key lake-writer "$LAKE_WRITER_KEY_ID" "$LAKE_WRITER_SECRET"
import_key analyst-reader "$LAKE_READER_KEY_ID" "$LAKE_READER_SECRET"

for bucket in "${BUCKETS[@]}"; do
  garage bucket allow --read --write --owner "$bucket" --key "$LAKE_WRITER_KEY_ID" >/dev/null
  if [ "$bucket" = lake-gold ]; then
    garage bucket allow --read "$bucket" --key "$LAKE_READER_KEY_ID" >/dev/null
    garage bucket deny --write --owner "$bucket" --key "$LAKE_READER_KEY_ID" >/dev/null
  else
    garage bucket deny --read --write --owner "$bucket" --key "$LAKE_READER_KEY_ID" >/dev/null
  fi
done
echo "permissions: lake-writer reads and writes every bucket, analyst-reader only reads lake-gold"
