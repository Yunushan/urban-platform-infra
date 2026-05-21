# Cluster Doctor And Guarded Repair

The cluster doctor is the public-safe first stop when `import-auto`, `deploy`,
or `operator-kubeconfig` cannot reach the Kubernetes API. It checks the operator
host, RKE2 node SSH/sudo access, API TCP paths, RKE2 services, HAProxy,
Keepalived, local `/readyz`, and listener ports without printing private IPs,
kubeconfig paths, credentials, or raw journals.

## Article 9 Baseline

Run the diagnostic report:

```bash
make cluster-doctor \
  CLUSTER_DOCTOR_NODES=<node-1>,<node-2>,<node-3> \
  CLUSTER_DOCTOR_SSH_USER=ansible
```

The report is written to `reports/cluster-doctor.md` and is safe to share. It
uses stable aliases such as `node-01` and `cluster-vip` instead of private
addresses.

When you intentionally want the existing guarded repair workflow to run, use:

```bash
make cluster-repair \
  CLUSTER_DOCTOR_NODES=<node-1>,<node-2>,<node-3> \
  CLUSTER_DOCTOR_SSH_USER=ansible
```

`cluster-repair` calls the same kubeconfig/RKE2 repair helper used by
`import-auto`. It can reconcile bootstrap and cluster installation when the
automation has enough SSH, sudo, version, token, VIP, and Keepalived inputs.

## What It Checks

- operator `kubectl` and `ssh` availability
- operator kubeconfig existence
- Kubernetes `/readyz` and version calls
- VIP API TCP reachability
- per-node RKE2 API and registration TCP reachability
- per-node SSH reachability
- passwordless sudo availability
- `rke2-server`, `rke2-agent`, `haproxy`, and `keepalived` service states
- local listener state for API, registration, ingress, and VIP ports
- HAProxy and Keepalived config validation
- local node `/readyz`
- recent journal error counts, never raw logs

## Interpretation

- SSH or sudo failures must be fixed before automatic repair can work.
- Node API ports listening with failing `/readyz` usually means RKE2 or embedded
  etcd needs private journal review.
- VIP API failures with healthy node APIs usually point to HAProxy, Keepalived,
  firewall, or VIP ownership.
- HAProxy config passing while the service crashes points to a package/runtime
  issue or a backend/TLS path that should be reviewed privately.
- Keepalived failures usually mean wrong interface, auth, or VIP settings.

Keep full diagnostic logs, kubeconfigs, inventories, tokens, and node addresses
on the operator machine only.
