# Urban Platform Topology

This is the canonical public-safe topology reference for
`urban-platform-infra`. It describes the logical architecture, physical
deployment shape, traffic paths, stateful services, delivery flow, and failure
domains without exposing site-specific addresses or credentials.

Use placeholders such as `control-plane-1`, `cluster-vip`,
`platform.example.internal`, `namespace`, and
`private-registry.example.internal`. Replace them only in private environment
overlays or operator runbooks.

The diagrams use Mermaid so they can be reviewed in GitHub and rendered by
documentation tooling. The [High-Level Design](hld.md) and
[Low-Level Design](lld.md) use this document as their visual topology source.

## Diagram Legend

| Shape or boundary | Meaning |
|---|---|
| External actor | User, operator, CI runner, registry, DNS, or secret system outside the cluster |
| HA edge | Keepalived and HAProxy provide stable VIP behavior and health-based forwarding |
| Control plane | RKE2 server nodes and embedded etcd quorum |
| Platform plane | Traefik, operators, policy, observability, and shared services |
| Workload plane | Imported or native application Deployments, Services, and ConfigMaps |
| State plane | PostgreSQL-family databases, Kafka, Redis, PVCs, and backups |
| Dashed edge | Optional, private, or operator-controlled integration |

## 1. System Context

This is the high-level context view. A request reaches the cluster through a
stable DNS name or, in lab IP mode, a hostless ingress bound to the cluster
VIP. Control-plane operations use a separate Kubernetes API path.

```mermaid
flowchart LR
    user["Users and API clients"]
    operator["Operator machine\nMake, Ansible, Helm, import tools"]
    ci["CI/CD\nvalidation and release gates"]
    dns["DNS or lab IP entry\nplatform.example.internal / cluster-vip"]
    registry["Private registry\noptional production image source"]
    secrets["Secret source\nVault, SOPS, External Secrets, or private operator state"]

    subgraph edge["HA edge and Kubernetes access"]
        vip["Cluster VIP"]
        haproxy["HAProxy\nAPI and edge forwarding"]
        keepalived["Keepalived\nVIP ownership"]
    end

    subgraph cluster["RKE2 cluster"]
        api["Kubernetes API"]
        ingress["Traefik ingress"]
        platform["Platform chart and operators"]
        workloads["Application workloads\nDeployments and Services"]
        state["State services\nCNPG, Kafka, Redis, PVCs"]
        observe["Observability\noptional"]
    end

    user --> dns
    dns --> vip
    operator --> haproxy
    ci -. release evidence .-> operator
    registry -. image promotion or pull .-> platform
    secrets -. secret reconciliation .-> platform
    vip --> haproxy
    keepalived --> vip
    haproxy --> api
    haproxy --> ingress
    api --> platform
    ingress --> workloads
    platform --> workloads
    workloads --> state
    platform --> state
    workloads -. metrics and logs .-> observe
    platform -. metrics and logs .-> observe
```

## 2. Production Physical Topology

The default production contract is `three-node-ha`: three RKE2 server nodes,
an odd embedded-etcd quorum, and an HA edge on the control-plane nodes. Worker
nodes can be added through the `multi-node-ha` profile without changing the
control-plane quorum shape.

```mermaid
flowchart TB
    clients["Users, automation, and external clients"]
    vip["cluster-vip\nTCP 80/443 for ingress\nconfigurable API VIP port"]

    subgraph ha["Three-node HA failure domain"]
        n1["control-plane-1\nRKE2 server\nembedded etcd\nKeepalived + HAProxy"]
        n2["control-plane-2\nRKE2 server\nembedded etcd\nKeepalived + HAProxy"]
        n3["control-plane-3\nRKE2 server\nembedded etcd\nKeepalived + HAProxy"]
        etcd["Embedded etcd quorum\n3 members, majority required"]
    end

    subgraph workers["Optional worker capacity"]
        w1["worker-1\nRKE2 agent"]
        w2["worker-2\nRKE2 agent"]
        wn["worker-N\nRKE2 agent"]
    end

    subgraph ns["Kubernetes namespace: namespace"]
        tr["Traefik"]
        apps["Stateless workloads\nspread by replicas and policy"]
        db["CNPG PostgreSQL-family clusters"]
        kafka["Strimzi-managed Apache Kafka"]
        redis["Redis or Redis Sentinel profile"]
    end

    clients --> vip
    vip --> n1
    vip --> n2
    vip --> n3
    n1 --- etcd
    n2 --- etcd
    n3 --- etcd
    n1 --> tr
    n2 --> tr
    n3 --> tr
    tr --> apps
    tr --> db
    tr --> kafka
    tr --> redis
    n1 --> w1
    n2 --> w2
    n3 --> wn
    w1 --> apps
    w2 --> apps
    wn --> apps
```

### Physical topology rules

1. Keep the RKE2 server count odd, normally three or five, so embedded etcd
   retains a majority during a node failure.
2. Keep the VIP on a network path reachable by every intended client and by
   every HA edge node. A VIP configured on the host but blocked by routing or
   firewall policy is not an available endpoint.
3. Treat `local-path` storage as node-local. A PVC bound to one node is not a
   portable replica and does not provide storage high availability.
4. Use a replicated or network-backed StorageClass for production databases,
   Kafka, and other durable state unless the platform has an explicit node
   affinity and recovery plan.
5. Add workers when workload capacity grows; do not add an even control-plane
   count merely to gain compute capacity.

## 3. Ingress Request Flow

The ingress mode determines whether routing is host-based or hostless.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant E as HA edge and VIP
    participant T as Traefik
    participant I as Ingress rule
    participant S as ClusterIP Service
    participant W as Workload pod

    C->>E: HTTP or HTTPS request
    E->>T: Forward after listener health check
    T->>I: Match host, path, or hostless IP rule
    I->>S: Select backend Service
    S->>W: Select ready endpoint
    W-->>C: Response through the same path
```

| Mode | Match key | TLS expectation | Recommended use |
|---|---|---|---|
| FQDN | `platform.example.internal` | Trusted certificate or approved internal CA | Production and normal user access |
| IP hostless | `cluster-vip` with no Host requirement | Certificate must contain the IP; self-signed still needs client trust | Lab, private network, or controlled automation |
| HTTP | Path only, no TLS termination | None | Temporary lab routing and diagnostics only |

An IP address cannot receive a public ACME certificate in the same way as a
normal DNS name, and a self-signed certificate is not automatically trusted by
browsers. The platform can automate certificate creation and secret delivery,
but client trust still belongs to the operating-system or browser trust store.

## 4. Application, Data, and Messaging Flow

The application plane is stateless where possible. Database and messaging
connections stay on internal Kubernetes Services and should never depend on a
hard-coded legacy host address after import.

```mermaid
flowchart LR
    gw["Traefik and web gateway"] --> api["Application API Services"]
    api --> worker["Workers and scheduled services"]
    api --> cache["Redis Service"]
    api --> pg["CNPG PostgreSQL Service"]
    api --> postgis["CNPG PostGIS Service"]
    api --> ts["TimescaleDB Service"]
    worker --> kafka["Apache Kafka\nStrimzi bootstrap Service"]
    worker --> pg
    worker --> ts
    kafka --> consumers["Consumers and stream workers"]
    pg --> backups["Database-native backup target"]
    postgis --> backups
    ts --> backups
    backups --> object["Private object storage\noptional cold tier"]
```

### Stateful service boundaries

| Boundary | Owner | Kubernetes contract | Recovery source |
|---|---|---|---|
| PostgreSQL | CloudNativePG | `Cluster` plus read-write/read-only Services | Logical dump/restore and database-native backup |
| PostGIS | CloudNativePG | PostgreSQL cluster with PostGIS image/extensions | Logical dump/restore plus extension validation |
| TimescaleDB | CloudNativePG or approved target profile | PostgreSQL-compatible Service and extension contract | Logical dump/restore plus extension validation |
| Apache Kafka | Strimzi | `Kafka`, `KafkaNodePool`, bootstrap Service | Topic/config export and approved durable volume/backup plan |
| Redis | Helm chart or approved operator profile | Service, StatefulSet, optional Sentinel | Snapshot/replication plan appropriate to cache role |

## 5. Delivery and Import Flow

This is the control-plane flow from a change in Git to a verified workload.

```mermaid
flowchart TD
    change["Git change or approved source project"]
    static["Static validation\nYAML, Python, Ansible, Shell"]
    policy["Policy and security validation\nimage policy, rendered manifests, PSA"]
    render["Helm and Helmfile render\nvalues plus topology overlay"]
    access["Kubernetes access check\nkubeconfig, API readiness, VIP path"]
    ops["Operator installation\nCNPG, cert-manager, Strimzi, optional"]
    stage["Private migration staging\nreports, secrets, images, DB targets"]
    apply["Apply or reconcile\nHelm, operator, or GitOps"]
    rollout["Rollout gates\nDeployments, StatefulSets, Services"]
    smoke["Smoke tests\nHTTP/TLS, database, Kafka, DNS"]
    evidence["Release evidence\nredacted public summary plus private details"]
    rollback["Rollback or repair\nprevious release, restore, or runbook"]

    change --> static --> policy --> render --> access
    access --> ops --> stage --> apply --> rollout --> smoke --> evidence
    static -. failure .-> rollback
    policy -. failure .-> rollback
    access -. failure .-> rollback
    rollout -. failure .-> rollback
    smoke -. failure .-> rollback
```

### Import stage boundaries

| Stage | Reads | Writes | Safe retry behavior |
|---|---|---|---|
| Prepare | Compose project and public values | Private compatibility report, target map, action plan | Rebuilds private planning outputs |
| Secrets | Approved source secret material | Kubernetes Secrets or external-secret references | Server-side apply with stable names |
| Images | Compose build contexts or registry images | Registry tags/digests or RKE2 preload archives | Digest/tag checks prevent unnecessary transfer |
| Databases | Source endpoints and approved credentials | Logical dumps and target restore state | Target map and dump checkpoints are retained privately |
| Manifests | Rendered workload model | Deployments, Services, ConfigMaps, Ingress | Server-side apply and selected-resource cleanup |
| Validate | Cluster objects and runtime endpoints | Redacted validation reports and private diagnostics | Read-only checks; failed checks identify blockers |

## 6. Failure Domains and Recovery

```mermaid
flowchart TB
    subgraph F1["Failure domain: one edge or control-plane node"]
        edge1["HAProxy/Keepalived"]
        cp1["RKE2 server and etcd member"]
    end
    subgraph F2["Failure domain: workload node"]
        worker1["RKE2 agent"]
        app1["Stateless pod replicas"]
    end
    subgraph F3["Failure domain: local durable volume"]
        pvc1["PVC and local path"]
        state1["Database or Kafka data"]
    end
    subgraph F4["Failure domain: external dependency"]
        dns1["DNS"]
        registry1["Registry"]
        secret1["Secret source"]
        backup1["Backup object store"]
    end

    edge1 --> cp1
    cp1 --> worker1
    worker1 --> app1
    app1 --> state1
    pvc1 --> state1
    dns1 -.-> edge1
    registry1 -.-> worker1
    secret1 -.-> app1
    backup1 -.-> state1
```

| Failure | Expected behavior | Operator evidence | Recovery action |
|---|---|---|---|
| One HA edge/control-plane node fails | VIP moves or remaining edge accepts traffic; etcd keeps quorum | Node health, VIP owner, API readiness, etcd health | Repair node, verify quorum, then return it to service |
| One worker fails | Replica scheduling moves ready stateless pods if capacity exists | Node conditions and pending pods | Restore capacity or reduce workload batch |
| One application pod fails | Deployment recreates it; Service removes unready endpoint | Rollout status and pod events | Inspect image, config, secret, and dependency probes |
| Local PVC host fails | State is unavailable unless replicated/backed up | PVC node affinity, CNPG/Kafka status, backup age | Restore to a replacement volume or execute stateful recovery runbook |
| Registry unavailable | Existing pinned workloads continue; new image pulls fail | Image pull events and registry probe | Use cached/preload image only for approved lab recovery |
| Secret source unavailable | Existing pods may continue; reconciliation/new rollout can fail | Secret provider status and events | Restore secret source or use approved break-glass secret path |
| DNS unavailable | Existing connections may continue; new name resolution fails | Resolver and ingress checks | Use controlled VIP fallback while DNS is repaired |

## 7. Supported Topology Profiles

The authoritative profile catalog is
[`config/deployment-topologies.yaml`](../config/deployment-topologies.yaml).

| Profile | Control plane | Workers | HA claim | Use |
|---|---:|---:|---|---|
| `single-node` | 1 | 0 | None | Development, demo, or constrained lab |
| `two-node-lab` | 1 | 1 | No embedded-etcd HA | Staging or migration rehearsal |
| `three-node-ha` | 3 | 0 initially | RKE2 server and VIP HA | Default production baseline |
| `multi-node-ha` | 3 or 5 | Scalable | Control-plane plus worker HA | Larger production capacity |

Profile selection is a contract, not a cosmetic label. The selected profile
must agree across the Ansible inventory, Helm topology values, capacity gates,
storage classes, and operational runbooks.

## 8. Network Contract

The following is a logical contract. Actual ports, firewall rules, and private
addresses belong in the environment overlay.

| Path | Source | Destination | Purpose |
|---|---|---|---|
| Edge HTTP | Client | Cluster VIP | Lab HTTP or redirect-to-HTTPS entry |
| Edge HTTPS | Client | Cluster VIP | TLS ingress entry |
| Kubernetes API | Operator and nodes | API VIP or direct server endpoint | Cluster control and reconciliation |
| Intra-cluster service | Workload pod | ClusterIP Service | Application, database, cache, and messaging traffic |
| Image pull | Node runtime | Registry or preload store | Pinned image retrieval |
| Secret sync | Operator or controller | Approved secret source | Secret reconciliation |
| Backup | Database/operator | Private object storage | Durable recovery artifacts |

NetworkPolicy should allow only the paths required by the selected services.
Ingress, egress, and service-mesh changes must be reviewed with DNS, TLS,
Kubernetes API access, and rollback behavior together.

## 9. Ownership Model

| Area | Primary owner in this repository | Environment-owned input |
|---|---|---|
| Cluster bootstrap | Ansible and Make targets | Inventory, OS access, tokens, node addresses |
| Operator lifecycle | Helmfile and operator install scripts | Chart policy, repository availability, CRD approval |
| Platform resources | Helm chart | Values overlay, replica/capacity choices |
| Imported workloads | Migration scripts | Source Compose project, service filters, secrets |
| Data migration | Migration scripts plus database operators | Credentials, dump location, restore approval |
| DNS and certificates | Ingress/TLS templates and cert-manager integration | DNS records, issuer, trust distribution |
| Backups and recovery | Policy and backup templates | Object store, retention, restore drills |
| Production evidence | CI and validation scripts | Private logs, approvals, incident/change records |

## 10. Review and Evidence Checklist

Before calling a topology production-ready, verify:

- the profile and node inventory agree;
- the API endpoint and ingress VIP are reachable from every intended client;
- HAProxy and Keepalived health checks are passing on all edge nodes;
- RKE2/etcd quorum survives one control-plane failure;
- workloads have enough replicas and scheduling capacity;
- stateful PVCs use an approved durability and recovery design;
- database, Kafka, Redis, TLS, and HTTP smoke tests pass;
- image digests, SBOM/signature evidence, and registry pull behavior are known;
- private reports, credentials, real addresses, and dumps remain outside Git;
- restore, rollback, and node-replacement drills have evidence.

Related implementation details are in the [HLD](hld.md), [LLD](lld.md),
[Deployment Topologies](deployment-topologies.md), [High Availability](high-availability.md),
[Operations](operations.md), and [Disaster Recovery](disaster-recovery.md)
documents.
