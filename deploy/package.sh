#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."; mkdir -p dist; v=$(python3 -c 'import mediaforge;print(mediaforge.__version__)'); ts=$(date -u +%Y%m%dT%H%M%SZ); out="dist/mediaforge-${v}-${ts}.tar.gz"; tar --exclude='.env' --exclude='.venv' --exclude='var' --exclude='dist' --exclude='.git' -czf "$out" .; shasum -a 256 "$out" > "$out.sha256"; echo "$out"
