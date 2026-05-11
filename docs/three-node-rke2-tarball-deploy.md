# Three-Node RKE2 Tarball Deployment

This guide describes how to deploy a previously packaged application archive onto three local RKE2 nodes without documenting private IPs, credentials, hostnames, tokens, or registry secrets.

Use placeholders in committed files. Keep real values in a private inventory, Ansible Vault, SOPS, a password manager, or your CI/CD secret store.

## Deployment Shape

- Three local Linux nodes run RKE2 server components.
- HAProxy and Keepalived provide a control-plane virtual IP.
- Application components are deployed as Kubernetes workloads.
- Container images are either pushed to a private registry or preloaded onto every RKE2 node.

Do not deploy by untarring application folders onto each node and starting services manually. RKE2 should run container images through Kubernetes manifests or Helm charts.

## Operator Prerequisites

Install these on the operator machine:

- SSH access to all three nodes with sudo privileges.
- Ansible.
- Docker or another image builder.
- kubectl.
- Helm.

On each target node:

- Use a supported Linux distribution, such as Ubuntu 24.04.
- Set stable hostnames.
- Configure static IP addresses or DHCP reservations.
- Ensure the nodes can reach each other.
- Reserve one unused virtual IP on the same network for Keepalived.

## Prepare The Application Archive

Extract the archive on the operator machine:

```bash
mkdir -p ~/work/previous-app
tar -xzf <application-archive>.tar.gz -C ~/work/previous-app
cd ~/work/previous-app
```

Inspect the contents:

```bash
find . -maxdepth 3 -type f | sort
find . -maxdepth 3 \( -iname "Dockerfile" -o -iname "docker-compose*.yml" -o -iname "Chart.yaml" \)
```

Map the folders to deployment units, for example:

| Folder | Kubernetes target |
|---|---|
| `backend/` | Deployment and Service |
| `interface/` | Deployment, Service, and optionally Ingress |
| `database/` | StatefulSet or managed database chart |
| `monitoring/` | Helm chart, Deployment, or external monitoring stack |

## Build Images

Build one image per runnable component:

```bash
docker build -t previous-app-backend:local ./backend
docker build -t previous-app-interface:local ./interface
```

If a component already has a Helm chart, keep its chart and only override image names/tags through values.

## Choose Image Distribution

Use one of these approaches.

### Option A: Private Registry

Tag and push images to a registry that all RKE2 nodes can pull:

```bash
docker tag previous-app-backend:local <registry>/<namespace>/previous-app-backend:<tag>
docker tag previous-app-interface:local <registry>/<namespace>/previous-app-interface:<tag>

docker push <registry>/<namespace>/previous-app-backend:<tag>
docker push <registry>/<namespace>/previous-app-interface:<tag>
```

Store registry credentials outside Git. Use `imagePullSecrets`, External Secrets, SOPS, Sealed Secrets, or Vault for production credentials.

### Option B: Preload Images On Each RKE2 Node

For a local lab without a registry, save image tar files:

```bash
mkdir -p dist/images
docker save previous-app-backend:local -o dist/images/previous-app-backend.tar
docker save previous-app-interface:local -o dist/images/previous-app-interface.tar
```

Copy the image tar files to every node:

```bash
for node in <node-1> <node-2> <node-3>; do
  scp dist/images/*.tar <ssh-user>@${node}:/tmp/
  ssh <ssh-user>@${node} 'sudo mkdir -p /var/lib/rancher/rke2/agent/images && sudo cp /tmp/*.tar /var/lib/rancher/rke2/agent/images/'
done
```

Restart RKE2 after preloading:

```bash
for node in <node-1> <node-2> <node-3>; do
  ssh <ssh-user>@${node} 'sudo systemctl restart rke2-server'
done
```

## Create A Private Three-Node Inventory

From this repository:

```bash
cp inventories/topologies/three-node-ha/hosts.yml inventories/prod/hosts.yml
```

Edit `inventories/prod/hosts.yml` locally. Do not commit real values.

Use placeholders like this in documentation and examples:

```yaml
all:
  vars:
    ansible_user: <ssh-user>
    cluster_engine: rke2
    cluster_vip: <unused-lan-vip>
    cluster_domain: <cluster-domain>
    rke2_token: "<vaulted-rke2-token>"
    rke2_version: "v<major>.<minor>.<patch>+rke2r<revision>"
    keepalived_auth_pass: "<vaulted-keepalived-pass>"
    keepalived_interface: <network-interface>
  children:
    rke2_servers:
      hosts:
        node-1:
          ansible_host: <node-1-ip>
          node_ip: <node-1-ip>
          keepalived_priority: 110
        node-2:
          ansible_host: <node-2-ip>
          node_ip: <node-2-ip>
          keepalived_priority: 105
        node-3:
          ansible_host: <node-3-ip>
          node_ip: <node-3-ip>
          keepalived_priority: 100
    rke2_agents:
      hosts: {}
    load_balancers:
      hosts:
        node-1:
        node-2:
        node-3:
```

Generate strong secret values outside Git:

```bash
openssl rand -hex 32
```

Encrypt production inventory or variable files with Ansible Vault or SOPS before storing them anywhere shared.

## Bootstrap RKE2

Run checks first:

```bash
make validate
make lint
make preflight ENV=prod ENGINE=rke2 INVENTORY=inventories/prod/hosts.yml
make bootstrap-check ENV=prod ENGINE=rke2 INVENTORY=inventories/prod/hosts.yml
make install-cluster-check ENV=prod ENGINE=rke2 INVENTORY=inventories/prod/hosts.yml
```

Apply the bootstrap only after the checks pass:

```bash
make bootstrap ENV=prod ENGINE=rke2 INVENTORY=inventories/prod/hosts.yml CONFIRM_PROD=true
make install-cluster ENV=prod ENGINE=rke2 INVENTORY=inventories/prod/hosts.yml CONFIRM_PROD=true
```

Copy kubeconfig from the first server node, then replace the server address with the cluster VIP or DNS name:

```bash
scp <ssh-user>@<node-1>:/etc/rancher/rke2/rke2.yaml ./kubeconfig-rke2
export KUBECONFIG="$PWD/kubeconfig-rke2"
kubectl get nodes -o wide
```

## Deploy The Application

If the previous project already has a Helm chart:

```bash
helm upgrade --install previous-app <chart-path> \
  --namespace previous-app \
  --create-namespace \
  -f <sanitized-values-file>
```

If you are using this repository chart, create a private values override that points at your images:

```yaml
global:
  imageRegistry: "<registry>/<namespace>"
  imagePullSecrets:
    - registry-credentials

ingress:
  host: <application-domain>
```

Deploy with the three-node topology override:

```bash
helm upgrade --install urban-platform-infra helm/urban-platform-infra \
  --namespace urban-platform \
  --create-namespace \
  -f helm/urban-platform-infra/values.yaml \
  -f helm/urban-platform-infra/topologies/three-node-ha.yaml \
  -f <private-values-file>
```

For components without Helm, create Kubernetes manifests:

```bash
kubectl create namespace previous-app

kubectl create deployment backend \
  --image=<registry-or-local-image>/previous-app-backend:<tag> \
  --namespace previous-app

kubectl expose deployment backend \
  --port=<service-port> \
  --target-port=<container-port> \
  --namespace previous-app
```

Use StatefulSets and persistent volumes for databases. Avoid running databases as plain Deployments unless the data is disposable.

## Verify

```bash
kubectl get nodes -o wide
kubectl -n previous-app get deploy,sts,pod,svc,ingress,pvc
kubectl -n previous-app describe pod <pod-name>
kubectl -n previous-app logs deploy/<deployment-name>
```

If images do not pull:

- confirm the image name and tag match the manifest,
- confirm every node has the preloaded image,
- or confirm the registry secret exists in the namespace.

If pods do not schedule:

- check node resources,
- check persistent volume availability,
- check anti-affinity and topology spread rules,
- check taints and tolerations.

## Keep Private Data Out Of Git

Do not commit:

- real node IP addresses,
- SSH usernames tied to individuals,
- RKE2 tokens,
- Keepalived passwords,
- registry credentials,
- kubeconfig files,
- database passwords,
- TLS private keys,
- production DNS names if they are sensitive.

Commit only sanitized examples and placeholders.
