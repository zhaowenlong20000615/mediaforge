#!/usr/bin/env bash
set -euo pipefail
TARGET_HOST="${TARGET_HOST:-107.151.245.166}"
[[ "$TARGET_HOST" == "107.151.245.166" ]] || { echo '拒绝：目标必须是 107.151.245.166' >&2; exit 2; }
KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/chimera-lab_root_ed25519}"
PACKAGE="${PACKAGE:?PACKAGE required}"
for f in "$PACKAGE" "$PACKAGE.sha256" "$PACKAGE.release.json"; do [[ -f "$f" ]] || { echo "缺少 $f" >&2; exit 2; }; done
if [[ "${DRY_RUN:-0}" == 1 ]]; then echo "DRY_RUN scp $PACKAGE* root@$TARGET_HOST:/tmp/"; exit 0; fi
scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes "$PACKAGE" "$PACKAGE.sha256" "$PACKAGE.release.json" "root@$TARGET_HOST:/tmp/"
echo "uploaded $PACKAGE to $TARGET_HOST"
