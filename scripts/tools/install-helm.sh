#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install Helm." >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo "tar is required to install Helm." >&2
  exit 1
fi

version="${HELM_VERSION:-v4.2.1}"
install_dir="${HELM_INSTALL_DIR:-/usr/local/bin}"
os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
machine_arch="$(uname -m)"

installed_version=""
if command -v helm >/dev/null 2>&1; then
  installed_version="$(helm version --template '{{.Version}}' 2>/dev/null || helm version --short 2>/dev/null | awk '{print $1}')"
  if [ "${installed_version}" = "${version}" ]; then
    helm version --short
    exit 0
  fi
  echo "Installed Helm version ${installed_version:-unknown} does not match requested ${version}; installing requested version."
fi

case "${machine_arch}" in
  x86_64 | amd64)
    arch="amd64"
    ;;
  aarch64 | arm64)
    arch="arm64"
    ;;
  armv7l | armv6l)
    arch="arm"
    ;;
  *)
    echo "Unsupported Helm architecture: ${machine_arch}" >&2
    exit 1
    ;;
esac

case "${os_name}" in
  linux | darwin)
    ;;
  *)
    echo "Unsupported Helm OS: ${os_name}" >&2
    exit 1
    ;;
esac

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

archive="helm-${version}-${os_name}-${arch}.tar.gz"
url="https://get.helm.sh/${archive}"

curl -fsSL "${url}" -o "${tmp_dir}/${archive}"
tar -xzf "${tmp_dir}/${archive}" -C "${tmp_dir}"

if [ -w "${install_dir}" ]; then
  install -m 0755 "${tmp_dir}/${os_name}-${arch}/helm" "${install_dir}/helm"
elif command -v sudo >/dev/null 2>&1; then
  sudo install -m 0755 "${tmp_dir}/${os_name}-${arch}/helm" "${install_dir}/helm"
else
  install_dir="${HOME}/.local/bin"
  mkdir -p "${install_dir}"
  install -m 0755 "${tmp_dir}/${os_name}-${arch}/helm" "${install_dir}/helm"
  case ":${PATH}:" in
    *":${install_dir}:"*) ;;
    *)
      echo "Installed Helm to ${install_dir}; add it to PATH before rerunning make." >&2
      exit 1
      ;;
  esac
fi

helm version --short
