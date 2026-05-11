# Repository Setup: GitHub, GitLab, and private GitLab

This project is ready for GitHub and GitLab. It includes:

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `.gitlab-ci.yml`
- `CODEOWNERS`
- `SECURITY.md`
- `CONTRIBUTING.md`
- Dependabot updates for GitHub Actions and Python CI dependencies
- release evidence with checksums, SPDX SBOM metadata, and GitHub artifact attestations
- scripts for creating and pushing remotes

## Local repository

```bash
scripts/repo/init-local-git.sh
```

## GitHub private repository

Use GitHub CLI:

```bash
gh auth login
GITHUB_OWNER=my-org GITHUB_VISIBILITY=private scripts/repo/create-github-repo.sh
```

Or set `GH_TOKEN` and use the fallback API path.

## GitLab private repository

```bash
export GITLAB_TOKEN=glpat_xxx
export GITLAB_URL=https://gitlab.com
export GITLAB_NAMESPACE_ID=123456     # optional group namespace
export GITLAB_VISIBILITY=private
scripts/repo/create-gitlab-repo.sh
```

## Push to all configured remotes

```bash
scripts/repo/push-all-remotes.sh
```
