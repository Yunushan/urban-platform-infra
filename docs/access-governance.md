# Access Governance And Tenant Isolation

## Article 22 Baseline

Access governance support is optional architecture and disabled by default. The
baseline keeps the chart's service account token automount disabled and uses a
public-safe planner to review RBAC, OIDC/SSO, Kubernetes audit logging,
break-glass access, tenant isolation, and tenant namespace boundaries before
stricter access controls are enabled.

The planner does not create users, groups, ClusterRoles, RoleBindings, OIDC
configuration, or tenant namespaces.

## Profiles

`config/access-governance.yaml` defines:

| Profile | Purpose | Runtime Change |
|---|---|---|
| `disabled` | Keep committed chart defaults | None |
| `lab-audit` | Review service-account and RBAC posture for lab imports | None |
| `production-rbac` | Prepare least-privilege RBAC, audit, and break-glass process | None |
| `oidc-sso` | Plan OIDC or Keycloak group-to-role mapping | None |
| `multi-tenant` | Plan namespace, RBAC, quota, NetworkPolicy, and secret boundaries | None |

## Planner

```bash
make access-governance-plan \
  ACCESS_GOVERNANCE_PROFILE=production-rbac \
  ACCESS_GOVERNANCE_AUDIT_EVIDENCE=true \
  ACCESS_GOVERNANCE_BREAK_GLASS_REVIEW=true \
  IMPORT_REDACT=true
```

The planner writes:

- `reports/access-governance-plan.md`
- `reports/access-governance-values.yaml`

The generated values overlay keeps `accessGovernance.enabled=false`. It records
review intent for private overlays rather than granting access from public
configuration.

## Guardrails

- Do not print user names, group names, email addresses, tenant names, or
  identity provider URLs in public reports.
- Keep `global.serviceAccount.automountServiceAccountToken=false` unless a
  workload has a reviewed Kubernetes API use case.
- Prefer namespace-scoped Roles and RoleBindings over ClusterRoles.
- Keep break-glass credentials outside Git, time-box access, and require
  post-use review.
- Use OIDC or Keycloak group mapping only after MFA, audit retention, and
  ownership are documented.
