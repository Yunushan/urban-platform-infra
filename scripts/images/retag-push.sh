#!/usr/bin/env bash
set -euo pipefail
: "${REGISTRY_PREFIX:?Set REGISTRY_PREFIX from a private environment value, for example registry.example.invalid/platform}"

while read -r image; do
  [ -z "$image" ] && continue
  target="${REGISTRY_PREFIX}/${image}"
  echo "Tagging ${image} -> ${target}"
  docker pull "$image" || true
  docker tag "$image" "$target"
  docker push "$target"
done < <(python3 scripts/images/list-images.py)
