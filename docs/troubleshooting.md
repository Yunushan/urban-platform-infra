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

## RKE2 registration wait does not finish

The first RKE2 server must open local port `9345` before the VIP can forward registration traffic. The first server config intentionally omits `server:` so it can bootstrap the embedded datastore; later servers use the VIP registration address. The install role probes the local listener in a retry loop that fails with RKE2 service, journal, and socket diagnostics.

The role also rejects any rendered `/etc/rancher/rke2/config.yaml` that still contains `cluster-init:` and prints an initial service/journal snapshot before waiting. If the first snapshot already shows `ExecMainStatus=2`, use the printed journal lines as the root cause.

The first server must not have a `server:` entry in `/etc/rancher/rke2/config.yaml`; later servers must have one. The role validates this before starting RKE2 to prevent the first server from trying to join through a VIP that has no healthy backend yet.

If HAProxy is running but reports `backend rke2_registration_servers has no server available`, check the RKE2 service diagnostics from the failed play output first. HAProxy will stay down until at least one server listens on `9345`.

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
