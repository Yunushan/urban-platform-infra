# Image Cache, Preload, And Cleanup

This is the public-safe operating contract for image movement during import.
It describes behavior without exposing private registry names, node addresses,
project names, image layers, or credentials.

## Modes

`MIGRATION_IMAGE_MODE=registry` is the production-friendly mode. The operator
builds or retags import candidates, pushes them to a private registry, and then
the platform deploys normal Kubernetes workloads. This mode requires a real
private registry and, when needed, registry credentials through
`MIGRATION_REGISTRY_USERNAME` and `MIGRATION_REGISTRY_PASSWORD`.

`MIGRATION_IMAGE_MODE=preload` is the lab and disconnected mode. The operator
uses a short-lived local image tag, saves a tar archive, streams it to every
node in `MIGRATION_RKE2_NODES`, and imports it into the running RKE2 containerd
socket when available. The operator machine is only a staging point.

`MIGRATION_IMAGE_MODE=skip` leaves image movement out of the migration. Use it
only when the old Compose deployment stays active or another approved image
promotion path already exists.

## One Command Plan

Generate the public-safe image cache plan before a heavy import:

```bash
make image-cache-plan \
  IMAGE_CACHE_PROFILE=lab-preload \
  MIGRATION_IMAGE_MODE=preload \
  MIGRATION_RKE2_NODES=node-01,node-02,node-03
```

The plan writes `reports/image-cache-plan.md`. It redacts private workspace and
registry details by default, counts the configured preload nodes, lists cleanup
settings, and calls out unsafe combinations such as preload mode without node
targets or registry mode without a registry.

## Cleanup Defaults

The import path defaults are intentionally aggressive for small labs:

- `MIGRATION_CLEANUP_OPERATOR_IMAGES=true`
- `MIGRATION_PRUNE_OPERATOR_CACHE=true`
- `MIGRATION_RKE2_IMPORT_IMAGES=true`

Those defaults remove generated import tags, short-lived local preload archives,
and dangling Docker/Podman image or builder cache after successful candidates.
Disable cleanup only while debugging a failed build or preserving an offline
evidence bundle.

## RKE2 Preload Behavior

Preload mode should include every node that can schedule imported workloads in
`MIGRATION_RKE2_NODES`. During execution, each archive is uploaded to the RKE2
image directory, imported into running containerd when possible, and removed
from the node after import. If containerd is not running, the archive remains in
the RKE2 image directory for startup import.

If pods later show `ImagePullBackOff`, first regenerate the image cache plan,
then verify that the node list includes the node where the pod is scheduled.
Only restart RKE2 during a maintenance window when running containerd import was
not possible.

## Profiles

The committed profile catalog lives in `config/image-cache.yaml`:

- `lab-preload`: default for small labs without a private registry.
- `production-registry`: preferred production path through a private registry.
- `disconnected-preload`: offline archive workflow with intentional retention.

Keep lab preload for 4 GiB/node test clusters. Switch to production registry
only after registry authentication, image scanning, SBOMs, signatures or
attestations, and release evidence are ready.
