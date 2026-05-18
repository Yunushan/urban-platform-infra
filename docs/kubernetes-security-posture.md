# Kubernetes Security Posture

This chart uses Kubernetes-native controls first: Pod Security Admission, service account isolation, service-link suppression, and NetworkPolicy isolation. These defaults are designed for infrastructure deployment without embedding private data or organization-specific disclosure details.

## Pod Security Admission

The namespace renders Pod Security Admission labels with separate modes:

- `enforce`: `baseline` by default for compatibility with third-party infrastructure images.
- `audit`: `restricted` by default so incompatible pods are visible before enforcing stricter rules.
- `warn`: `restricted` by default so operators see restricted-profile gaps during deployment.
- `version`: `latest` by default; pin this to your cluster minor version during controlled production rollouts.

The Kubernetes Pod Security Standards define `baseline` as protection against known privilege escalations and `restricted` as the profile aligned with current pod hardening practices.

## Service Account Exposure

All native pod templates use the chart service account and set `automountServiceAccountToken: false`. Workloads that need Kubernetes API access should opt in deliberately and prefer short-lived projected tokens.

`enableServiceLinks: false` is also enabled globally to avoid injecting cluster service inventory into every pod environment.

## Network Isolation

NetworkPolicy is split into named policies:

- `urban-platform-default-deny` isolates all ingress and egress by default.
- `urban-platform-same-namespace` allows same-namespace pod communication.
- `urban-platform-ingress-controller` allows ingress from configured ingress-controller namespaces.
- `urban-platform-dns-egress` allows DNS only to the configured cluster DNS selector.
- `urban-platform-cnpg-operator-ingress` allows the CloudNativePG operator to
  reach database instance-manager and PostgreSQL ports.
- `urban-platform-kubernetes-api-egress` allows controller and bootstrap pods to
  reach the Kubernetes API on TCP 443/6443.
- `urban-platform-external-web-egress` allows configurable outbound TCP ports for package downloads or webhook access.

Keep `externalWeb.cidrs` narrow in production. The default `0.0.0.0/0` is a portable bootstrap setting, not a final enterprise allowlist.

## CI Policy Checks

The rendered-manifest policy check now verifies:

- Namespace Pod Security Admission labels are present.
- Required NetworkPolicies are rendered.
- Pods do not use host namespaces.
- Pods use a dedicated service account.
- Pods disable service account token automount and service links.
- Application workloads use `RuntimeDefault` seccomp, run as non-root, disable privilege escalation, and drop all Linux capabilities.

## References

- Kubernetes Pod Security Standards: https://kubernetes.io/docs/concepts/security/pod-security-standards/
- Kubernetes Service Accounts: https://kubernetes.io/docs/concepts/security/service-accounts/
- Kubernetes Network Policies: https://kubernetes.io/docs/concepts/services-networking/network-policies/
