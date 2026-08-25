#!/usr/bin/env bash
set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install Helmfile." >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo "tar is required to install Helmfile." >&2
  exit 1
fi

version="${HELMFILE_VERSION:-v1.5.3}"
os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
machine_arch="$(uname -m)"
installed_version=""

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$1" | awk '{print $NF}'
  else
    echo "sha256sum, shasum, or openssl is required to verify Helmfile." >&2
    return 1
  fi
}

if command -v helmfile >/dev/null 2>&1; then
  installed_version="$(helmfile --version 2>/dev/null | awk '{print $NF}')"
  case "${installed_version}" in
    "${version}" | "${version#v}")
      helmfile --version
      exit 0
      ;;
  esac
  echo "Installed Helmfile version ${installed_version:-unknown} does not match requested ${version}; installing requested version."
fi

case "${machine_arch}" in
  x86_64 | amd64)
    arch="amd64"
    ;;
  aarch64 | arm64)
    arch="arm64"
    ;;
  *)
    echo "Unsupported Helmfile architecture: ${machine_arch}" >&2
    exit 1
    ;;
esac

case "${os_name}" in
  linux | darwin)
    ;;
  *)
    echo "Unsupported Helmfile OS: ${os_name}" >&2
    exit 1
    ;;
esac

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

archive="helmfile_${version#v}_${os_name}_${arch}.tar.gz"
url="https://github.com/helmfile/helmfile/releases/download/${version}/${archive}"
expected_sha256="${HELMFILE_ARCHIVE_SHA256:-}"

if [ -z "${expected_sha256}" ]; then
  case "${version}:${os_name}:${arch}" in
    v1.5.3:darwin:amd64) expected_sha256="c7bd24cd5fd25f9a2b656c67e8ede3526ff2ff524f708ea152e74f17a22a6214" ;;
    v1.5.3:darwin:arm64) expected_sha256="4cd54e6a8ccf69daf7a64ba073b1a7814d3084c5a0d8328a4c7f6f3693252553" ;;
    v1.5.3:linux:amd64) expected_sha256="1a93e6889737eba70339860ba5a71799cd71a95d0c29daf636c09c76b63cd660" ;;
    v1.5.3:linux:arm64) expected_sha256="05057e3ad11f651a5ed189b90193bc43c091cdd697e1bb5925f24babdb862ba7" ;;
  esac
fi
if ! printf '%s\n' "${expected_sha256}" | grep -Eq '^[A-Fa-f0-9]{64}$'; then
  echo "No trusted Helmfile checksum is pinned for ${version} ${os_name}/${arch}. Set HELMFILE_ARCHIVE_SHA256 to the checksum published by the Helmfile release." >&2
  exit 1
fi

curl --proto '=https' --tlsv1.2 --retry 3 -fsSL "${url}" -o "${tmp_dir}/${archive}"
actual_sha256="$(sha256_file "${tmp_dir}/${archive}")"
if [ "$(printf '%s' "${actual_sha256}" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "${expected_sha256}" | tr '[:upper:]' '[:lower:]')" ]; then
  echo "Helmfile archive checksum verification failed for ${archive}." >&2
  exit 1
fi
tar -xzf "${tmp_dir}/${archive}" -C "${tmp_dir}" helmfile

install_dir="${HELMFILE_INSTALL_DIR:-/usr/local/bin}"
if [ -w "${install_dir}" ]; then
  install -m 0755 "${tmp_dir}/helmfile" "${install_dir}/helmfile"
elif command -v sudo >/dev/null 2>&1; then
  sudo install -m 0755 "${tmp_dir}/helmfile" "${install_dir}/helmfile"
else
  install_dir="${HOME}/.local/bin"
  mkdir -p "${install_dir}"
  install -m 0755 "${tmp_dir}/helmfile" "${install_dir}/helmfile"
  case ":${PATH}:" in
    *":${install_dir}:"*) ;;
    *)
      echo "Installed Helmfile to ${install_dir}; add it to PATH before rerunning make." >&2
      exit 1
      ;;
  esac
fi

helmfile --version
