#!/usr/bin/env python3
"""Generate a public-safe GitOps delivery and drift-control plan."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - keeps the planner usable on lean operator hosts.
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "''", '""'}:
        return ""
    if value in {"[]", "[ ]"}:
        return []
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def next_child_is_list(lines: list[str], index: int, indent: int) -> bool:
    for raw_line in lines[index + 1 :]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        child_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if child_indent < indent:
            return False
        return raw_line.lstrip().startswith("- ")
    return False


def load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.split(" #", 1)[0].rstrip()
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        is_list_item = stripped.startswith("- ")
        while stack and (indent < stack[-1][0] or (indent == stack[-1][0] and not (is_list_item and isinstance(stack[-1][1], list)))):
            stack.pop()
        parent = stack[-1][1]
        if is_list_item:
            if isinstance(parent, list):
                parent.append(parse_scalar(stripped[2:].strip()))
            continue
        if ":" not in stripped or not isinstance(parent, dict):
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        raw_value = raw_value.strip()
        if raw_value == "":
            child: Any = [] if next_child_is_list(lines, index, indent) else {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)
    return root


def load_yaml_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise SystemExit(f"{path} must contain a mapping.")
        return loaded
    return load_simple_yaml(text)


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def select_profile(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        raise SystemExit("GitOps delivery config must contain a profiles mapping.")
    if profile_name not in profiles:
        choices = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown GitOps delivery profile `{profile_name}`. Available profiles: {choices}")
    profile = profiles[profile_name]
    if not isinstance(profile, dict):
        raise SystemExit(f"GitOps delivery profile `{profile_name}` must be a mapping.")
    return profile


def public_value(value: str, redact_sensitive: bool, placeholder: str) -> str:
    if not value:
        return ""
    return placeholder if redact_sensitive else value


def nested_get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def argo_repo_url(path: Path) -> str:
    if not path.exists():
        return ""
    data = load_yaml_file(path)
    return str(nested_get(data, ["spec", "source", "repoURL"], ""))


def profile_findings(profile_name: str, profile: dict[str, Any], repo_url: str, app_path: Path, helmfile_path: Path, kustomize_root: Path) -> list[str]:
    findings: list[str] = []
    enabled = bool_value(profile.get("enabled"), False)
    controller = str(profile.get("controller", "none"))
    if not enabled:
        findings.append(f"INFO: Profile `{profile_name}` is disabled; operator-managed delivery remains the default.")
    if controller == "argocd" and not app_path.exists():
        findings.append("ERROR: Argo CD profile selected but the public-safe Application template is missing.")
    if controller == "flux" and not kustomize_root.exists():
        findings.append("WARN: Flux profile selected but the kustomize root is missing.")
    if not helmfile_path.exists():
        findings.append("ERROR: Helmfile break-glass path is missing.")
    if bool_value(profile.get("requirePrivateRepo"), False) and (not repo_url or "example.com" in repo_url):
        findings.append("WARN: Production GitOps requires a private repo URL supplied outside public Git.")
    if bool_value(profile.get("requireSignedCommits"), False):
        findings.append("WARN: Signed commit enforcement must be configured in the private Git provider.")
    if bool_value(profile.get("requireProtectedBranch"), False):
        findings.append("WARN: Branch protection must be configured in the private Git provider.")
    if bool_value(profile.get("requirePrivateOverlays"), False):
        findings.append("WARN: Private values overlays must be stored outside the public-safe repo.")
    if bool_value(profile.get("prune"), False):
        findings.append("WARN: Pruning is enabled; confirm orphaned/shared resources before production sync.")
    return findings or ["OK: GitOps delivery settings are internally consistent."]


def result_from_findings(findings: list[str]) -> str:
    if any(item.startswith("ERROR:") for item in findings):
        return "FAIL"
    if any(item.startswith("WARN:") for item in findings):
        return "WARN"
    return "PASS"


def write_overrides(path: Path, profile_name: str, profile: dict[str, Any], repo_url: str, target_revision: str, values_path: str, redact_sensitive: bool) -> None:
    public_repo = public_value(repo_url, redact_sensitive, "https://git.example.invalid/platform/urban-platform-infra.git") or "https://git.example.invalid/platform/urban-platform-infra.git"
    lines = [
        "gitOpsDelivery:",
        "  enabled: false",
        f"  profile: {profile_name}",
        f"  controller: {profile.get('controller', 'none')}",
        f"  reconciliation: {profile.get('reconciliation', 'manual')}",
        f"  driftDetection: {profile.get('driftDetection', 'report-only')}",
        f"  prune: {str(bool_value(profile.get('prune'), False)).lower()}",
        f"  selfHeal: {str(bool_value(profile.get('selfHeal'), False)).lower()}",
        "  source:",
        f"    repoURL: {public_repo!r}",
        f"    targetRevision: {target_revision or 'main'}",
        "    path: helm/urban-platform-infra",
        "    valueFiles:",
        "      - values.yaml",
    ]
    if values_path:
        lines.append(f"      - {values_path}")
    lines.extend(
        [
            "  reports:",
            "    plan: reports/gitops-delivery-plan.md",
            "    overrides: reports/gitops-delivery-values.yaml",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_report(args: argparse.Namespace, config: dict[str, Any], profile: dict[str, Any], repo_url: str, findings: list[str]) -> str:
    controller_config = config.get("controller", {}) if isinstance(config.get("controller"), dict) else {}
    guardrails = config.get("guardrails", [])
    checks = controller_config.get("requiredChecks", [])
    if not isinstance(guardrails, list):
        guardrails = []
    if not isinstance(checks, list):
        checks = []
    result = result_from_findings(findings)
    public_repo = public_value(repo_url or args.repo_url, args.redact_sensitive, "<private-git-repo>") or "-"
    lines = [
        "# GitOps Delivery And Drift Control Plan",
        "",
        "This report is public-safe. It does not connect to Git providers, install GitOps controllers, mutate clusters, read deploy keys, or print private repository data.",
        "",
        f"- Profile: `{args.profile}`",
        f"- Enabled: `{str(bool_value(profile.get('enabled'), False)).lower()}`",
        f"- Controller: `{profile.get('controller', 'none')}`",
        f"- Reconciliation: `{profile.get('reconciliation', 'manual')}`",
        f"- Drift detection: `{profile.get('driftDetection', 'report-only')}`",
        f"- Prune: `{str(bool_value(profile.get('prune'), False)).lower()}`",
        f"- Self heal: `{str(bool_value(profile.get('selfHeal'), False)).lower()}`",
        f"- Repo URL: `{public_repo}`",
        f"- Target revision: `{args.target_revision}`",
        f"- Private values path: `{public_value(args.values_path, args.redact_sensitive, '<private-values-overlay>') or '-'}`",
        f"- Argo CD application: `{controller_config.get('argocdApplication', '-')}`",
        f"- Helmfile break-glass path: `{controller_config.get('helmfile', '-')}`",
        f"- Result: `{result}`",
        "",
        "## Required Checks",
        "",
    ]
    for check in checks:
        lines.append(f"- {check}")
    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- {finding}")
    lines.extend(["", "## Guardrails", ""])
    for guardrail in guardrails:
        lines.append(f"- {guardrail}")
    lines.extend(
        [
            "",
            "## Recommended Sequence",
            "",
            "1. Keep operator-managed deployment as the baseline.",
            "2. Enable `lab-argocd` for drift visibility without pruning.",
            "3. Move private repo URLs and overlays into the private GitOps repository.",
            "4. Require signed commits and protected branches before production sync.",
            "5. Enable production reconciliation only after registry, runtime, backup, and restore plans are ready.",
            "",
            "## Example Commands",
            "",
            "```bash",
            "make gitops-delivery-plan GITOPS_DELIVERY_PROFILE=lab-argocd IMPORT_REDACT=true",
            "make gitops-delivery-plan GITOPS_DELIVERY_PROFILE=production-argocd IMPORT_REDACT=true",
            "helmfile -f deploy/helmfile.yaml.gotmpl sync",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a public-safe GitOps delivery and drift-control plan.")
    parser.add_argument("--config", default="config/gitops-delivery.yaml")
    parser.add_argument("--profile", default="")
    parser.add_argument("--repo-url", default="")
    parser.add_argument("--target-revision", default="main")
    parser.add_argument("--values-path", default="")
    parser.add_argument("--output", default="reports/gitops-delivery-plan.md")
    parser.add_argument("--overrides", default="reports/gitops-delivery-values.yaml")
    parser.add_argument("--redact-sensitive", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    output_path = Path(args.output)
    overrides_path = Path(args.overrides)
    if not config_path.is_absolute():
        config_path = (ROOT / config_path).resolve()
    if not output_path.is_absolute():
        output_path = (ROOT / output_path).resolve()
    if not overrides_path.is_absolute():
        overrides_path = (ROOT / overrides_path).resolve()

    config = load_yaml_file(config_path)
    args.profile = args.profile or str(config.get("defaultProfile", "operator-managed"))
    profile = select_profile(config, args.profile)
    controller = config.get("controller", {}) if isinstance(config.get("controller"), dict) else {}
    app_path = ROOT / str(controller.get("argocdApplication", "deploy/argocd/urban-platform-infra-application.yaml"))
    helmfile_path = ROOT / str(controller.get("helmfile", "deploy/helmfile.yaml.gotmpl"))
    kustomize_root = ROOT / str(controller.get("kustomizeRoot", "deploy/kustomize"))
    repo_url = args.repo_url or argo_repo_url(app_path)
    findings = profile_findings(args.profile, profile, repo_url, app_path, helmfile_path, kustomize_root)
    write_overrides(overrides_path, args.profile, profile, repo_url, args.target_revision, args.values_path, args.redact_sensitive)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_report(args, config, profile, repo_url, findings), encoding="utf-8")
    print(f"GitOps delivery plan written: {output_path}")
    print(f"GitOps delivery values overlay written: {overrides_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
