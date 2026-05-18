# Troubleshooting

## VIP does not move

Check Keepalived status and interface name:

```bash
systemctl status keepalived
ip addr show
journalctl -u keepalived -n 100
```

## Kubernetes API unreachable

```bash
systemctl status haproxy
ss -lntp | grep -E '6443|7443|9345|9346'
curl -k https://<vip>:7443/readyz
```

If Helm or kubectl tries `https://127.0.0.1:6443` on the operator machine,
repair the operator kubeconfig through the project target instead of editing it
by hand:

```bash
make operator-kubeconfig ENV=prod ENGINE=rke2 INVENTORY=<private-inventory>
kubectl config view --minify | grep server
```

`make install-operators` and `make deploy` run this step automatically.

## VIP shows ingress 404

A `404 Not Found` from Traefik or nginx at `http://<vip>` or `https://<vip>`
means the ingress controller is reachable, but no application or dashboard
Ingress currently matches that host/path. Install the application chart with
`make deploy` or install the Kubernetes Dashboard and expose it through an
Ingress/port-forward. The cluster install target only brings up Kubernetes and
the selected RKE2 ingress controller; it does not deploy the platform workload
by itself.

RKE2 nodes open `80/tcp` and `443/tcp` for the bundled ingress controller by
default. The chart root Ingress enables TLS and HTTP-to-HTTPS redirect by
default, so normal user traffic should enter through `https://<vip>` after the
application chart is deployed.

## RKE2 registration wait does not finish

The first RKE2 server must open local port `9345` before the VIP can forward
registration traffic. The first server config intentionally omits `server:` so
it can bootstrap the embedded datastore; later servers use the VIP registration
address. The install role probes the local listener in a retry loop that fails
with RKE2 service, journal, and socket diagnostics.

The role also rejects any rendered `/etc/rancher/rke2/config.yaml` that still
contains `cluster-init:` and prints an initial service/journal snapshot before
waiting. If the first snapshot already shows `ExecMainStatus=2`, use the
printed journal lines as the root cause.

The first server must not have a `server:` entry in
`/etc/rancher/rke2/config.yaml`; later servers must have one. The role validates
this before starting RKE2 to prevent the first server from trying to join
through a VIP that has no healthy backend yet.

If HAProxy is running but reports `backend rke2_registration_servers has no
server available`, check the RKE2 service diagnostics from the failed play
output first. HAProxy will keep the backend down until at least one server is
accepting TCP connections on `9345`.

If the journal shows `failed to recover v3 backend from snapshot`, `failed to
find database snapshot file`, or `snapshot file doesn't exist`, the node has a
stale or corrupt embedded-etcd datastore from an interrupted bootstrap. The RKE2
role scans the recent journal for that exact panic before waiting on `9345`,
stops the service, archives `/var/lib/rancher/rke2/server/db` to
`/var/lib/rancher/rke2/server/db.corrupt.<timestamp>`, resets the failed unit,
and retries startup. Set `rke2_auto_recover_corrupt_etcd_snapshot=false` in
inventory if you want to inspect and recover an established production datastore
manually.

If the journal shows `Unit process ... remains running after unit stopped` with
`failed to reconcile with local datastore: context deadline exceeded`, stale
RKE2 child processes are still bound to local datastore or API ports after a
failed service stop. The role stops RKE2, kills the stale service control group
and RKE2-owned component processes, resets the unit, and retries startup. Set
`rke2_cleanup_stale_processes=false` if you want to inspect those processes
manually before cleanup.

## RKE2 pod IP range overlaps another network

RKE2 defaults can place pods in `10.42.0.0/16` and services in `10.43.0.0/16`.
This project overrides those defaults to `100.64.0.0/16` for pods,
`100.65.0.0/16` for services, and `100.65.0.10` for cluster DNS. Set
`pod_cidr`, `service_cidr`, `cluster_dns`, and `cluster_underlay_cidrs` in the
private inventory before bootstrap if those ranges overlap your real routed
networks. Changing these values after a cluster is initialized requires
rebuilding the RKE2 datastore/cluster; do not change them in-place on a running
production cluster.

## CloudNativePG InitDB pods cannot reach the API

If CloudNativePG init jobs repeatedly fail with messages like
`dial tcp 100.65.0.1:443: i/o timeout`, workload pods cannot reach the
Kubernetes API service. Keep `networkPolicy.kubernetesApi.enabled=true`, and
narrow `networkPolicy.kubernetesApi.cidrs` to your service CIDR and API endpoint
CIDRs after bootstrap if you do not want the portable default.

## API server logs 502 to a pod IP

Messages such as `Sending HTTP/1.1 502 response ... dial tcp 100.64.x.y:10250`
usually mean the API server is proxying to an aggregated API pod, often
metrics-server, and the host firewall is blocking cross-node pod traffic. The
`100.64.0.0/16` range is the Kubernetes pod overlay, not the physical
`<node-lan-cidr>` node network.

The RKE2 role opens the RKE2 ports, trusts the configured pod and service CIDRs
in firewalld, and enables overlay egress masquerading. Re-run `make bootstrap` and `make install-cluster` after
updating the inventory or role, then verify:

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl top nodes
```

## Images cannot be pulled

Set `global.imageRegistry`, configure `imagePullSecrets`, or preload images:

```bash
scripts/images/export-from-host.sh
scripts/images/preload-rke2.sh dist/images
```

## CloudNativePG or ECK resources not recognized

Install operators:

```bash
make install-operators
kubectl get crd | grep -E 'postgresql.cnpg|elastic'
```

If Helmfile reports `unknown command "diff" for "helm"`, use
`helmfile -f deploy/helmfile.yaml.gotmpl sync` or run `make install-operators`
from a version of this repository that uses `sync`. The normal operator install
path intentionally avoids requiring the Helm diff plugin.

If the platform chart is denied with PostgreSQL 18, TimescaleDB, or Elastic
Stack 9.x validation errors, rerun `make deploy` from a version of this
repository that installs CloudNativePG 1.29+ and ECK 3.4+. The default
TimescaleDB resource also requires the chart's CNPG `ImageCatalog` template so
the operator sees `timescale/timescaledb:2.26.4-pg18` as PostgreSQL 18.

If CNPG `initdb` pods fail with `could not look up effective user ID 26`, the
cluster is trying to run an image whose `postgres` user is not UID 26. The chart
defaults `databases.postgresUID` and `databases.postgresGID` to `999`, matching
the Docker Hub Postgres-family images used by the default PostgreSQL, PostGIS,
and TimescaleDB clusters.

## PrometheusRule or ServiceMonitor resources not recognized

Install kube-prometheus-stack before enabling `monitoring.enabled=true`:

```bash
make install-operators
kubectl get crd | grep -E 'prometheusrules|servicemonitors'
kubectl -n observability get pods,svc
```

## Alert fires without a matching dashboard

Check the runbook first, then open the required dashboard list:

```bash
grep -A20 '^dashboards:' config/slo.yaml
kubectl -n urban-platform get prometheusrules.monitoring.coreos.com
```
