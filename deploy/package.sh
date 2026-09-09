#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
version=$(python3 -c 'import mediaforge;print(mediaforge.__version__)')
commit=$(git rev-parse HEAD)
ts=$(date -u +%Y%m%dT%H%M%SZ)
out="dist/mediaforge-${version}-${ts}.tar.gz"
tar --exclude='.env' --exclude='.venv' --exclude='var' --exclude='dist' --exclude='.git' --exclude='__pycache__' -czf "$out" .
sha=$(shasum -a 256 "$out" | awk '{print $1}')
printf '{"project_id":"local.mediaforge","version":"%s","git_commit":"%s","artifact_sha256":"%s","built_at":"%s"}\n' "$version" "$commit" "$sha" "$ts" > "$out.release.json"
printf '%s  %s\n' "$sha" "$(basename "$out")" > "$out.sha256"
echo "$out"
