#!/usr/bin/env bash
# Install the AutoSentry hub on a fresh Jetson (automates docs/HARDWARE_SETUP.md §B).
# Idempotent: safe to re-run. Does NOT arm the system and does NOT write the mesh key — run
# `scripts/provision.py hub-env` for the key (SR-3) and arm only after `--selftest` passes.
#
#   sudo scripts/install_hub.sh                 # install to /opt/autosentry, enable the service
#   PREFIX=/opt/autosentry WITH_VOICE=1 sudo scripts/install_hub.sh
set -euo pipefail

PREFIX="${PREFIX:-/opt/autosentry}"
ETC="${ETC:-/etc/autosentry}"
SVC_USER="${SVC_USER:-autosentry}"
WITH_VOICE="${WITH_VOICE:-0}"            # 1 → install the [voice] extra (STT/TTS)
REPO_SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "== AutoSentry hub install =="
echo "   prefix=$PREFIX  etc=$ETC  user=$SVC_USER  voice=$WITH_VOICE"

# 1. System deps + Ollama (local VLM/LLM server). Ollama install is skipped if already present.
if command -v apt-get >/dev/null 2>&1; then
  apt-get update && apt-get -y install python3-venv python3-pip git
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo ">> installing Ollama (local model server)"
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama 2>/dev/null || true

# 2. Code into $PREFIX (copy from this checkout if not already there).
if [ "$REPO_SRC" != "$PREFIX" ]; then
  mkdir -p "$PREFIX"
  cp -r "$REPO_SRC/." "$PREFIX/"
fi

# 3. venv + package.
python3 -m venv "$PREFIX/hub/.venv"
EXTRA="."
[ "$WITH_VOICE" = "1" ] && EXTRA=".[voice]"
"$PREFIX/hub/.venv/bin/pip" install --upgrade pip
( cd "$PREFIX/hub" && .venv/bin/pip install -e "$EXTRA" )

# 4. Config (don't clobber an existing one).
mkdir -p "$ETC"
if [ ! -f "$ETC/config.yaml" ]; then
  cp "$PREFIX/hub/autosentry/config.yaml" "$ETC/config.yaml"
  echo ">> wrote $ETC/config.yaml — edit capture.sources/zones, comms.port, detection.weapon_model"
fi

# 5. Models (one-time fetch; idempotent; needs network — runs offline afterward).
echo ">> fetching local models (this can take a while)"
( cd "$PREFIX" && hub/.venv/bin/python scripts/download_models.py ) || \
  echo "!! model fetch incomplete — re-run scripts/download_models.py when online"

# 6. Service user + systemd unit (enabled, NOT started — start after keying + self-test).
id "$SVC_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin "$SVC_USER"
chown -R "$SVC_USER" "$PREFIX" "$ETC"
cp "$PREFIX/deploy/autosentry.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable autosentry

cat <<DONE

== Install complete. Next steps (docs/HARDWARE_SETUP.md §C–E) ==
  1. Mesh key:   $PREFIX/hub/.venv/bin/python $PREFIX/scripts/provision.py hub-env --key "\$KEY"
  2. Self-test:  $PREFIX/hub/.venv/bin/python -m autosentry.app --selftest --config $ETC/config.yaml
  3. Start:      sudo systemctl start autosentry   # only after self-test is READY
  4. Arm:        set armed: true (or arm per-zone from the dashboard) after on-site drills
DONE
