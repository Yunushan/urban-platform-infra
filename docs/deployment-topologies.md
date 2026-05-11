# Deployment Topologies

The project supports multiple deployment sizes, but the default remains `three-node-ha`. Use these profiles to make node-count intent explicit instead of silently changing inventories and replica values.

## Profiles

| Profile | Intended use | Shape | Production |
|---|---|---|---|
| `single-node` | One VM/server, dev, demo, constrained environments | 1 server | No |
| `two-node-lab` | Lab/staging with one server and one worker | 1 server + 1 worker | No |
| `three-node-ha` | Default production HA | 3 server/load-balancer nodes | Yes |
| `multi-node-ha` | Production HA with additional workers | 3 or 5 servers + workers | Yes |

The contract is stored in `config/deployment-topologies.yaml`.

## Helm Usage

Render or deploy with a topology override:

```bash
helm template city-intersection-project helm/city-intersection-platform \
  --namespace city-intersection \
  -f helm/city-intersection-platform/values.yaml \
  -f helm/city-intersection-platform/topologies/single-node.yaml
```

For production, use `three-node-ha` or `multi-node-ha`, then add a private production override for real DNS, TLS, registry, storage classes, and digest-pinned images.

## Ansible Inventory Usage

Use one of the topology inventories as a starting point:

```bash
cp inventories/topologies/three-node-ha/hosts.yml inventories/prod/hosts.yml
```

Then replace placeholder values with vaulted tokens, real host addresses, production DNS, and approved network values. Do not commit the resulting production inventory.

## Single Node

Use `single-node` for one VM or one server.

Key behavior:

- one RKE2/K3s server
- no load-balancer group by default
- `cluster_vip` points at the node address
- `global.replicaOverride: 1`
- autoscaling disabled
- Redis Sentinel disabled

This is not HA. It is useful for evaluation, local operations testing, or a small non-critical deployment.

## Two Node Lab

Use `two-node-lab` as one control-plane server plus one worker/agent.

Do not treat two embedded-etcd control-plane nodes as production HA. Quorum behavior is weak with two members. If you need two nodes for a serious environment, use K3s with an external datastore or move to `three-node-ha`.

## Three Node HA

Use `three-node-ha` for the default production topology:

- three RKE2 server nodes
- HAProxy/Keepalived VIP on the control-plane nodes
- three replicas for most application/data workloads
- odd etcd/control-plane count for quorum

## Multi Node HA

Use `multi-node-ha` when application capacity needs to grow:

- keep 3 or 5 control-plane nodes
- add workers under `rke2_agents`
- keep the load-balancer group on stable control-plane/load-balancer nodes
- scale workloads only after capacity and failure testing

Do not increase control-plane nodes to an even number. Use 3 for most cases and 5 for larger production clusters.
