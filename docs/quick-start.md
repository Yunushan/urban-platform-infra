# Quick Start

```bash
cp inventories/example/hosts.yml inventories/prod/hosts.yml
cp .env.example .env
make validate
make preflight ENV=prod ENGINE=rke2
make bootstrap-check ENV=prod ENGINE=rke2
make install-cluster-check ENV=prod ENGINE=rke2
make bootstrap ENV=prod ENGINE=rke2 CONFIRM_PROD=true
make install-cluster ENV=prod ENGINE=rke2 CONFIRM_PROD=true
make install-operators
make deploy ENV=prod
```

`make deploy` installs Helm on the operator machine if the `helm` binary is
missing, then runs the chart upgrade/install.

Topology-specific starting points are also available:

```bash
cp inventories/topologies/single-node/hosts.yml inventories/prod/hosts.yml
cp inventories/topologies/three-node-ha/hosts.yml inventories/prod/hosts.yml
```

Use the matching Helm override when rendering or deploying:

```bash
helm template urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  -f helm/urban-platform-infra/values.yaml \
  -f helm/urban-platform-infra/topologies/three-node-ha.yaml
```

For a single-machine compatibility run:

```bash
make docker-up
```
