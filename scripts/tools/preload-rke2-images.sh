#!/usr/bin/env bash
set -euo pipefail

images_text="${RKE2_PRELOAD_IMAGES:-}"
if [ "$#" -gt 0 ]; then
  images_text="$*"
fi

if [ -z "${images_text//[[:space:],]/}" ]; then
  echo "No RKE2 preload images requested."
  exit 0
fi

container_tool="${MIGRATION_CONTAINER_TOOL:-auto}"
archive_dir="${MIGRATION_IMAGE_OUTPUT_DIR:-${MIGRATION_PRIVATE_DIR:-/var/lib/urban-platform/private}/images}"
rke2_image_dir="${MIGRATION_RKE2_IMAGE_DIR:-/var/lib/rancher/rke2/agent/images}"
fallback_inventory_path="${FALLBACK_INVENTORY_PATH:-${MIGRATION_FALLBACK_INVENTORY:-/tmp/urban-platform-import-inventory.yml}}"
required="${RKE2_PRELOAD_REQUIRED:-false}"
reuse_archives="${RKE2_PRELOAD_REUSE_ARCHIVES:-true}"
cleanup_archives="${RKE2_PRELOAD_CLEANUP_ARCHIVES:-false}"

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

ssh_options_for_node() {
  printf '%s\n' "-o"
  printf '%s\n' "BatchMode=yes"
  printf '%s\n' "-o"
  printf '%s\n' "ConnectTimeout=${MIGRATION_SSH_CONNECT_TIMEOUT:-10}"
  printf '%s\n' "-o"
  printf '%s\n' "ServerAliveInterval=${MIGRATION_SSH_SERVER_ALIVE_INTERVAL:-5}"
  printf '%s\n' "-o"
  printf '%s\n' "ServerAliveCountMax=${MIGRATION_SSH_SERVER_ALIVE_COUNT_MAX:-2}"
  printf '%s\n' "-o"
  printf '%s\n' "StrictHostKeyChecking=${MIGRATION_SSH_STRICT_HOST_KEY_CHECKING:-accept-new}"
  if [ -n "${MIGRATION_SSH_KEY:-}" ]; then
    printf '%s\n' "-i"
    printf '%s\n' "${MIGRATION_SSH_KEY}"
  fi
}

recover_migration_context() {
  local discovered_rke2_nodes
  local recovered_ssh_user
  local recovered_ssh_key

  if [ -z "${MIGRATION_RKE2_NODES:-}" ] && [ -r "${fallback_inventory_path}" ]; then
    discovered_rke2_nodes="$(
      sed -nE "s/^[[:space:]]*ansible_host:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
        | paste -sd, -
    )"
    if [ -n "${discovered_rke2_nodes}" ]; then
      export MIGRATION_RKE2_NODES="${discovered_rke2_nodes}"
      echo "Recovered MIGRATION_RKE2_NODES from ${fallback_inventory_path}."
    fi
  fi

  if [ "${MIGRATION_RECOVER_INVENTORY_SSH_CONTEXT:-true}" = "true" ] && [ -r "${fallback_inventory_path}" ]; then
    recovered_ssh_user="$(
      sed -nE "s/^[[:space:]]*ansible_user:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
        | head -n 1
    )"
    if [ -n "${recovered_ssh_user}" ] && { [ -z "${MIGRATION_SSH_USER:-}" ] || [ "${MIGRATION_SSH_USER:-}" = "root" ]; }; then
      export MIGRATION_SSH_USER="${recovered_ssh_user}"
      echo "Recovered MIGRATION_SSH_USER from ${fallback_inventory_path}: ${MIGRATION_SSH_USER}."
    fi

    if [ -z "${MIGRATION_SSH_KEY:-}" ]; then
      recovered_ssh_key="$(
        sed -nE "s/^[[:space:]]*ansible_ssh_private_key_file:[[:space:]]*['\"]?([^'\"]+)['\"]?[[:space:]]*$/\1/p" "${fallback_inventory_path}" \
          | head -n 1
      )"
      if [ -z "${recovered_ssh_key}" ]; then
        for recovered_ssh_key in \
          "${HOME}/.ssh/id_ed25519_urban_ansible" \
          "${HOME}/.ssh/id_rsa_urban_ansible" \
          "${HOME}/.ssh/id_ed25519"; do
          if [ -r "${recovered_ssh_key}" ]; then
            break
          fi
          recovered_ssh_key=""
        done
      fi
      if [ -n "${recovered_ssh_key}" ] && [ -r "${recovered_ssh_key}" ]; then
        export MIGRATION_SSH_KEY="${recovered_ssh_key}"
        echo "Recovered MIGRATION_SSH_KEY from local SSH identity: ${MIGRATION_SSH_KEY}."
      fi
    fi
  fi
}

discover_nodes() {
  if [ -n "${MIGRATION_RKE2_NODES:-}" ]; then
    printf '%s\n' "${MIGRATION_RKE2_NODES}" | tr ',' '\n'
    return 0
  fi

  if command -v kubectl >/dev/null 2>&1; then
    kubectl get nodes \
      -o jsonpath='{range .items[*]}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{"\n"}{end}{end}' 2>/dev/null || true
  fi
}

select_container_tool() {
  if [ "${container_tool}" = "auto" ]; then
    if command -v podman >/dev/null 2>&1; then
      container_tool="podman"
    elif command -v docker >/dev/null 2>&1; then
      container_tool="docker"
    else
      echo "podman or docker is required to prepare RKE2 preload images." >&2
      exit 1
    fi
  fi

  if ! command -v "${container_tool}" >/dev/null 2>&1; then
    echo "Container tool not found: ${container_tool}" >&2
    exit 1
  fi
}

image_exists_locally() {
  local image="$1"
  case "${container_tool}" in
    podman)
      "${container_tool}" image exists "${image}" >/dev/null 2>&1
      ;;
    docker)
      "${container_tool}" image inspect "${image}" >/dev/null 2>&1
      ;;
    *)
      "${container_tool}" image inspect "${image}" >/dev/null 2>&1
      ;;
  esac
}

image_archive_name() {
  printf '%s.tar' "$(printf '%s' "$1" | sed -E 's#[^A-Za-z0-9_.-]+#_#g')"
}

ensure_archive_for_image() {
  local image="$1"
  local archive="$2"

  mkdir -p "${archive_dir}"
  if [ -s "${archive}" ] && [ "${reuse_archives}" = "true" ]; then
    echo "Using cached preload archive: ${archive}"
    return 0
  fi

  if ! image_exists_locally "${image}"; then
    echo "Source image ${image} is not local; pulling before RKE2 preload."
    "${container_tool}" pull "${image}"
  fi

  echo "Saving ${image} to ${archive}."
  "${container_tool}" save -o "${archive}" "${image}"
  test -s "${archive}"
}

remote_image_present() {
  local node="$1"
  local image="$2"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()
  local image_q

  mapfile -t ssh_options < <(ssh_options_for_node)
  image_q="$(shell_quote "${image}")"
  ssh "${ssh_options[@]}" "${ssh_user}@${node}" \
    "sudo -n sh -lc 'ctr=/var/lib/rancher/rke2/bin/ctr; socket=/run/k3s/containerd/containerd.sock; [ -S \"\$socket\" ] && [ -x \"\$ctr\" ] && \"\$ctr\" --address \"\$socket\" -n k8s.io images ls -q | grep -Fx -- ${image_q} >/dev/null'"
}

stage_archive_on_node() {
  local node="$1"
  local archive="$2"
  local archive_name="$3"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()
  local remote_archive="${rke2_image_dir}/${archive_name}"
  local remote_dir_q
  local remote_archive_q

  mapfile -t ssh_options < <(ssh_options_for_node)
  remote_dir_q="$(shell_quote "${rke2_image_dir}")"
  remote_archive_q="$(shell_quote "${remote_archive}")"

  echo "Streaming ${archive_name} to ${ssh_user}@${node}:${remote_archive}."
  if [ "${ssh_user}" = "root" ]; then
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" \
      "sh -lc 'mkdir -p ${remote_dir_q}; cat > ${remote_archive_q}; chmod 0644 ${remote_archive_q}; test -s ${remote_archive_q}'" < "${archive}"
  else
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" \
      "sudo -n sh -lc 'mkdir -p ${remote_dir_q}; cat > ${remote_archive_q}; chmod 0644 ${remote_archive_q}; test -s ${remote_archive_q}'" < "${archive}"
  fi
}

import_archive_on_node() {
  local node="$1"
  local archive_name="$2"
  local ssh_user="${MIGRATION_SSH_USER:-${ANSIBLE_USER:-root}}"
  local ssh_options=()
  local remote_archive="${rke2_image_dir}/${archive_name}"

  mapfile -t ssh_options < <(ssh_options_for_node)
  if [ "${ssh_user}" = "root" ]; then
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" sh -s -- "${remote_archive}" <<'REMOTE_IMPORT'
set -eu
archive="${1:?missing archive path}"
ctr=/var/lib/rancher/rke2/bin/ctr
socket=/run/k3s/containerd/containerd.sock
if [ -S "$socket" ] && [ -x "$ctr" ]; then
  "$ctr" --address "$socket" -n k8s.io images import "$archive"
  rm -f "$archive"
  echo "Imported $(basename "$archive") into running RKE2 containerd and removed staged tar file."
else
  echo "RKE2 containerd is not running; archive remains staged for startup import: $archive"
fi
REMOTE_IMPORT
  else
    ssh "${ssh_options[@]}" "${ssh_user}@${node}" sudo -n sh -s -- "${remote_archive}" <<'REMOTE_IMPORT'
set -eu
archive="${1:?missing archive path}"
ctr=/var/lib/rancher/rke2/bin/ctr
socket=/run/k3s/containerd/containerd.sock
if [ -S "$socket" ] && [ -x "$ctr" ]; then
  "$ctr" --address "$socket" -n k8s.io images import "$archive"
  rm -f "$archive"
  echo "Imported $(basename "$archive") into running RKE2 containerd and removed staged tar file."
else
  echo "RKE2 containerd is not running; archive remains staged for startup import: $archive"
fi
REMOTE_IMPORT
  fi
}

preload_image() {
  local image="$1"
  local archive_name
  local archive
  local node
  local missing_nodes=()

  archive_name="$(image_archive_name "${image}")"
  archive="${archive_dir}/${archive_name}"

  for node in "${nodes[@]}"; do
    node="${node//[[:space:]]/}"
    if [ -z "${node}" ]; then
      continue
    fi
    if remote_image_present "${node}" "${image}" >/dev/null 2>&1; then
      echo "Image ${image} is already present on ${node}; skipping upload."
    else
      missing_nodes+=("${node}")
    fi
  done

  if [ "${#missing_nodes[@]}" -eq 0 ]; then
    echo "Image ${image} is already present on all RKE2 nodes."
    return 0
  fi

  ensure_archive_for_image "${image}" "${archive}"
  for node in "${missing_nodes[@]}"; do
    stage_archive_on_node "${node}" "${archive}" "${archive_name}"
    import_archive_on_node "${node}" "${archive_name}"
  done

  if [ "${cleanup_archives}" = "true" ]; then
    rm -f "${archive}"
  fi
}

recover_migration_context
mapfile -t images < <(printf '%s\n' "${images_text}" | tr ', ' '\n\n' | awk 'NF && !seen[$0]++')
mapfile -t nodes < <(discover_nodes | awk 'NF && !seen[$0]++')

if [ "${#nodes[@]}" -eq 0 ]; then
  echo "No RKE2 nodes were discovered for image preload." >&2
  if [ "${required}" = "true" ]; then
    exit 1
  fi
  exit 0
fi

select_container_tool
for image in "${images[@]}"; do
  preload_image "${image}"
done

echo "RKE2 image preload completed for ${#images[@]} image(s) across ${#nodes[@]} node(s)."
