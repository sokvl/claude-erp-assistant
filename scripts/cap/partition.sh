#!/usr/bin/env bash
set -euo pipefail

NETWORK="${COMPOSE_NETWORK:-claude_default}"

usage() {
  echo "usage: $0 isolate|heal mongo1|mongo2|mongo3" >&2
  exit 2
}

[ $# -eq 2 ] || usage
action="$1"
node="$2"
case "$node" in
  mongo1) container=invoices_mongo ;;
  mongo2 | mongo3) container="invoices_$node" ;;
  *) usage ;;
esac

case "$action" in
  isolate) docker network disconnect "$NETWORK" "$container" ;;
  heal) docker network connect --alias "$node" --alias "$node.localhost" "$NETWORK" "$container" ;;
  *) usage ;;
esac
echo "$action $node ($container)"
