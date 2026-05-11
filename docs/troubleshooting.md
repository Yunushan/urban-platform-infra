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
ss -lntp | grep -E '6443|9345'
curl -k https://<vip>:6443/readyz
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
kubectl -n city-intersection get prometheusrules.monitoring.coreos.com
```
