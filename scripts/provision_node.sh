#!/usr/bin/env bash
# Flash one AutoSentry device with PlatformIO (SR-3 key injection at flash time).
#
#   scripts/provision_node.sh --env lilygo_t3s3 --addr 1 --key "<mesh-key>"   # an alarm node
#   scripts/provision_node.sh --env hub_gateway --gateway                      # the hub radio
#
# An alarm node is flashed with the shared mesh key and a UNIQUE address (--addr N, N>=1).
# The hub gateway is a dumb modem and needs no key. The mesh key is passed as a build flag and
# baked into flash, never written to disk in the repo. See docs/PRODUCTION_PROVISIONING.md.
set -euo pipefail

ENV=""; ADDR=""; KEY=""; GATEWAY=0
FW_DIR="$(cd "$(dirname "$0")/../firmware/alarm_node" && pwd)"
PROVISION_PY="$(dirname "$0")/provision.py"

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV="$2"; shift 2;;
    --addr) ADDR="$2"; shift 2;;
    --key) KEY="$2"; shift 2;;
    --gateway) GATEWAY=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

command -v pio >/dev/null 2>&1 || { echo "PlatformIO (pio) not found: pip install platformio" >&2; exit 1; }
[ -n "$ENV" ] || { echo "--env is required (e.g. lilygo_t3s3, heltec_v3, hub_gateway)" >&2; exit 2; }

if [ "$GATEWAY" -eq 1 ]; then
  echo ">> Flashing GATEWAY role on env=$ENV (no key/address needed)"
  ( cd "$FW_DIR" && pio run -e "$ENV" -t upload )
else
  [ -n "$ADDR" ] || { echo "--addr N (>=1) is required for a node" >&2; exit 2; }
  [ -n "$KEY" ]  || { echo "--key <mesh-key> is required for a node (SR-3)" >&2; exit 2; }
  # Build the -DNODE_ADDR / -DAUTOSENTRY_MESH_KEY flags via the provisioning helper so the
  # key is consistently validated + escaped for the C preprocessor.
  FLAGS="$(python3 "$PROVISION_PY" node-flags --key "$KEY" --addr "$ADDR")"
  echo ">> Flashing NODE addr=$ADDR on env=$ENV (key injected at flash, not stored)"
  ( cd "$FW_DIR" && PLATFORMIO_BUILD_FLAGS="$FLAGS" pio run -e "$ENV" -t upload )
fi

echo ">> Done. Monitor with: pio device monitor -d $FW_DIR"
