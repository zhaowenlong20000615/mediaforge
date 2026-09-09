#!/usr/bin/env bash
set -euo pipefail
: "${TARGET_HOST:=107.151.245.166}"; [[ "$TARGET_HOST" == "107.151.245.166" ]] || exit 2; echo "status target=$TARGET_HOST project=mediaforge"
