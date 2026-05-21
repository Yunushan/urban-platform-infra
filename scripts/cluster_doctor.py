#!/usr/bin/env python3
"""Public-safe RKE2 cluster doctor and guarded repair wrapper."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_IP_RE = re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b")
URL_HOST_RE = re.compile(r"https://([^:/\s]+)(?::([0-9]+))?")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    recommendation: str = ""


@dataclass(frozen=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str
    duration: float


def csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def alias_map(values: list[str], prefix: str) -> dict[str, str]:
    return {value: f"{prefix}-{index:02d}" for index, value in enumerate(values, start=1)}


def redact(text: str, aliases: dict[str, str], enabled: bool = True) -> str:
    if not enabled:
        return text
    redacted = text
    for real, alias in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        redacted = redacted.replace(real, alias)
    redacted = PRIVATE_IP_RE.sub("<private-ip>", redacted)
    redacted = URL_HOST_RE.sub(lambda match: f"https://<endpoint>{':' + match.group(2) if match.group(2) else ''}", redacted)
    return redacted


def run(command: list[str], timeout: int = 20, env: dict[str, str] | None = None, stdin: str | None = None) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip(), time.monotonic() - started)
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc), time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(124, stdout.strip(), (stderr.strip() or f"timed out after {timeout}s"), time.monotonic() - started)


def ssh_base(args: argparse.Namespace) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.ssh_timeout}",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
    ]
    if args.ssh_key:
        command.extend(["-i", args.ssh_key])
    return command


def tcp_check(host: str, port: int, timeout: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def local_kubectl(args: argparse.Namespace, subcommand: list[str], timeout: int = 20) -> CommandResult:
    command = ["kubectl"]
    if args.kubeconfig:
        command.extend(["--kubeconfig", args.kubeconfig])
    command.extend(subcommand)
    return run(command, timeout=timeout)


def local_checks(args: argparse.Namespace, aliases: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    # Diagnostic token for repository validation: local binary `kubectl`.
    for binary in ["kubectl", "ssh"]:
        checks.append(
            Check(
                f"local binary `{binary}`",
                "OK" if shutil.which(binary) else "WARN",
                "available" if shutil.which(binary) else "not found in PATH",
                f"Install `{binary}` on the operator host." if not shutil.which(binary) else "",
            )
        )

    kubeconfig = Path(args.kubeconfig).expanduser() if args.kubeconfig else None
    if kubeconfig:
        checks.append(
            Check(
                "operator kubeconfig file",
                "OK" if kubeconfig.exists() and kubeconfig.stat().st_size > 0 else "WARN",
                "<kubeconfig>" if args.redact_sensitive else str(kubeconfig),
                "Run `make operator-kubeconfig` or `make cluster-repair`." if not kubeconfig.exists() else "",
            )
        )
    if shutil.which("kubectl"):
        readyz = local_kubectl(args, ["get", "--raw=/readyz", "--request-timeout=10s"], timeout=15)
        checks.append(
            Check(
                "operator Kubernetes `/readyz`",
                "OK" if readyz.code == 0 else "ERROR",
                "ready" if readyz.code == 0 else redact(readyz.stderr or readyz.stdout or "not ready", aliases, args.redact_sensitive),
                "Check API endpoint, VIP, HAProxy, and RKE2 server health." if readyz.code != 0 else "",
            )
        )
        version = local_kubectl(args, ["version", "--request-timeout=10s"], timeout=15)
        checks.append(
            Check(
                "operator Kubernetes version call",
                "OK" if version.code == 0 else "WARN",
                "answered" if version.code == 0 else redact(version.stderr or version.stdout or "not answered", aliases, args.redact_sensitive),
                "If `/readyz` fails too, repair the operator kubeconfig or API path." if version.code != 0 else "",
            )
        )
    return checks


REMOTE_DIAGNOSTICS = r"""
svc_state() {
  systemctl is-active "$1" 2>/dev/null || echo unknown
}
echo "service:rke2-server:$(svc_state rke2-server)"
echo "service:rke2-agent:$(svc_state rke2-agent)"
echo "service:haproxy:$(svc_state haproxy)"
echo "service:keepalived:$(svc_state keepalived)"
if command -v ss >/dev/null 2>&1; then
  for port in 6443 7443 9345 9346 80 443; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\])${port}$"; then
      echo "socket:${port}:listening"
    else
      echo "socket:${port}:closed"
    fi
  done
fi
if command -v haproxy >/dev/null 2>&1 && [ -r /etc/haproxy/haproxy.cfg ]; then
  if haproxy -c -f /etc/haproxy/haproxy.cfg >/dev/null 2>&1; then
    echo "haproxy-config:ok"
  else
    echo "haproxy-config:fail"
  fi
else
  echo "haproxy-config:missing"
fi
if command -v keepalived >/dev/null 2>&1 && [ -r /etc/keepalived/keepalived.conf ]; then
  if keepalived -t -f /etc/keepalived/keepalived.conf >/dev/null 2>&1; then
    echo "keepalived-config:ok"
  else
    echo "keepalived-config:fail"
  fi
else
  echo "keepalived-config:missing"
fi
if [ -x /var/lib/rancher/rke2/bin/kubectl ] && [ -r /etc/rancher/rke2/rke2.yaml ]; then
  if timeout 10 /var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz >/dev/null 2>&1; then
    echo "local-readyz:ok"
  else
    echo "local-readyz:fail"
  fi
else
  echo "local-readyz:missing"
fi
if command -v rke2 >/dev/null 2>&1; then
  rke2 --version 2>/dev/null | sed -n '1s/^/rke2-version:/p'
elif [ -x /usr/local/bin/rke2 ]; then
  /usr/local/bin/rke2 --version 2>/dev/null | sed -n '1s/^/rke2-version:/p'
elif [ -x /var/lib/rancher/rke2/bin/rke2 ]; then
  /var/lib/rancher/rke2/bin/rke2 --version 2>/dev/null | sed -n '1s/^/rke2-version:/p'
else
  echo "rke2-version:missing"
fi
if command -v journalctl >/dev/null 2>&1; then
  echo "journal:haproxy-errors:$(journalctl -u haproxy -n 80 --no-pager 2>/dev/null | grep -Eci 'dumped core|alert|fatal|panic|error|failed|aborted' || true)"
  echo "journal:rke2-errors:$(journalctl -u rke2-server -n 120 --no-pager 2>/dev/null | grep -Eci 'fatal|panic|error|failed|timeout|context deadline' || true)"
else
  echo "journal:haproxy-errors:unknown"
  echo "journal:rke2-errors:unknown"
fi
"""


def parse_remote(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.strip().split(":", 2)
        if len(parts) == 3:
            parsed[f"{parts[0]}:{parts[1]}"] = parts[2]
        elif len(parts) == 2:
            parsed[parts[0]] = parts[1]
    return parsed


def remote_checks(args: argparse.Namespace, nodes: list[str], aliases: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    if not nodes:
        return [
            Check(
                "RKE2 node list",
                "WARN",
                "no nodes configured",
                "Set CLUSTER_DOCTOR_NODES or MIGRATION_RKE2_NODES.",
            )
        ]
    if not shutil.which("ssh"):
        return [Check("remote diagnostics", "WARN", "`ssh` is not available", "Install OpenSSH client on the operator host.")]

    for node in nodes:
        node_label = aliases.get(node, node)
        ssh_prefix = ssh_base(args) + [f"{args.ssh_user}@{node}"]
        ssh_ok = run(ssh_prefix + ["true"], timeout=args.ssh_timeout + 5)
        checks.append(
            Check(
                f"{node_label} SSH",
                "OK" if ssh_ok.code == 0 else "ERROR",
                "reachable" if ssh_ok.code == 0 else redact(ssh_ok.stderr or ssh_ok.stdout or "unreachable", aliases, args.redact_sensitive),
                "Verify CLUSTER_DOCTOR_SSH_USER, MIGRATION_SSH_USER, SSH keys, and firewall reachability." if ssh_ok.code != 0 else "",
            )
        )
        if ssh_ok.code != 0:
            continue
        sudo_ok = run(ssh_prefix + ["sudo", "-n", "true"], timeout=args.ssh_timeout + 5)
        checks.append(
            Check(
                f"{node_label} passwordless sudo",
                "OK" if sudo_ok.code == 0 else "WARN",
                "available" if sudo_ok.code == 0 else "not available",
                "Enable passwordless sudo or set MIGRATION_BECOME_PASSWORD_FILE for repair/import workflows." if sudo_ok.code != 0 else "",
            )
        )
        diagnostic_command = ssh_prefix + ["sudo", "-n", "sh", "-s"]
        diagnostic = run(diagnostic_command, timeout=args.remote_timeout, env=None, stdin=REMOTE_DIAGNOSTICS)
        if diagnostic.code == 0:
            parsed = parse_remote(diagnostic.stdout)
        else:
            parsed = {}
            diagnostic = run(ssh_prefix + ["sh", "-s"], timeout=args.remote_timeout, env=None, stdin=REMOTE_DIAGNOSTICS)
            parsed = parse_remote(diagnostic.stdout) if diagnostic.code == 0 else {}
        if not parsed:
            checks.append(
                Check(
                    f"{node_label} remote diagnostics",
                    "WARN",
                    redact(diagnostic.stderr or diagnostic.stdout or "diagnostics unavailable", aliases, args.redact_sensitive),
                    "Remote service checks need sudo access on RKE2 nodes.",
                )
            )
            continue

        for service in ["rke2-server", "rke2-agent", "haproxy", "keepalived"]:
            state = parsed.get(f"service:{service}", "unknown")
            status = "OK" if state == "active" or (service == "rke2-agent" and state in {"inactive", "unknown"}) else "WARN"
            recommendation = ""
            if service == "haproxy" and state != "active":
                recommendation = "Run `make cluster-repair` or bootstrap HAProxy/Keepalived from the inventory."
            if service == "keepalived" and state != "active":
                recommendation = "Check Keepalived interface, VIP, and auth settings."
            if service == "rke2-server" and state != "active":
                recommendation = "Inspect RKE2 journal and run guarded repair only when quorum is understood."
            checks.append(Check(f"{node_label} service `{service}`", status, state, recommendation))

        for port in ["6443", "7443", "9345", "9346", "80", "443"]:
            state = parsed.get(f"socket:{port}", "unknown")
            checks.append(
                Check(
                    f"{node_label} local port {port}",
                    "OK" if state == "listening" or (port in {"7443", "9346"} and state in {"closed", "unknown"}) else "WARN",
                    state,
                    "Check RKE2 or HAProxy listeners." if port in {"6443", "9345"} and state != "listening" else "",
                )
            )

        for item, label in [
            ("haproxy-config", "HAProxy config"),
            ("keepalived-config", "Keepalived config"),
            ("local-readyz", "local RKE2 `/readyz`"),
        ]:
            state = parsed.get(item, "unknown")
            checks.append(
                Check(
                    f"{node_label} {label}",
                    "OK" if state == "ok" else "WARN",
                    state,
                    "Re-render/reconcile the service config with `make cluster-repair`." if state == "fail" else "",
                )
            )

        for journal_key, label in [("journal:haproxy-errors", "recent HAProxy error hints"), ("journal:rke2-errors", "recent RKE2 error hints")]:
            raw_count = parsed.get(journal_key, "unknown")
            status = "OK"
            if raw_count not in {"0", "unknown"}:
                status = "WARN"
            checks.append(
                Check(
                    f"{node_label} {label}",
                    status,
                    raw_count,
                    "Inspect journal details privately on the node; do not paste private logs into public reports." if status == "WARN" else "",
                )
            )
    return checks


def endpoint_checks(args: argparse.Namespace, nodes: list[str], aliases: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    endpoints: list[tuple[str, int, str]] = []
    if args.cluster_vip:
        endpoints.append((args.cluster_vip, args.api_port, "cluster VIP API"))
    for node in nodes:
        endpoints.append((node, 6443, "node API"))
        endpoints.append((node, 9345, "node RKE2 registration"))

    seen: set[tuple[str, int]] = set()
    for host, port, label in endpoints:
        if (host, port) in seen:
            continue
        seen.add((host, port))
        visible = aliases.get(host, "cluster-vip" if host == args.cluster_vip else host)
        ok = tcp_check(host, port, args.tcp_timeout)
        checks.append(
            Check(
                f"{visible} {label} TCP {port}",
                "OK" if ok else "WARN",
                "reachable" if ok else "not reachable from operator",
                "Check firewall, HAProxy listener, Keepalived VIP ownership, or node reachability." if not ok else "",
            )
        )
    return checks


def summarize(checks: list[Check]) -> tuple[int, int, int]:
    errors = sum(1 for check in checks if check.status == "ERROR")
    warnings = sum(1 for check in checks if check.status == "WARN")
    ok = sum(1 for check in checks if check.status == "OK")
    return ok, warnings, errors


def render_report(args: argparse.Namespace, nodes: list[str], aliases: dict[str, str], checks: list[Check], repair_result: CommandResult | None) -> str:
    ok, warnings, errors = summarize(checks)
    lines = [
        "# Cluster Doctor Report",
        "",
        "This report is public-safe. It redacts private IPs, kubeconfig paths, credentials, and raw journal output. Keep full command logs on the operator machine only.",
        "",
        f"- Engine: `{args.engine}`",
        f"- Environment: `{args.environment}`",
        f"- Nodes configured: `{len(nodes)}`",
        f"- Cluster VIP configured: `{'yes' if args.cluster_vip else 'no'}`",
        f"- API VIP port: `{args.api_port}`",
        f"- Kubeconfig: `{('<kubeconfig>' if args.kubeconfig else 'default')}`",
        f"- Repair requested: `{str(args.repair).lower()}`",
        f"- Result: `{'FAIL' if errors else ('WARN' if warnings else 'PASS')}`",
        f"- Summary: `{errors}` error(s), `{warnings}` warning(s), `{ok}` ok item(s)",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail | Recommendation |",
        "|---|---|---|---|",
    ]
    for check in checks:
        detail = redact(check.detail, aliases, args.redact_sensitive).replace("|", "\\|")
        recommendation = redact(check.recommendation, aliases, args.redact_sensitive).replace("|", "\\|")
        lines.append(f"| {check.name} | `{check.status}` | {detail or '-'} | {recommendation or '-'} |")

    lines.extend(
        [
            "",
            "## Operator Next Steps",
            "",
            "- If SSH or sudo checks fail, fix access first; RKE2 repair cannot safely run without node access.",
            "- If local node API ports are listening but `/readyz` fails, inspect RKE2 journals privately and preserve etcd quorum.",
            "- If the VIP API is down but node APIs work, reconcile HAProxy/Keepalived and firewall rules.",
            "- If HAProxy config validates but the service still crashes, update or reinstall the HAProxy package and review TLS/backend health privately.",
            "- Run `make cluster-repair` only when you want the guarded kubeconfig/RKE2 repair path to execute.",
            "",
        ]
    )
    if repair_result is not None:
        repair_state = "succeeded" if repair_result.code == 0 else "failed"
        lines.extend(
            [
                "## Repair Attempt",
                "",
                f"- Status: `{repair_state}`",
                f"- Exit code: `{repair_result.code}`",
                f"- Duration: `{repair_result.duration:.1f}s`",
                f"- Last output: `{redact((repair_result.stdout or repair_result.stderr).splitlines()[-1] if (repair_result.stdout or repair_result.stderr) else '-', aliases, args.redact_sensitive)}`",
                "",
            ]
        )
    return "\n".join(lines)


def run_repair(args: argparse.Namespace) -> CommandResult:
    env = os.environ.copy()
    env.update(
        {
            "ENV": args.environment,
            "ENGINE": args.engine,
            "INVENTORY": args.inventory,
            "OPERATOR_KUBECONFIG": args.kubeconfig,
            "MIGRATION_RKE2_NODES": ",".join(args.nodes),
            "MIGRATION_SSH_USER": args.ssh_user,
            "MIGRATION_SSH_KEY": args.ssh_key,
            "MIGRATION_CLUSTER_VIP": args.cluster_vip,
            "MIGRATION_KUBERNETES_API_VIP_PORT": str(args.api_port),
            "MIGRATION_AUTO_REPAIR_CLUSTER": "true",
        }
    )
    script = ROOT / "scripts/tools/ensure-kubeconfig.sh"
    return run(["bash", str(script)], timeout=args.repair_timeout, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose RKE2 API/VIP/kubeconfig readiness and optionally run guarded repair.")
    parser.add_argument("--nodes", default=os.environ.get("CLUSTER_DOCTOR_NODES", os.environ.get("MIGRATION_RKE2_NODES", "")))
    parser.add_argument("--cluster-vip", default=os.environ.get("CLUSTER_DOCTOR_CLUSTER_VIP", os.environ.get("MIGRATION_CLUSTER_VIP", "")))
    parser.add_argument("--api-port", type=int, default=int(os.environ.get("CLUSTER_DOCTOR_API_PORT", os.environ.get("MIGRATION_KUBERNETES_API_VIP_PORT", "7443") or "7443")))
    parser.add_argument("--ssh-user", default=os.environ.get("CLUSTER_DOCTOR_SSH_USER", os.environ.get("MIGRATION_SSH_USER", "root")))
    parser.add_argument("--ssh-key", default=os.environ.get("CLUSTER_DOCTOR_SSH_KEY", os.environ.get("MIGRATION_SSH_KEY", "")))
    parser.add_argument("--kubeconfig", default=os.environ.get("CLUSTER_DOCTOR_KUBECONFIG", os.environ.get("OPERATOR_KUBECONFIG", os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config")))))
    parser.add_argument("--inventory", default=os.environ.get("INVENTORY", "inventories/prod/hosts.yml"))
    parser.add_argument("--environment", default=os.environ.get("ENV", "prod"))
    parser.add_argument("--engine", default=os.environ.get("ENGINE", "rke2"))
    parser.add_argument("--output", default=os.environ.get("CLUSTER_DOCTOR_OUTPUT", "reports/cluster-doctor.md"))
    parser.add_argument("--tcp-timeout", type=int, default=int(os.environ.get("CLUSTER_DOCTOR_TCP_TIMEOUT", "3")))
    parser.add_argument("--ssh-timeout", type=int, default=int(os.environ.get("CLUSTER_DOCTOR_SSH_TIMEOUT", "8")))
    parser.add_argument("--remote-timeout", type=int, default=int(os.environ.get("CLUSTER_DOCTOR_REMOTE_TIMEOUT", "20")))
    parser.add_argument("--repair-timeout", type=int, default=int(os.environ.get("CLUSTER_DOCTOR_REPAIR_TIMEOUT", "1800")))
    parser.add_argument("--repair", action="store_true", default=os.environ.get("CLUSTER_DOCTOR_REPAIR", "false").lower() in {"true", "1", "yes"})
    parser.add_argument("--redact-sensitive", action="store_true", default=os.environ.get("CLUSTER_DOCTOR_REDACT", os.environ.get("IMPORT_REDACT", "true")).lower() not in {"false", "0", "no"})
    args = parser.parse_args()
    args.nodes = csv(args.nodes)

    aliases = alias_map(args.nodes, "node")
    if args.cluster_vip:
        aliases[args.cluster_vip] = "cluster-vip"
    checks: list[Check] = []
    checks.extend(local_checks(args, aliases))
    checks.extend(endpoint_checks(args, args.nodes, aliases))
    checks.extend(remote_checks(args, args.nodes, aliases))

    repair_result = run_repair(args) if args.repair else None
    if repair_result is not None:
        post_repair_readyz = local_kubectl(args, ["get", "--raw=/readyz", "--request-timeout=10s"], timeout=15) if shutil.which("kubectl") else CommandResult(127, "", "kubectl missing", 0)
        checks.append(
            Check(
                "post-repair operator Kubernetes `/readyz`",
                "OK" if post_repair_readyz.code == 0 else "ERROR",
                "ready" if post_repair_readyz.code == 0 else redact(post_repair_readyz.stderr or post_repair_readyz.stdout or "not ready", aliases, args.redact_sensitive),
                "Review the repair attempt output and private node journals." if post_repair_readyz.code != 0 else "",
            )
        )

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(args, args.nodes, aliases, checks, repair_result), encoding="utf-8")
    print(f"Cluster doctor report written: {args.output}")
    if repair_result is not None and repair_result.code != 0:
        return repair_result.code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
