# GitOps Delivery And Drift Control

## Article 18 Baseline

GitOps delivery is optional and disabled by default. The repository still works
in operator-managed mode through `make install-operators`, Helmfile, and Helm.
Article 18 adds a public-safe plan for moving to Argo CD or Flux when production
teams want continuous reconciliation and drift visibility.

The planner does not connect to Git, install Argo CD or Flux, mutate a cluster,
or print private repository details. It checks committed intent and writes a
safe values overlay template.

## Profiles

| Profile | Purpose | Controller | Drift behavior |
|---|---|---|---|
| `operator-managed` | Default Make/Helmfile/Helm flow | none | report only |
| `lab-argocd` | Lab drift visibility | Argo CD | warn |
| `production-argocd` | Production reconciliation | Argo CD | enforce |
| `production-flux` | Production reconciliation | Flux | enforce |

## One Command

```bash
make gitops-delivery-plan \
  GITOPS_DELIVERY_PROFILE=production-argocd \
  IMPORT_REDACT=true
```

The command writes:

- `reports/gitops-delivery-plan.md`
- `reports/gitops-delivery-values.yaml`

## Production Readiness

Before enabling production GitOps:

- Put real repo URLs, credentials, and overlays in private configuration.
- Enable branch protection and signed commits for the delivery branch.
- Keep `prune=false` until orphaned resources and shared ownership are reviewed.
- Run `make deploy-dry-run`, `make policy`, `make registry-promotion-plan`,
  `make runtime-hardening-plan`, and `make backup-plan`.
- Keep Helmfile/operator deployment as a documented break-glass path.

## Argo CD

The public example lives at
`deploy/argocd/urban-platform-infra-application.yaml`. It intentionally uses a
sanitized repo URL and keeps pruning disabled. Replace repository, revision, and
private values paths only in private overlays.

## Flux

Flux is modeled as a supported controller profile, but no private
`GitRepository`, `Kustomization`, or `HelmRelease` manifests are committed. Add
those in the private GitOps repository when Flux is selected.

## Public-Safe Rules

- Do not commit deploy keys, personal access tokens, kubeconfigs, or cluster
  credentials.
- Do not commit customer-specific repo URLs or private overlay paths.
- Do not enable destructive pruning until the resource ownership map is clear.
- Keep `gitOpsDelivery.enabled=false` in committed defaults.
