# Runbooks

These runbooks are safe for the public repository. Keep private IPs, internal hostnames, credentials, customer details, and disclosure-sensitive system names out of this file.

## Deployment Replicas Unavailable

Alert: `CityIntersectionDeploymentReplicasUnavailable`

1. Check the deployment and events:

```bash
kubectl -n city-intersection get deploy,po
kubectl -n city-intersection describe deploy <deployment>
kubectl -n city-intersection get events --sort-by=.lastTimestamp
```

2. Check image pulls, scheduling, probes, and resource pressure.
3. Roll back if the issue follows a recent deployment:

```bash
helm history city-intersection-project -n city-intersection
helm rollback city-intersection-project <REVISION> -n city-intersection
```

## StatefulSet Replicas Unavailable

Alert: `CityIntersectionStatefulSetReplicasUnavailable`

1. Identify the affected dependency:

```bash
kubectl -n city-intersection get sts,po,pvc
kubectl -n city-intersection describe sts <statefulset>
```

2. Check PVC binding, node pressure, anti-affinity placement, and recent restarts.
3. Avoid deleting multiple stateful pods at once. Restore quorum first, then repair replicas one at a time.

## Container Restarts

Alert: `CityIntersectionContainerRestartingTooOften`

1. Inspect the restart reason:

```bash
kubectl -n city-intersection describe pod <pod>
kubectl -n city-intersection logs <pod> --previous
```

2. Check memory limits, startup time, dependency connection errors, and probe thresholds.
3. If restarts started after a release, compare values and image tags with the previous Helm revision.

## HPA Saturated

Alert: `CityIntersectionHPASaturated`

1. Check HPA and pod resource usage:

```bash
kubectl -n city-intersection get hpa
kubectl -n city-intersection top pods
```

2. Increase capacity only after confirming the load is expected.
3. If saturation is caused by a dependency outage, fix the dependency before scaling the caller.

## Persistent Volume Filling

Alert: `CityIntersectionPersistentVolumeFilling`

1. Identify the PVC and owning workload:

```bash
kubectl -n city-intersection get pvc
kubectl -n city-intersection describe pvc <pvc>
```

2. Check retention settings, log growth, Kafka topics, Redis persistence, Elasticsearch shards, and database backups.
3. Expand storage only after confirming the growth source and backup health.

## Observability Checks

```bash
make status
make observability-status
kubectl -n observability get pods,svc
kubectl -n city-intersection get prometheusrules.monitoring.coreos.com
```
