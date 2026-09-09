#!/usr/bin/env bash
set -euo pipefail
TARGET_HOST="${TARGET_HOST:-107.151.245.166}"
[[ "$TARGET_HOST" == "107.151.245.166" ]] || { echo '拒绝：目标必须是 107.151.245.166' >&2; exit 2; }
KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/chimera-lab_root_ed25519}"
PACKAGE="${PACKAGE:?PACKAGE required}"
meta="$PACKAGE.release.json"; [[ -f "$meta" ]] || { echo "缺少 $meta" >&2; exit 2; }
version=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$meta")
commit=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["git_commit"])' "$meta")
remote="/tmp/$(basename "$PACKAGE")"
ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes "root@$TARGET_HOST" "set -e; base=/opt/mediaforge; mkdir -p \"\$base/releases/$version-$commit\" \"\$base/data\"; tar -xzf \"$remote\" -C \"\$base/releases/$version-$commit\"; cp /tmp/$(basename "$meta") \"\$base/releases/$version-$commit/release.json\"; if [ -f \"\$base/server.pid\" ]; then kill \$(cat \"\$base/server.pid\") 2>/dev/null || true; fi; ln -sfn \"\$base/releases/$version-$commit\" \"\$base/current\"; cd \"\$base/current\"; nohup env MEDIAFORGE_PORT=18081 MEDIAFORGE_DATA=\"\$base/data\" PYTHONPATH=. python3 -m mediaforge.server >\"\$base/service.log\" 2>&1 </dev/null & echo \$! > \"\$base/server.pid\"; sleep 1; curl -fsS http://127.0.0.1:18081/healthz; curl -fsS http://127.0.0.1:18081/readyz; curl -fsS http://127.0.0.1:18081/version"
echo "activated $version-$commit on $TARGET_HOST"
