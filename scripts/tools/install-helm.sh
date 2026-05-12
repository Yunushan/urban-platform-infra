#!/usr/bin/env bash
set -euo pipefail

if command -v helm >/dev/null 2>&1; then
  helm version --short
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install Helm." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \
  -o "${tmp_dir}/get-helm-3"
chmod 0700 "${tmp_dir}/get-helm-3"
"${tmp_dir}/get-helm-3"

helm version --short
