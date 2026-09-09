#!/usr/bin/env bash
set -euo pipefail
TARGET_HOST="${TARGET_HOST:-107.151.245.166}"; [[ "$TARGET_HOST" == "107.151.245.166" ]] || exit 2
KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/chimera-lab_root_ed25519}"
ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes "root@$TARGET_HOST" 'set -e; base=/opt/mediaforge; prev=$(find "$base/releases" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 2 | head -n 1); test -n "$prev"; kill $(cat "$base/server.pid") 2>/dev/null || true; ln -sfn "$prev" "$base/current"; cd "$base/current"; nohup env MEDIAFORGE_PORT=18081 MEDIAFORGE_DATA="$base/data" PYTHONPATH=. python3 -m mediaforge.server >"$base/service.log" 2>&1 </dev/null & echo $! > "$base/server.pid"; sleep 1; curl -fsS http://127.0.0.1:18081/healthz'
