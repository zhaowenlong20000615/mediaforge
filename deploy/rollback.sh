#!/usr/bin/env bash
set -euo pipefail
: "${TARGET_HOST:=107.151.245.166}"; [[ "$TARGET_HOST" == "107.151.245.166" ]] || exit 2; echo "rollback on $TARGET_HOST requires release operator"
