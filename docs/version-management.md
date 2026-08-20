# Version Management

The repository uses an approval-only update policy. Automatic patch, minor, and
major updates are disabled by design:

```yaml
updatePolicy:
  mode: approval-only
  autoPatch: false
  autoMinor: false
  autoMajor: false
  requireManualRequest: true
  requireApprovalForApply: true
  allowDirectProductionMutation: false
```

The policy and lifecycle catalog are in
[`config/version-policy.yaml`](../config/version-policy.yaml). It defines four
channels:

- `lts`: approved patch updates only.
- `stable`: approved patch or minor updates.
- `mainline`: approved patch, minor, or major updates.
- `edge`: explicitly approved preview updates.

The channel controls which update types are admissible. It never authorizes an
automatic change. EOL and obsolete lifecycle statuses block an apply operation;
unknown lifecycle data is a warning and must be reviewed against the component's
declared source.

## Workflow

1. Check the committed policy:

   ```bash
   make version-policy-check
   ```

2. Generate a read-only plan for a proposed update:

   ```bash
   make version-update-plan \
     VERSION_UPDATE_COMPONENT=dotnet \
     VERSION_UPDATE_TARGET=10.0.10 \
     VERSION_UPDATE_CHANNEL=lts
   ```

3. Create an explicit manual request. This produces evidence and does not
   change files or a cluster:

   ```bash
   make version-update-request \
     VERSION_UPDATE_MANUAL_REQUEST=true \
     VERSION_UPDATE_COMPONENT=dotnet \
     VERSION_UPDATE_TARGET=10.0.10 \
     VERSION_UPDATE_CHANNEL=lts \
     VERSION_UPDATE_CHANGE_TICKET=CHANGE-EXAMPLE \
     VERSION_UPDATE_ROLLBACK_PLAN=docs/change-management.md
   ```

   The same request can be generated from the manually triggered GitHub Actions
   workflow `version-update-request`. It only uploads review evidence.

4. After review and approval, apply the policy pin with every required gate:

   ```bash
   make version-update-apply \
     VERSION_UPDATE_MANUAL_REQUEST=true \
     VERSION_UPDATE_APPROVED=true \
     VERSION_UPDATE_EXECUTE=true \
     VERSION_UPDATE_COMPONENT=dotnet \
     VERSION_UPDATE_TARGET=10.0.10 \
     VERSION_UPDATE_CHANNEL=lts \
     VERSION_UPDATE_APPROVAL_REFERENCE=APPROVAL-EXAMPLE \
     VERSION_UPDATE_CHANGE_TICKET=CHANGE-EXAMPLE \
     VERSION_UPDATE_ROLLBACK_PLAN=docs/change-management.md
   ```

   This changes only the catalog pin in `config/version-policy.yaml`. It never
   mutates a live cluster. Review and update every listed `sourceFiles` entry in
   the same pull request, then run `make validate`, `make policy`, the relevant
   Helm renders, image policy checks, smoke tests, and release evidence gates.

## Automation Boundaries

Renovate and Dependabot may open dependency pull requests, but both are
configured without automerge. A pull request must pass CI, dependency review,
image policy, lifecycle review, and the project change-management process before
it is merged. Production deployment remains a separate operator or GitOps action
after the approved release is promoted.

The policy is intentionally not a live EOL feed. Each component has a
`lastReviewed` date and the configured review-age limit; stale metadata fails the
policy check. Lifecycle metadata must be reviewed on that cadence against each
component's public source, then the status or `eolDate` in
`config/version-policy.yaml` can be changed in a reviewed pull request. This
avoids silently trusting stale or unauthenticated release data.
