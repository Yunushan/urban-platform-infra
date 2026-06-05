#!/usr/bin/env python3
"""Read-only Docker Compose project compatibility checker.

The checker inventories an external Compose project before it is migrated into
the platform Helm chart. It does not copy files, deploy manifests, or mutate the
source project.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by operator setup.
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUES = ROOT / "helm/urban-platform-infra/values.yaml"
DEFAULT_IMAGE_POLICY = ROOT / "config/image-policy.yaml"
COMPOSE_SUFFIXES = {".yaml", ".yml"}
SKIP_DIRS = {
    ".git",
    ".terraform",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "vendor",
    "venv",
}
MUTABLE_TAGS = {"latest", "latest-pg16", "latest-pg17", "latest-pg18"}
POSTGRES_COMPATIBLE_SELECTIONS = {
    "postgresql",
    "postgres",
    "postgis",
    "timescaledb",
    "cloudnative-pg",
    "cnpg",
}
POSTGRES_FAMILY_KINDS = {"postgresql", "postgis", "timescaledb"}
OPTIONAL_DATABASE_KINDS = {"mysql", "mariadb", "microsoft-sql-server", "mongodb", "sqlite"}
DATABASE_KINDS = POSTGRES_FAMILY_KINDS | OPTIONAL_DATABASE_KINDS
DATABASE_PROFILE_ALIASES = {
    "mysql": {"mysql", "vitess"},
    "mariadb": {"mariadb"},
    "microsoft-sql-server": {"microsoft-sql-server", "mssql", "sql-server", "sqlserver"},
    "mongodb": {"mongodb", "mongo"},
    "sqlite": {"sqlite"},
}
PUBLIC_RUNTIME_KINDS = {
    "apache-httpd",
    "apache-tomcat",
    "elasticsearch",
    "kafka",
    "kibana",
    "logstash",
    "mariadb",
    "microsoft-sql-server",
    "mongodb",
    "mysql",
    "nginx",
    "postgis",
    "postgresql",
    "redis",
    "sqlite",
    "timescaledb",
    "traefik",
    "zookeeper",
}
SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|client[_-]?secret|access[_-]?key)",
    re.IGNORECASE,
)
VARIABLE_VALUE_RE = re.compile(r"^(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*)$")
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])/(?:home|root|srv|opt|etc|var/lib|mnt|media|data)/[^`\s,)]*")
RELATIVE_PATH_RE = re.compile(r"(?<![\w.-])(?:\.\./|\./)[^`\s,)]*")
SQLITE_FILE_RE = re.compile(r"\.(?:sqlite|sqlite3|db)(?:$|[.:?])", re.IGNORECASE)


@dataclass
class Finding:
    severity: str
    file: str
    service: str
    message: str
    recommendation: str


@dataclass
class ImageRef:
    raw: str
    repository: str
    tag: str | None = None
    digest: str | None = None
    variable: bool = False

    @property
    def canonical_repository(self) -> str:
        repository = self.repository.lower()
        for prefix in ("docker.io/library/", "index.docker.io/library/", "library/"):
            if repository.startswith(prefix):
                return repository[len(prefix) :]
        if repository.startswith("docker.io/"):
            return repository[len("docker.io/") :]
        return repository

    @property
    def display(self) -> str:
        if self.digest:
            return f"{self.repository}@{self.digest}"
        if self.tag:
            return f"{self.repository}:{self.tag}"
        return self.repository


@dataclass
class PortRef:
    published: str | None
    target: str | None
    protocol: str = "tcp"

    @property
    def display(self) -> str:
        if self.published and self.target:
            return f"{self.published}->{self.target}/{self.protocol}"
        if self.target:
            return f"{self.target}/{self.protocol}"
        return "unknown"


@dataclass
class ServiceRecord:
    file: str
    name: str
    image: ImageRef | None
    kind: str
    ports: list[PortRef] = field(default_factory=list)
    build_only: bool = False


class ReportRedactor:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.file_ids: dict[str, str] = {}
        self.service_ids: dict[str, str] = {}

    def _stable_id(self, prefix: str, value: str, cache: dict[str, str]) -> str:
        if value in {"", "-"}:
            return value
        if value not in cache:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
            cache[value] = f"{prefix}-{len(cache) + 1:03d}-{digest}"
        return cache[value]

    def project_path(self, value: Path) -> str:
        if not self.enabled:
            return str(value)
        return "/path/to/compose-project"

    def file(self, value: str) -> str:
        if not self.enabled:
            return value
        return self._stable_id("compose-file", value, self.file_ids)

    def service(self, value: str) -> str:
        if not self.enabled:
            return value
        return self._stable_id("service", value, self.service_ids)

    def image(self, record: ServiceRecord) -> str:
        if record.image is None:
            return "build-only"
        if not self.enabled or record.kind in PUBLIC_RUNTIME_KINDS:
            return record.image.display
        return "<application-image>"

    def text(self, value: str) -> str:
        if not self.enabled:
            return value
        value = ABSOLUTE_PATH_RE.sub("<host-path>", value)
        value = RELATIVE_PATH_RE.sub("<relative-path>", value)
        value = re.sub(r"Image `[^`]+` has no explicit tag", "Image `<image>` has no explicit tag", value)
        value = re.sub(r"Image `[^`]+` uses mutable tag", "Image `<image>` uses mutable tag", value)
        value = re.sub(r"Image reference is variable-driven: `[^`]+`", "Image reference is variable-driven: `<image-variable>`", value)
        return value


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Install it with `python3 -m pip install PyYAML`.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def looks_like_compose_file(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in COMPOSE_SUFFIXES:
        return False
    if name in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}:
        return True
    return name.startswith("docker-compose.") or "compose" in name


def find_compose_files(project_path: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_path.rglob("*"):
        try:
            relative_parts = path.relative_to(project_path).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if path.is_file() and looks_like_compose_file(path):
            files.append(path)
    return sorted(files)


def parse_image_ref(raw: Any) -> ImageRef | None:
    if raw is None:
        return None
    image = str(raw).strip()
    if not image:
        return None
    if "${" in image or image.startswith("$"):
        return ImageRef(raw=image, repository=image, variable=True)
    digest = None
    base = image
    if "@" in image:
        base, digest = image.split("@", 1)
    tag = None
    repository = base
    last_segment = base.rsplit("/", 1)[-1]
    if ":" in last_segment:
        repository, tag = base.rsplit(":", 1)
    return ImageRef(raw=image, repository=repository, tag=tag, digest=digest)


def image_kind(image: ImageRef | None) -> str:
    if image is None:
        return "build"
    repository = image.canonical_repository
    base = repository.rsplit("/", 1)[-1]
    if repository in {"nginx", "nginxinc/nginx-unprivileged"} or base == "nginx-unprivileged":
        return "nginx"
    if repository == "httpd" or base == "httpd":
        return "apache-httpd"
    if repository == "tomcat" or base == "tomcat":
        return "apache-tomcat"
    if repository == "traefik" or base == "traefik":
        return "traefik"
    if repository == "postgres" or base == "postgres":
        return "postgresql"
    if repository == "postgis/postgis" or base == "postgis":
        return "postgis"
    if "timescaledb" in repository:
        return "timescaledb"
    if repository == "mysql" or base == "mysql":
        return "mysql"
    if repository == "mariadb" or base == "mariadb":
        return "mariadb"
    if repository in {"mongo", "mongodb/mongodb-community-server"} or base in {"mongo", "mongod"}:
        return "mongodb"
    if repository in {"mcr.microsoft.com/mssql/server", "mcr.microsoft.com/azure-sql-edge"}:
        return "microsoft-sql-server"
    if "mssql" in repository or "sqlserver" in repository:
        return "microsoft-sql-server"
    if repository == "redis" or base == "redis":
        return "redis"
    if "kafka" in repository:
        return "kafka"
    if "zookeeper" in repository:
        return "zookeeper"
    if "elasticsearch" in repository:
        return "elasticsearch"
    if "kibana" in repository:
        return "kibana"
    if "logstash" in repository:
        return "logstash"
    return "application"


def parse_port_ref(entry: Any) -> PortRef:
    if isinstance(entry, int):
        return PortRef(published=None, target=str(entry))
    if isinstance(entry, dict):
        published = entry.get("published")
        target = entry.get("target")
        protocol = str(entry.get("protocol", "tcp"))
        return PortRef(
            published=str(published) if published is not None else None,
            target=str(target) if target is not None else None,
            protocol=protocol,
        )
    spec = str(entry).strip()
    protocol = "tcp"
    if "/" in spec:
        spec, protocol = spec.rsplit("/", 1)
    parts = spec.split(":")
    if len(parts) == 1:
        return PortRef(published=None, target=parts[0], protocol=protocol)
    if len(parts) == 2:
        return PortRef(published=parts[0], target=parts[1], protocol=protocol)
    return PortRef(published=parts[-2], target=parts[-1], protocol=protocol)


def normalize_approved_images(policy_path: Path) -> dict[str, set[str]]:
    data = load_yaml(policy_path)
    approved: dict[str, set[str]] = {}
    for item in data.get("policy", {}).get("approvedRuntimeImages", []):
        repository = str(item.get("repository", "")).lower()
        tag = str(item.get("tag", ""))
        if repository and tag:
            approved.setdefault(repository, set()).add(tag)
    return approved


def expected_webserver_image(values: dict[str, Any], provider: str) -> str | None:
    webservers = values.get("webserver", {}).get("providers", {})
    image = webservers.get(provider, {}).get("image", {})
    repository = image.get("repository")
    tag = image.get("tag")
    if repository and tag:
        return f"{repository}:{tag}"
    return None


def database_target_images(values: dict[str, Any]) -> list[str]:
    targets: set[str] = set()
    database_values = values.get("databases", {})
    for instance in database_values.get("instances", {}).values():
        image = instance.get("image", {}) if isinstance(instance, dict) else {}
        repository = image.get("repository")
        tag = image.get("tag")
        if repository and tag:
            targets.add(f"{repository}:{tag}")
    for catalog in database_values.get("imageCatalogs", {}).values():
        if not isinstance(catalog, dict):
            continue
        for item in catalog.get("images", []):
            image = item.get("image", {}) if isinstance(item, dict) else {}
            repository = image.get("repository")
            tag = image.get("tag")
            if repository and tag:
                targets.add(f"{repository}:{tag}")
    return sorted(targets)


def detect_postgres_major(image: ImageRef) -> int | None:
    tag = image.tag or ""
    pg_match = re.search(r"pg(\d{1,2})", tag)
    if pg_match:
        return int(pg_match.group(1))
    leading_match = re.match(r"^(\d{1,2})(?:[.\-]|$)", tag)
    if leading_match:
        return int(leading_match.group(1))
    return None


def environment_entries(environment: Any) -> list[tuple[str, str | None]]:
    if isinstance(environment, dict):
        return [(str(key), None if value is None else str(value)) for key, value in environment.items()]
    if isinstance(environment, list):
        entries: list[tuple[str, str | None]] = []
        for item in environment:
            text = str(item)
            if "=" in text:
                key, value = text.split("=", 1)
                entries.append((key, value))
            else:
                entries.append((text, None))
        return entries
    return []


def selected_database_matches_kind(kind: str, selected_database: str) -> bool:
    selected = selected_database.lower().replace("_", "-")
    if kind in POSTGRES_FAMILY_KINDS:
        return selected in POSTGRES_COMPATIBLE_SELECTIONS
    return selected in DATABASE_PROFILE_ALIASES.get(kind, {kind})


def service_uses_sqlite_files(service: dict[str, Any]) -> bool:
    for key, value in environment_entries(service.get("environment")):
        key_text = key.lower()
        value_text = value or ""
        if "sqlite" in key_text or SQLITE_FILE_RE.search(value_text):
            return True
    for mount in service.get("volumes") or []:
        if isinstance(mount, dict):
            fields = [mount.get("source"), mount.get("target")]
        else:
            fields = str(mount).split(":")[:2]
        if any(SQLITE_FILE_RE.search(str(field or "")) for field in fields):
            return True
    return False


def add_finding(
    findings: list[Finding],
    severity: str,
    file: str,
    service: str,
    message: str,
    recommendation: str,
) -> None:
    findings.append(Finding(severity=severity, file=file, service=service, message=message, recommendation=recommendation))


def has_edge_publish(ports: list[PortRef]) -> bool:
    return any(port.published in {"80", "443"} for port in ports)


def analyze_service(
    service: dict[str, Any],
    record: ServiceRecord,
    findings: list[Finding],
    approved_images: dict[str, set[str]],
    selected_ingress: str,
    selected_webserver: str,
    selected_database: str,
    expected_web_image: str | None,
) -> None:
    image = record.image
    if record.build_only:
        add_finding(
            findings,
            "INFO",
            record.file,
            record.name,
            "Service uses `build` without an explicit image.",
            "Build and push the image to the private registry before creating Helm values.",
        )

    if image is not None and image.variable:
        add_finding(
            findings,
            "INFO",
            record.file,
            record.name,
            f"Image reference is variable-driven: `{image.raw}`.",
            "Resolve the variable in the target environment before comparing runtime pins.",
        )
    elif image is not None:
        if image.digest is None and not image.tag:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Image `{image.raw}` has no explicit tag.",
                "Pin an immutable version and promote it through the private registry.",
            )
        if image.tag in MUTABLE_TAGS:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Image `{image.raw}` uses mutable tag `{image.tag}`.",
                "Replace mutable tags with an approved version and digest pin for production.",
            )

        approved_tags = approved_images.get(image.canonical_repository)
        if approved_tags and image.tag and image.tag not in approved_tags:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Runtime image `{image.display}` is not in the approved tag set `{sorted(approved_tags)}`.",
                "Update the Compose source or add an intentional approved image-policy entry.",
            )

    if selected_ingress == "traefik" and has_edge_publish(record.ports):
        add_finding(
            findings,
            "WARN",
            record.file,
            record.name,
            "Service publishes host port 80 or 443 while Traefik is the selected edge ingress.",
            "Model this service behind a Kubernetes Service and Traefik Ingress instead of binding host ports.",
        )

    if selected_ingress == "traefik" and record.kind == "traefik":
        add_finding(
            findings,
            "WARN",
            record.file,
            record.name,
            "Compose project includes its own Traefik service.",
            "RKE2 already owns the bundled Traefik ingress; import app backends and routes, not a second edge controller.",
        )
    if selected_ingress == "traefik" and record.kind == "nginx" and has_edge_publish(record.ports):
        add_finding(
            findings,
            "WARN",
            record.file,
            record.name,
            "Compose nginx appears to be acting as an edge gateway.",
            "Move external routes to Traefik Ingress and keep nginx only as an internal backend if needed.",
        )

    webserver_kinds = {"nginx", "apache-httpd", "apache-tomcat", "traefik"}
    if record.kind in webserver_kinds and record.kind != selected_webserver:
        add_finding(
            findings,
            "WARN",
            record.file,
            record.name,
            f"Service uses `{record.kind}` but selected webserver profile is `{selected_webserver}`.",
            "Switch the platform profile, or migrate this service to the selected webserver/Ingress pattern.",
        )
    if record.kind == "nginx" and selected_webserver == "nginx" and image is not None and expected_web_image:
        if image.display != expected_web_image:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"nginx image `{image.display}` differs from selected platform image `{expected_web_image}`.",
                "Prefer `nginxinc/nginx-unprivileged:1.30.2` for the platform gateway, or document why this backend is separate.",
            )

    if record.kind in POSTGRES_FAMILY_KINDS and image is not None:
        if not selected_database_matches_kind(record.kind, selected_database):
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Service uses PostgreSQL-family image `{image.display}` but selected database profile is `{selected_database}`.",
                "Select the PostgreSQL/CloudNativePG profile or plan a database migration.",
            )
        major = detect_postgres_major(image)
        if major is None:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Could not detect PostgreSQL major version from `{image.display}`.",
                "Confirm the major version and extensions before mapping it to CloudNativePG.",
            )
        elif major < 12:
            add_finding(
                findings,
                "ERROR",
                record.file,
                record.name,
                f"PostgreSQL major `{major}` is too old for the CloudNativePG migration path.",
                "Upgrade or dump/restore into PostgreSQL 18-compatible images before import.",
            )
        elif major < 18:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"PostgreSQL major `{major}` is older than the platform default major `18`.",
                "Run extension and dump/restore compatibility checks before import.",
            )
        elif major > 18:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"PostgreSQL major `{major}` is newer than the platform default major `18`.",
                "Update the database catalog/operator support before selecting this image.",
            )

    if record.kind in OPTIONAL_DATABASE_KINDS:
        if selected_database_matches_kind(record.kind, selected_database):
            add_finding(
                findings,
                "INFO",
                record.file,
                record.name,
                f"Service uses optional database engine `{record.kind}` matching selected profile `{selected_database}`.",
                "Map it to an operator-backed, managed, or external database target before workload cutover.",
            )
        else:
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Service uses optional database engine `{record.kind}` while selected database profile is `{selected_database}`.",
                "Choose the matching optional database profile or define an external target in the private database target map.",
            )

    if record.kind not in DATABASE_KINDS and service_uses_sqlite_files(service):
        add_finding(
            findings,
            "INFO",
            record.file,
            record.name,
            "Service appears to mount or reference SQLite database files.",
            "Keep SQLite only for dev/single-pod mode, or externalize the data store before HA migration.",
        )

    for key, value in environment_entries(service.get("environment")):
        if not SECRET_KEY_RE.search(key):
            continue
        if value is None or VARIABLE_VALUE_RE.match(value):
            continue
        add_finding(
            findings,
            "ERROR",
            record.file,
            record.name,
            f"Environment variable `{key}` appears to contain a literal secret value.",
            "Move secret material into SOPS, External Secrets, Sealed Secrets, or Vault before import.",
        )

    if service.get("env_file"):
        add_finding(
            findings,
            "INFO",
            record.file,
            record.name,
            "Service uses Compose `env_file`.",
            "Verify those files stay private and translate sensitive entries into Kubernetes Secret references.",
        )

    for mount in service.get("volumes") or []:
        source = None
        target = None
        if isinstance(mount, dict):
            source = mount.get("source")
            target = mount.get("target")
        else:
            text = str(mount)
            parts = text.split(":")
            if len(parts) >= 2:
                source, target = parts[0], parts[1]
        if not source:
            continue
        source_text = str(source)
        if source_text == "/var/run/docker.sock":
            add_finding(
                findings,
                "ERROR",
                record.file,
                record.name,
                "Service mounts `/var/run/docker.sock`.",
                "Avoid Docker socket mounts in Kubernetes; replace with a least-privilege integration.",
            )
        elif source_text.startswith(("/", "./", "../", "~")):
            add_finding(
                findings,
                "WARN",
                record.file,
                record.name,
                f"Service uses host bind mount `{source_text}` -> `{target or 'unknown'}`.",
                "Map bind-mounted config/data to a ConfigMap, Secret, or PersistentVolumeClaim.",
            )


def read_compose_services(project_path: Path, compose_files: list[Path], findings: list[Finding]) -> list[tuple[ServiceRecord, dict[str, Any]]]:
    services: list[tuple[ServiceRecord, dict[str, Any]]] = []
    for compose_file in compose_files:
        display_file = compose_file.relative_to(project_path).as_posix()
        try:
            document = load_yaml(compose_file)
        except Exception as exc:
            add_finding(findings, "ERROR", display_file, "-", f"Could not parse Compose file: {exc}", "Fix the YAML before import.")
            continue
        raw_services = document.get("services", {})
        if not isinstance(raw_services, dict) or not raw_services:
            add_finding(
                findings,
                "WARN",
                display_file,
                "-",
                "Compose file has no service definitions.",
                "Confirm this is an override-only file and run the checker against the full project directory.",
            )
            continue
        for service_name, service in raw_services.items():
            if not isinstance(service, dict):
                add_finding(findings, "ERROR", display_file, str(service_name), "Service definition is not a mapping.", "Fix the Compose service before import.")
                continue
            image = parse_image_ref(service.get("image"))
            ports = [parse_port_ref(port) for port in service.get("ports") or []]
            build_only = image is None and "build" in service
            record = ServiceRecord(
                file=display_file,
                name=str(service_name),
                image=image,
                kind=image_kind(image),
                ports=ports,
                build_only=build_only,
            )
            services.append((record, service))
    return services


def count_findings(findings: list[Finding], needle: str) -> int:
    return sum(1 for finding in findings if needle in finding.message)


def count_runtime_drift(findings: list[Finding]) -> int:
    return sum(1 for finding in findings if "is not in the approved tag set" in finding.message)


def unique_records(records: list[ServiceRecord]) -> list[ServiceRecord]:
    seen: set[tuple[str, str]] = set()
    unique: list[ServiceRecord] = []
    for record in records:
        key = (record.file, record.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def compact_scope(records: list[ServiceRecord], redactor: ReportRedactor, limit: int = 10) -> str:
    unique = unique_records(records)
    if not unique:
        return "none detected"
    rendered = [
        f"`{redactor.file(record.file)}` :: `{redactor.service(record.name)}`"
        for record in unique[:limit]
    ]
    remaining = len(unique) - len(rendered)
    if remaining > 0:
        rendered.append(f"`+{remaining}` more")
    return ", ".join(rendered)


def compact_kind_counts(records: list[ServiceRecord]) -> str:
    counts: dict[str, int] = {}
    for record in unique_records(records):
        counts[record.kind] = counts.get(record.kind, 0) + 1
    if not counts:
        return "none detected"
    return ", ".join(f"`{kind}`: `{count}`" for kind, count in sorted(counts.items()))


def render_migration_plan(
    lines: list[str],
    service_records: list[ServiceRecord],
    findings: list[Finding],
    redactor: ReportRedactor,
    selected_ingress: str,
    selected_webserver: str,
    selected_database: str,
    expected_web_image: str | None,
    database_targets: list[str],
) -> None:
    secret_errors = count_findings(findings, "literal secret value")
    docker_socket_errors = count_findings(findings, "/var/run/docker.sock")
    bind_mounts = count_findings(findings, "host bind mount")
    build_only = sum(1 for record in service_records if record.build_only)
    no_tag = count_findings(findings, "has no explicit tag")
    mutable_tags = count_findings(findings, "uses mutable tag")
    runtime_drift = count_runtime_drift(findings)
    database_records = [record for record in service_records if record.kind in POSTGRES_FAMILY_KINDS]
    optional_database_records = [record for record in service_records if record.kind in OPTIONAL_DATABASE_KINDS]
    ingress_records = [
        record for record in service_records
        if has_edge_publish(record.ports) or (selected_ingress == "traefik" and record.kind in {"nginx", "traefik"})
    ]

    lines.extend(
        [
            "",
            "## Migration Plan",
            "",
            "This plan is safe to generate in redacted mode. Use the private full report only on the operator machine when mapping aliases back to exact files and services.",
            "",
            "### 1. Clear Hard Blockers",
            "",
            f"- Literal secret findings: `{secret_errors}`. Move values into SOPS, External Secrets, Sealed Secrets, or Vault. Compose placeholders should look like `${{SECRET_NAME}}`, not real values.",
            f"- Docker socket mounts: `{docker_socket_errors}`. Replace Docker-socket monitoring with Kubernetes-native telemetry, node exporters, Zabbix Kubernetes templates, or a least-privilege agent.",
            "- Do not commit full import reports; keep private reports under an ignored or external private directory.",
            "",
            "### 2. Database Migration",
            "",
            f"- Selected database profile: `{selected_database}`.",
            f"- PostgreSQL-family services detected: `{len(unique_records(database_records))}`.",
            f"- Optional database services detected: `{len(unique_records(optional_database_records))}` ({compact_kind_counts(optional_database_records)}).",
            f"- Target database images from selected values: `{', '.join(database_targets) if database_targets else 'not detected'}`.",
            f"- Scope sample: {compact_scope(database_records, redactor)}.",
            "- Do not reuse old PostgreSQL major-version data directories as Kubernetes volumes. Use logical dump/restore when moving PostgreSQL 16-family data to PostgreSQL 18-family targets.",
            "- Precheck each source with `SELECT version();` and `SELECT extname, extversion FROM pg_extension ORDER BY 1;`.",
            "- Migration rehearsal pattern: `pg_dump --format=custom --no-owner --no-acl --file=<database>.dump <source>` then `pg_restore --clean --if-exists --no-owner --dbname=<target> <database>.dump`.",
            "- For PostGIS and TimescaleDB, create/upgrade extensions on the target before restore, then run application smoke tests before switching traffic.",
            "- MySQL, MariaDB, Microsoft SQL Server, MongoDB, and SQLite are optional target profiles. The importer generates private target-map scaffolds for them, while engine-specific dump/restore runners should be enabled only after the matching operator, managed service, or external endpoint is declared.",
            "",
            "### 3. Edge Routing And Webserver",
            "",
            f"- Selected ingress: `{selected_ingress}`. Selected webserver: `{selected_webserver}`.",
            f"- Target webserver image: `{expected_web_image or 'not detected'}`.",
            f"- Edge/web scope sample: {compact_scope(ingress_records, redactor)}.",
            "- For nginx services binding host ports `80` or `443`, move external routing to a Kubernetes `Ingress` with `ingressClassName: traefik`.",
            "- Preserve backend containers as `ClusterIP` Services. Convert nginx routing rules into Traefik Ingress routes, middlewares, and TLS references.",
            "- If nginx is only serving static files, bake static content into an application image or mount a ConfigMap/PVC behind Traefik instead of running it as the edge gateway.",
            "",
            "### 4. Image Promotion",
            "",
            f"- Build-only services: `{build_only}`. Untagged image findings: `{no_tag}`. Mutable tag findings: `{mutable_tags}`. Runtime version drift findings: `{runtime_drift}`.",
            "- Build application images with explicit release tags, push them to the private registry, then reference those tags from private Helm values.",
            "- For production, promote images by digest after vulnerability scan and SBOM evidence are attached.",
            "- Runtime image drift should be handled by either upgrading to the selected platform image pins or intentionally updating `config/image-policy.yaml` and Helm values together.",
            "",
            "### 5. Volumes And Configuration",
            "",
            f"- Host bind mount findings: `{bind_mounts}`.",
            "- Config files should become ConfigMaps unless they contain secrets. Secret-like files should become Kubernetes Secret references through the selected secret manager.",
            "- Stateful data directories should become PVC-backed workloads or operator-managed storage. Database data directories need logical migration, not a raw copy across major versions.",
            "- Logs should go to stdout/stderr or the selected observability pipeline rather than host log directories.",
            "",
            "### 6. Validation Loop",
            "",
            "- Re-run `make import-check PROJECT_PATH=/path/to/compose-project IMPORT_REDACT=true IMPORT_REPORT=reports/import-check-public.md` after each remediation batch.",
            "- When errors reach zero, run with `IMPORT_STRICT=true` to force warnings into the migration backlog before deployment dry runs.",
        ]
    )


def render_report(
    project_path: Path,
    compose_files: list[Path],
    service_records: list[ServiceRecord],
    findings: list[Finding],
    selected_ingress: str,
    selected_webserver: str,
    selected_database: str,
    expected_web_image: str | None,
    database_targets: list[str],
    redact_sensitive: bool = False,
) -> str:
    redactor = ReportRedactor(redact_sensitive)
    counts = {severity: 0 for severity in ["ERROR", "WARN", "INFO"]}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    result = "FAIL" if counts["ERROR"] else "PASS_WITH_WARNINGS" if counts["WARN"] else "PASS"
    lines = [
        "# Project Import Compatibility Report",
        "",
        f"- Project path: `{redactor.project_path(project_path)}`",
        f"- Selected ingress: `{selected_ingress}`",
        f"- Selected webserver: `{selected_webserver}`",
        f"- Selected database: `{selected_database}`",
        f"- Result: `{result}`",
        f"- Summary: `{counts['ERROR']}` error(s), `{counts['WARN']}` warning(s), `{counts['INFO']}` info item(s)",
        f"- Redacted output: `{'true' if redact_sensitive else 'false'}`",
        "",
        "## Compose Files",
        "",
    ]
    if compose_files:
        lines.extend(f"- `{redactor.file(path.relative_to(project_path).as_posix())}`" for path in compose_files)
    else:
        lines.append("- No Compose files found.")
    lines.extend(["", "## Findings", ""])
    if findings:
        for finding in findings:
            lines.append(
                f"- **{finding.severity}** `{redactor.file(finding.file)}` :: `{redactor.service(finding.service)}` - "
                f"{redactor.text(finding.message)} Recommendation: {redactor.text(finding.recommendation)}"
            )
    else:
        lines.append("- No compatibility issues detected by the static checker.")
    lines.extend(["", "## Service Inventory", ""])
    if service_records:
        lines.append("| Compose file | Service | Kind | Image | Ports |")
        lines.append("|---|---|---|---|---|")
        for record in service_records:
            image = redactor.image(record)
            ports = ", ".join(port.display for port in record.ports) if record.ports else "-"
            lines.append(f"| `{redactor.file(record.file)}` | `{redactor.service(record.name)}` | `{record.kind}` | `{image}` | `{ports}` |")
    else:
        lines.append("- No services inventoried.")
    render_migration_plan(
        lines=lines,
        service_records=service_records,
        findings=findings,
        redactor=redactor,
        selected_ingress=selected_ingress,
        selected_webserver=selected_webserver,
        selected_database=selected_database,
        expected_web_image=expected_web_image,
        database_targets=database_targets,
    )
    if redact_sensitive:
        lines.extend(
            [
                "",
                "## Redaction Note",
                "",
                "Project paths, Compose filenames, service names, and local application image names were redacted.",
                "Run again without `--redact-sensitive` only on a trusted operator machine when you need exact remediation targets.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def automation_adjusted_findings(
    findings: list[Finding],
    allow_literal_secret_import: bool = False,
    allow_docker_socket_skip: bool = False,
) -> list[Finding]:
    adjusted: list[Finding] = []
    for finding in findings:
        if (
            finding.severity == "ERROR"
            and allow_literal_secret_import
            and "literal secret value" in finding.message
        ):
            adjusted.append(
                Finding(
                    severity="WARN",
                    file=finding.file,
                    service=finding.service,
                    message=(
                        f"{finding.message} Automated import is allowed to read this value "
                        "on the operator machine and create a Kubernetes Secret."
                    ),
                    recommendation=(
                        "Keep generated private reports out of Git, rotate the value after "
                        "migration when practical, and move future changes to SOPS, External "
                        "Secrets, Sealed Secrets, or Vault."
                    ),
                )
            )
            continue
        if (
            finding.severity == "ERROR"
            and allow_docker_socket_skip
            and "/var/run/docker.sock" in finding.message
        ):
            adjusted.append(
                Finding(
                    severity="WARN",
                    file=finding.file,
                    service=finding.service,
                    message=(
                        f"{finding.message} Automated import will skip Docker-socket behavior "
                        "instead of carrying it into Kubernetes."
                    ),
                    recommendation=(
                        "Use Kubernetes-native telemetry, node exporters, Zabbix Kubernetes "
                        "templates, or another least-privilege integration after import."
                    ),
                )
            )
            continue
        adjusted.append(finding)
    return adjusted


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check an external Docker Compose project before importing it.")
    parser.add_argument("--project-path", required=True, help="Path to the external project, for example /path/to/compose-project.")
    parser.add_argument("--values", default=str(DEFAULT_VALUES), help="Helm values file used to infer selected platform defaults.")
    parser.add_argument("--image-policy", default=str(DEFAULT_IMAGE_POLICY), help="Image policy used for approved runtime tag checks.")
    parser.add_argument("--ingress-controller", choices=["traefik", "nginx"], help="Selected platform ingress controller.")
    parser.add_argument("--webserver", choices=["nginx", "apache-httpd", "apache-tomcat", "traefik"], help="Selected platform webserver profile.")
    parser.add_argument("--database", help="Selected platform database profile, for example postgresql or cloudnative-pg.")
    parser.add_argument("--report", help="Optional Markdown report output path.")
    parser.add_argument("--redact-sensitive", action="store_true", help="Redact project paths, Compose filenames, service names, and local application image names in the report.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when warnings are present.")
    parser.add_argument(
        "--allow-literal-secret-import",
        action="store_true",
        help="Downgrade literal secret findings when a trusted migration run will import them into Kubernetes Secrets.",
    )
    parser.add_argument(
        "--allow-docker-socket-skip",
        action="store_true",
        help="Downgrade Docker socket findings when migration will skip that unsafe behavior.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if yaml is None:
        print("PyYAML is required. Install it with `python3 -m pip install PyYAML`.", file=sys.stderr)
        return 2

    project_path = Path(args.project_path).expanduser().resolve()
    if not project_path.exists() or not project_path.is_dir():
        print(f"Project path does not exist or is not a directory: {project_path}", file=sys.stderr)
        return 2

    values_path = Path(args.values).expanduser()
    if not values_path.is_absolute():
        values_path = (ROOT / values_path).resolve()
    policy_path = Path(args.image_policy).expanduser()
    if not policy_path.is_absolute():
        policy_path = (ROOT / policy_path).resolve()

    try:
        values = load_yaml(values_path)
        approved_images = normalize_approved_images(policy_path)
    except Exception as exc:
        print(f"Could not load platform configuration: {exc}", file=sys.stderr)
        return 2

    selected_ingress = args.ingress_controller or values.get("ingress", {}).get("className", "traefik")
    selected_webserver = args.webserver or values.get("webserver", {}).get("provider", "nginx")
    selected_database = args.database or values.get("databases", {}).get("provider", "cloudnative-pg")
    expected_web_image = expected_webserver_image(values, selected_webserver)
    selected_database_targets = database_target_images(values)

    findings: list[Finding] = []
    compose_files = find_compose_files(project_path)
    if not compose_files:
        add_finding(
            findings,
            "ERROR",
            "-",
            "-",
            "No Docker Compose files were found in the project path.",
            "Place compose files under the project path or pass the correct --project-path.",
        )

    service_pairs = read_compose_services(project_path, compose_files, findings)
    for record, service in service_pairs:
        analyze_service(
            service=service,
            record=record,
            findings=findings,
            approved_images=approved_images,
            selected_ingress=str(selected_ingress),
            selected_webserver=str(selected_webserver),
            selected_database=str(selected_database),
            expected_web_image=expected_web_image,
        )

    report_findings = automation_adjusted_findings(
        findings,
        allow_literal_secret_import=args.allow_literal_secret_import,
        allow_docker_socket_skip=args.allow_docker_socket_skip,
    )

    report = render_report(
        project_path=project_path,
        compose_files=compose_files,
        service_records=[record for record, _service in service_pairs],
        findings=report_findings,
        selected_ingress=str(selected_ingress),
        selected_webserver=str(selected_webserver),
        selected_database=str(selected_database),
        expected_web_image=expected_web_image,
        database_targets=selected_database_targets,
        redact_sensitive=args.redact_sensitive,
    )
    print(report)

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    has_errors = any(finding.severity == "ERROR" for finding in report_findings)
    has_warnings = any(finding.severity == "WARN" for finding in report_findings)
    if has_errors or (args.strict and has_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
