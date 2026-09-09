#!/usr/bin/env bash
set -euo pipefail
TARGET_HOST="${TARGET_HOST:-107.151.245.166}"; [[ "$TARGET_HOST" == "107.151.245.166" ]] || exit 2
KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/chimera-lab_root_ed25519}"
ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes "root@$TARGET_HOST" 'cat /opt/mediaforge/current/release.json 2>/dev/null || true; curl -fsS http://127.0.0.1:18081/healthz; echo; curl -fsS http://127.0.0.1:18081/readyz; echo; curl -fsS http://127.0.0.1:18081/version'
