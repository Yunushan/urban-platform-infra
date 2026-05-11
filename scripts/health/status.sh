#!/usr/bin/env bash
set -euo pipefail
NS="${1:-city-intersection}"

echo "== Nodes =="
kubectl get nodes -o wide || true

echo "== Namespace: ${NS} =="
kubectl get ns "${NS}" || true

echo "== Workloads =="
kubectl -n "${NS}" get deploy,sts,po,svc,hpa,pdb || true

echo "== Data CRDs =="
kubectl -n "${NS}" get clusters.postgresql.cnpg.io,elasticsearch,kibana 2>/dev/null || true

echo "== Monitoring CRDs =="
kubectl -n "${NS}" get prometheusrules.monitoring.coreos.com,servicemonitors.monitoring.coreos.com 2>/dev/null || true

echo "== Observability namespace =="
kubectl -n observability get pods,svc 2>/dev/null || true
