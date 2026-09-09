#!/usr/bin/env bash
set -euo pipefail
: "${TARGET_HOST:=107.151.245.166}"; [[ "$TARGET_HOST" == "107.151.245.166" ]] || { echo '拒绝：目标必须是 107.151.245.166' >&2; exit 2; }; : "${PACKAGE:?PACKAGE required}"; [[ "${DRY_RUN:-0}" == 1 ]] && { echo "DRY_RUN scp $PACKAGE root@$TARGET_HOST:/opt/mediaforge/releases/"; exit 0; }; scp "$PACKAGE" "root@$TARGET_HOST:/opt/mediaforge/releases/"
