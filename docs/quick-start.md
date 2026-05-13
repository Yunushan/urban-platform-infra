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

`make deploy` installs Helm and Helmfile on the operator machine if they are
missing, installs the required operator CRDs, waits for the default CNPG and ECK
CRDs, then runs the chart upgrade/install.

The install/deploy targets repair the operator kubeconfig automatically for
RKE2. They copy it from the first server and rewrite `127.0.0.1:6443` to the
configured Kubernetes API VIP port before running Helm or kubectl.

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
