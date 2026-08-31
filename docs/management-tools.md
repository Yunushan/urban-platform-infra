# Optional Management Tools

The repository supports eight management tools through a separate, explicit
workflow. They are disabled by default and are not part of `make deploy`,
`make install-operators`, normal CI, or the application Helm chart.

The machine-readable contract is
[`config/management-tools.yaml`](../config/management-tools.yaml). The
controller is [`scripts/management_tools.py`](../scripts/management_tools.py).

## Supported Boundaries

| Tool | Supported boundary | Default | Important constraint |
|---|---|---:|---|
| Rancher Manager Community | Kubernetes Helm install | Disabled | Prefer a dedicated management cluster for production; use `cattle-system`. |
| Portainer CE | Kubernetes Helm install | Disabled | Use the `portainer` namespace, durable storage, and TLS. |
| Headlamp | Kubernetes Helm install | Disabled | Use reviewed least-privilege RBAC, disable service-account impersonation, and use TLS. |
| Devtron OSS | Kubernetes Helm install | Disabled | Requires Helm 3.8+; plan its larger storage and resource footprint before enabling it. |
| FreeLens | Operator workstation | Disabled | Desktop client only; no Kubernetes workload is installed. |
| k9s | Operator workstation CLI | Disabled | Use a restricted kubeconfig context. |
| Komodo | External Docker Compose | Disabled | Core uses MongoDB; Periphery needs Docker access on the managed host. |
| Arcane | External Docker Compose | Disabled | Requires Docker socket access and external project/build directories. |

The four Helm integrations use upstream repositories and chart names from the
catalog. Chart versions are intentionally blank in the public values files:
the operator must provide an exact reviewed version and a private values file.
This avoids silently selecting a moving chart channel and keeps hostnames,
credentials, bootstrap settings, and identity configuration out of Git.
Rancher additionally requires a compatible Helm v3 executable; the repository's
standard Helm 4 executable is intentionally rejected for Rancher. Use a
separately installed Helm 3 binary through `MANAGEMENT_TOOLS_HELM`. Devtron
also uses Helm 3 and the installer enforces its upstream minimum of Helm
3.8.0.

## Inspect And Plan

List the complete catalog:

```bash
make management-tools-list
```

Generate the public-safe plan without changing a cluster or host:

```bash
make management-tools-plan \
  MANAGEMENT_TOOLS_SELECTED=rancher,portainer,headlamp,devtron \
  MANAGEMENT_TOOLS_OUTPUT=reports/management-tools-plan.md
```

FreeLens and k9s are intentionally represented in the plan only. Install
those desktop/CLI clients from their reviewed upstream release artifacts, then
load a least-privilege kubeconfig context. The repository does not download
desktop binaries or place them on a cluster node.

## Kubernetes Helm Install

Create one private values file per selected tool outside this checkout. The
files must configure the upstream chart’s hostname, TLS, authentication,
resource requests, storage, RBAC, and external secret references. Then run:

```bash
make management-tools-install ENV=lab \
  MANAGEMENT_TOOLS_SELECTED=headlamp \
  MANAGEMENT_TOOLS_CHART_VERSIONS=headlamp=0.32.0 \
  MANAGEMENT_TOOLS_VALUES_DIR=/var/lib/urban-platform/private/management-tools \
  MANAGEMENT_TOOLS_EXECUTE=true \
  MANAGEMENT_TOOLS_CONFIRM=true
```

With `MANAGEMENT_TOOLS_VALUES_DIR=/private/management-tools`, the controller
expects `/private/management-tools/headlamp.values.yaml`. It performs all
preflight checks before the first Helm mutation, adds/updates only the selected
upstream repository, installs the exact chart pin supplied through
`MANAGEMENT_TOOLS_CHART_VERSIONS` (or the selected values override), waits for
the release, uses Helm `--atomic` rollback behavior, and does not print the
private values content. Replace the example
`0.32.0` with the chart version reviewed for the target Kubernetes and tool
release.

The installer validates tool-specific safety settings without printing their
values: Portainer must explicitly keep `enterpriseEdition.enabled: false` and
enable persistence; Headlamp must explicitly disable
`config.unsafeUseServiceAccountToken` and use a non-`cluster-admin`
`clusterRoleBinding.clusterRoleName`. The other Helm tools still require the
operator's private values file to declare their reviewed hostname, TLS,
storage, identity, and external-secret settings.

Check the workstation-only tools without downloading or changing anything:

```bash
make management-tools-workstation-check \
  MANAGEMENT_TOOLS_SELECTED=freelens,k9s
```

The check compares the commands on `PATH` with the catalog pins (`FreeLens
1.10.3` and `k9s 0.51.0`) and writes a public-safe report. Update those pins in
a reviewed pull request when the operator workstation standard changes.

For a production profile, also pass `CONFIRM_PROD=true`; the normal production
overlay remains explicit and the management-tool operation remains separate:

```bash
make management-tools-install ENV=prod CONFIRM_PROD=true \
  MANAGEMENT_TOOLS_SELECTED=rancher \
  MANAGEMENT_TOOLS_CHART_VERSIONS=rancher=2.11.4 \
  MANAGEMENT_TOOLS_VALUES_DIR=/var/lib/urban-platform/private/management-tools \
  MANAGEMENT_TOOLS_HELM=/usr/local/bin/helm3 \
  MANAGEMENT_TOOLS_EXECUTE=true \
  MANAGEMENT_TOOLS_CONFIRM=true
```

The command refuses a missing chart pin, `latest`/floating selection, missing
private values file, relative values path, repository-local values file, or a
desktop/Compose tool passed to the Helm installer. It does not automatically
install Rancher, Devtron, or any other management plane during the core
application deployment.

## External Docker Compose

[`compose/management-tools-komodo.yml`](../compose/management-tools-komodo.yml)
and [`compose/management-tools-arcane.yml`](../compose/management-tools-arcane.yml)
contain independent Komodo Core/Mongo/Periphery and Arcane profiles. They have
no default active profile, require private digest-pinned image references and secret environment values, bind
UI ports to localhost by default, and mount Docker sockets only on the
external management host.

Create a private environment file outside Git. It must provide the image
references and required keys named in `config/management-tools.yaml`, including
the Komodo database/admin/JWT values and Arcane encryption/JWT values. The
controller passes the selected file into the containers as `env_file`, so
additional upstream settings such as OIDC configuration are preserved without
being copied into Git. Use the plan first:

```bash
make management-tools-compose-plan ENV=lab \
  MANAGEMENT_TOOLS_SELECTED=komodo,arcane \
  MANAGEMENT_TOOLS_ENV_FILE=/var/lib/urban-platform/private/management-tools/compose.env
```

Start only after reviewing the plan and the external host permissions:

```bash
make management-tools-compose-up ENV=lab \
  MANAGEMENT_TOOLS_SELECTED=komodo \
  MANAGEMENT_TOOLS_ENV_FILE=/var/lib/urban-platform/private/management-tools/compose.env \
  MANAGEMENT_TOOLS_EXECUTE=true \
  MANAGEMENT_TOOLS_CONFIRM=true
```

For production, add `CONFIRM_PROD=true`. The Compose workflow rejects a
repository-local environment file, missing values, and mutable or
non-digest-pinned image references. It
validates the selected Compose model before startup and does not configure
firewall rules, TLS certificates, DNS, or remote Periphery
agents automatically. For multiple managed servers, install Periphery with a
reviewed systemd/Ansible procedure and use expiring onboarding keys.

## Production Controls

- Keep Rancher and Devtron on a separate management cluster when capacity and
  operational boundaries justify it.
- Use an approved Kubernetes ingress, trusted TLS certificate, OIDC/SSO, MFA,
  and least-privilege RBAC for browser tools.
- Use durable CSI-backed storage and tested backup/restore for stateful tools.
- Keep Komodo and Arcane away from the RKE2 workload nodes unless the Docker
  socket risk has been explicitly accepted and isolated.
- Updates are approval-only: review upstream release notes, change one pin,
  run CI, capture rollback evidence, then deploy.

Upstream references: [Rancher installation](https://ranchermanager.docs.rancher.com/getting-started/installation-and-upgrade/install-upgrade-on-a-kubernetes-cluster/),
[Portainer CE Kubernetes installation](https://docs.portainer.io/start/install-ce/server/kubernetes/baremetal),
[Headlamp installation](https://headlamp.dev/docs/latest/installation/),
[Devtron installation](https://docs.devtron.ai/docs/setup/install),
[FreeLens releases](https://github.com/freelensapp/freelens/releases),
[k9s releases](https://github.com/derailed/k9s/releases),
[Komodo setup](https://komo.do/docs/setup), and
[Arcane Compose example](https://github.com/getarcaneapp/arcane/blob/main/docker/examples/compose.basic.yaml).
