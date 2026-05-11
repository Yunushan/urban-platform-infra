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

Topology-specific starting points are also available:

```bash
cp inventories/topologies/single-node/hosts.yml inventories/prod/hosts.yml
cp inventories/topologies/three-node-ha/hosts.yml inventories/prod/hosts.yml
```

Use the matching Helm override when rendering or deploying:

```bash
helm template city-intersection-project helm/city-intersection-platform \
  --namespace city-intersection \
  -f helm/city-intersection-platform/values.yaml \
  -f helm/city-intersection-platform/topologies/three-node-ha.yaml
```

For a single-machine compatibility run:

```bash
make docker-up
```
