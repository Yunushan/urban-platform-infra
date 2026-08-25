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

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  else
    echo "sha256sum, shasum, or openssl is required to verify Helm." >&2
    return 1
  fi
}

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
expected_sha256="${HELM_ARCHIVE_SHA256:-}"

if [ -z "${expected_sha256}" ]; then
  case "${version}:${os_name}:${arch}" in
    v4.2.1:darwin:amd64) expected_sha256="2a21c9f368d608bcf6eb794ebc06514eb6b529a846b60fe4a43dea7bcce65228" ;;
    v4.2.1:darwin:arm64) expected_sha256="896472d2ec0740c60f64a9df0fc30d478beee38a1a2a6ed91aa6e6ee177c1575" ;;
    v4.2.1:linux:amd64) expected_sha256="479dca836e5b45e8bd222400c5591b0e3a647378f03ff96597180db97c17fdae" ;;
    v4.2.1:linux:arm64) expected_sha256="596b9a73d366c1e72ce67d595c22805480e30914593aafbc9f547694e72814db" ;;
    v4.2.1:linux:arm) expected_sha256="49e8f7856de6eab170dc09671cfb0578cc455d820df5b0f54e6453058dc0e3f3" ;;
  esac
fi
if ! printf '%s\n' "${expected_sha256}" | grep -Eq '^[A-Fa-f0-9]{64}$'; then
  echo "No trusted Helm checksum is pinned for ${version} ${os_name}/${arch}. Set HELM_ARCHIVE_SHA256 to the checksum published by the Helm release." >&2
  exit 1
fi

curl --proto '=https' --tlsv1.2 --retry 3 -fsSL "${url}" -o "${tmp_dir}/${archive}"
actual_sha256="$(sha256_file "${tmp_dir}/${archive}")"
if [ "$(printf '%s' "${actual_sha256}" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "${expected_sha256}" | tr '[:upper:]' '[:lower:]')" ]; then
  echo "Helm archive checksum verification failed for ${archive}." >&2
  exit 1
fi
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
