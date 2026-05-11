# Security Policy

Report security issues privately to the repository owners. Do not open public issues with credentials, exploit steps against live systems, kubeconfigs, or internal IP inventories.

Required controls before production use:

- Keep private data and confidential disclosure material out of the repository.
- Use documentation-only examples such as `example.com` domains and RFC 5737 IP ranges.
- Store secrets with SOPS, External Secrets, or Sealed Secrets.
- Do not commit plain Kubernetes Secret manifests or decrypted SOPS outputs.
- Keep the secret contract in `config/secrets.contract.yaml`; store actual values in a managed provider.
- Use registry authentication, release checksums, SBOM metadata, and artifact provenance controls.
- Keep GitHub Actions on reviewed refs; avoid floating `@main` and `@master` action refs.
- Enable TLS for ingress and internal service paths where required.
- Restrict `LoadBalancer` services to trusted networks.
- Rotate RKE2/K3s tokens after bootstrap.
- Keep audit logs and backups enabled for stateful services.
