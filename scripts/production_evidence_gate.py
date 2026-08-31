#!/usr/bin/env python3
"""Fail-closed production evidence and live-cluster readiness gate.

The gate reads private evidence metadata and hashes evidence artifact bytes, but
never prints or persists secret values, kubeconfig contents, or image layers.
Evidence content and private paths are never included in reports. It is intended
to run on the operator or a private release runner, not in public CI.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import re
import shutil
import ssl
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - the private gate requires PyYAML.
    yaml = None

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SCRIPT_DIR / "images") not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR / "images"))

import kafka_clickhouse_readiness as kafka_readiness  # noqa: E402
import promotion_plan  # noqa: E402


DIGEST_RE = re.compile(r"^sha256:[A-Fa-f0-9]{64}$")
RELEASE_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
SOURCE_REVISION_RE = re.compile(r"^(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})$")
PSA_VERSION_RE = re.compile(r"^v1\.[0-9]+$")
MAX_MANIFEST_VALIDITY = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)
MIN_COSIGN_VERSION = (3, 1, 3)
SIGSTORE_BUNDLE_MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
HTTP_PROBE_TIMEOUT_SECONDS = 15
HTTPS_PROBE_STATUS_CODES = frozenset({200, 201, 202, 204, 301, 302, 303, 307, 308, 401, 403})
HTTP_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
REQUIRED_IMAGE_EVIDENCE = (
    "vulnerabilityScan",
    "sbom",
    "signatureOrAttestation",
    "promotionRecord",
)
REQUIRED_DR_ARTIFACTS = (
    "rtoRpo",
    "dependencyMap",
    "criticalityMap",
    "backupReplication",
    "dataReplication",
    "crossZonePlacement",
    "databaseRestore",
    "etcdRestore",
    "namespaceRestore",
    "applicationSmokeTest",
    "runbook",
    "commsPlan",
    "manualWorkaround",
    "supplierContacts",
    "drillEvidence",
    "rtoEvidence",
    "postDrillReview",
)


@dataclass(frozen=True)
class TrustPolicy:
    cosign: str
    trusted_approvers: frozenset[str]


class NoRedirectHandler(HTTPRedirectHandler):
    """Keep redirect responses visible so the HTTP-to-HTTPS contract is tested."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def meaningful_identity(value: Any) -> bool:
    identity = str(value).strip()
    lowered = identity.lower()
    return (
        len(identity) >= 3
        and "<" not in identity
        and ">" not in identity
        and lowered not in {"changeme", "placeholder", "reviewer-id", "platform-owner"}
    )


def immutable_source_revision(value: Any) -> bool:
    revision = str(value).strip().lower()
    return bool(SOURCE_REVISION_RE.fullmatch(revision) and len(set(revision)) >= 4)


def canonical_uuid(value: Any, *, version: int | None = None) -> str | None:
    candidate = str(value).strip().lower()
    try:
        parsed = uuid.UUID(candidate)
    except (AttributeError, TypeError, ValueError):
        return None
    if str(parsed) != candidate or (version is not None and parsed.version != version):
        return None
    return candidate


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise ValueError("PyYAML is required by the private production evidence gate")
    if not path.is_file():
        raise ValueError("required evidence manifest is missing")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("evidence manifest must contain a mapping")
    return loaded


def resolve_path(value: Any, base: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def nonempty_file(path: Path | None) -> bool:
    return path is not None and path.is_file() and path.stat().st_size > 0


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def digest_matches(path: Path | None, expected_digest: Any) -> bool:
    expected = str(expected_digest).strip().lower()
    return bool(
        nonempty_file(path)
        and DIGEST_RE.fullmatch(expected)
        and path is not None
        and file_digest(path).lower() == expected
    )


def utc_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_attestation_window(config: dict[str, Any]) -> tuple[bool, str]:
    attestation = mapping(config.get("attestation"))
    issued_at = utc_timestamp(attestation.get("issuedAt"))
    expires_at = utc_timestamp(attestation.get("expiresAt"))
    if issued_at is None or expires_at is None:
        return False, "signed evidence attestation issue or expiry time is missing"
    now = datetime.now(timezone.utc)
    validity = expires_at - issued_at
    if issued_at > now + MAX_CLOCK_SKEW:
        return False, "signed evidence attestation is not valid yet"
    if expires_at <= now:
        return False, "signed evidence attestation has expired"
    if validity <= timedelta(0) or validity > MAX_MANIFEST_VALIDITY:
        return False, "signed evidence attestation validity exceeds 24 hours"
    return True, "signed evidence attestation is current and expires within 24 hours"


def validate_source_checkout(source_revision: Any) -> tuple[bool, str]:
    revision = str(source_revision).strip().lower()
    if not immutable_source_revision(revision):
        return False, "signed source revision is invalid"
    git = shutil.which("git")
    if not git:
        return False, "git is required to verify the production gate source checkout"
    commands = (
        ([git, "-C", str(ROOT), "rev-parse", "--show-toplevel"], "root"),
        ([git, "-C", str(ROOT), "rev-parse", "HEAD"], "revision"),
        ([git, "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"], "status"),
    )
    results: dict[str, str] = {}
    for command, name in commands:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "production gate source checkout could not be verified"
        if completed.returncode != 0:
            return False, "production gate source checkout could not be verified"
        results[name] = completed.stdout.strip()
    try:
        checkout_root = Path(results["root"]).resolve()
    except (OSError, ValueError):
        return False, "production gate source checkout root is invalid"
    if checkout_root != ROOT.resolve():
        return False, "production gate is not running from the expected repository root"
    if results["revision"].lower() != revision:
        return False, "production gate checkout does not match the signed source revision"
    if results["status"]:
        return False, "production gate checkout contains tracked or untracked drift"
    return True, "production gate runs from the clean signed source revision"


def validate_trust_policy(
    trust_policy_path: Path | None,
    evidence_manifest_path: Path,
) -> tuple[bool, str, TrustPolicy | None]:
    if not nonempty_file(trust_policy_path):
        return False, "operator trust policy is missing", None
    try:
        trust = load_yaml(trust_policy_path)
    except (OSError, ValueError, TypeError):
        return False, "operator trust policy is invalid", None
    if int(trust.get("version", 0) or 0) != 2 or trust.get("provider") != "cosign-key-bundle":
        return False, "operator trust policy version or provider is unsupported", None
    manifest = mapping(trust.get("evidenceManifest"))
    public_key = resolve_path(manifest.get("publicKey"), trust_policy_path.parent)
    bundle = resolve_path(manifest.get("bundle"), trust_policy_path.parent)
    approver_values = trust.get("trustedApprovers")
    if not isinstance(approver_values, list):
        return False, "operator trust policy has no trusted approver allowlist", None
    approvers = frozenset(str(value).strip() for value in approver_values if meaningful_identity(value))
    if not approvers or len(approvers) != len(approver_values):
        return False, "operator trust policy contains an empty or placeholder approver", None
    if not nonempty_file(public_key) or not nonempty_file(bundle):
        return False, "trusted public key or standardized evidence bundle is missing", None
    try:
        bundle_data = json.loads(bundle.read_text(encoding="utf-8")) if bundle is not None else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, "standardized evidence bundle is invalid", None
    if not isinstance(bundle_data, dict) or bundle_data.get("mediaType") != SIGSTORE_BUNDLE_MEDIA_TYPE:
        return False, "legacy or unsupported evidence bundle format is forbidden", None
    cosign = shutil.which("cosign")
    if not cosign:
        return False, "cosign is required to verify the production evidence signature", None
    try:
        version_result = subprocess.run(
            [cosign, "version", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        version_match = re.search(
            r"v?(\d+)\.(\d+)\.(\d+)",
            version_result.stdout if version_result.returncode == 0 else "",
        )
        if version_match is None or tuple(int(value) for value in version_match.groups()) < MIN_COSIGN_VERSION:
            return False, "cosign 3.1.3 or newer is required for secure bundle verification", None
        completed = subprocess.run(
            [
                cosign,
                "verify-blob",
                "--key",
                str(public_key),
                "--bundle",
                str(bundle),
                str(evidence_manifest_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "detached production evidence signature could not be verified", None
    if completed.returncode != 0:
        return False, "detached production evidence signature is invalid", None
    return True, "standardized Sigstore bundle and trusted approver allowlist are valid", TrustPolicy(cosign, approvers)


def evidence_artifact(
    value: Any,
    base: Path,
    maximum_age_days: int,
    trusted_approvers: frozenset[str],
) -> tuple[bool, Path | None]:
    descriptor = mapping(value)
    path = resolve_path(descriptor.get("path"), base)
    expected_digest = str(descriptor.get("sha256", "")).strip().lower()
    captured_at = str(descriptor.get("capturedAt", "")).strip()
    approved_by = str(descriptor.get("approvedBy", "")).strip()
    if (
        not nonempty_file(path)
        or not DIGEST_RE.fullmatch(expected_digest)
        or not captured_at
        or approved_by not in trusted_approvers
        or maximum_age_days < 1
    ):
        return False, path
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            return False, path
        age_seconds = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
        if age_seconds < -86400 or age_seconds > maximum_age_days * 86400:
            return False, path
        if path is None or file_digest(path).lower() != expected_digest:
            return False, path
    except (OSError, ValueError):
        return False, path
    return True, path


def image_key(image: promotion_plan.ImageObject) -> str:
    return image.path


def kubernetes_name(value: Any) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", str(value).strip())
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()


def merged_images(base_values: Path, public_values: Path, private_values: Path) -> tuple[dict[str, Any], list[promotion_plan.ImageObject]]:
    base = promotion_plan.load_yaml(base_values)
    public = promotion_plan.load_yaml(public_values)
    private = promotion_plan.load_yaml(private_values)
    merged = promotion_plan.merge_values(promotion_plan.merge_values(base, public), private)
    source = "production-values"
    images = promotion_plan.images_from_loaded_yaml(source, merged)
    unique: dict[tuple[str, str], promotion_plan.ImageObject] = {}
    for image in images:
        unique[(image.path, image.reference)] = image
    return merged, sorted(unique.values(), key=lambda item: item.path)


def approved_runtime_image_references(
    base_values: Path,
    public_values: Path,
    private_values: Path,
) -> set[str]:
    merged, images = merged_images(base_values, public_values, private_values)
    registry = str(mapping(merged.get("global")).get("imageRegistry", "")).strip().rstrip("/")
    if not registry or not images:
        raise ValueError("approved production runtime image inventory is unavailable")
    references: set[str] = set()
    for image in images:
        if not image.repository or not image.digest or not DIGEST_RE.fullmatch(image.digest):
            raise ValueError("approved production runtime image inventory is not fully digest pinned")
        references.add(f"{registry}/{image.repository}@{image.digest}")
    return references


def resolved_image_digest(value: Any) -> str | None:
    match = re.search(r"sha256:[A-Fa-f0-9]{64}", str(value))
    return match.group(0).lower() if match else None


def validate_release(config: dict[str, Any], config_dir: Path) -> tuple[bool, str, Path | None]:
    release = mapping(config.get("release"))
    tag = str(release.get("tag", "")).strip()
    owner = str(release.get("owner", "")).strip()
    source_revision = str(release.get("sourceRevision", "")).strip()
    deployment_id = canonical_uuid(release.get("deploymentId"), version=4)
    private_values = resolve_path(release.get("valuesOverlay"), config_dir)
    if not tag or not RELEASE_TAG_RE.fullmatch(tag):
        return False, "release tag is missing or not a release version", private_values
    if tag.lower().lstrip("v") == "0.0.0" or not meaningful_identity(owner):
        return False, "release owner or non-placeholder release tag is missing", private_values
    if not immutable_source_revision(source_revision):
        return False, "immutable source revision is missing", private_values
    if deployment_id is None:
        return False, "unique release deployment ID is missing", private_values
    if not nonempty_file(private_values):
        return False, "private production values overlay is missing", private_values
    if not digest_matches(private_values, release.get("valuesOverlaySha256")):
        return False, "private production values overlay checksum is missing or invalid", private_values
    try:
        private = load_yaml(private_values)
    except (OSError, ValueError, TypeError):
        return False, "private production values overlay is invalid", private_values
    release_identity = mapping(mapping(private.get("global")).get("releaseIdentity"))
    if release_identity.get("enabled") is not True:
        return False, "private production values overlay does not enable release identity", private_values
    if str(release_identity.get("tag", "")).strip() != tag:
        return False, "private production values release tag does not match signed evidence", private_values
    if str(release_identity.get("sourceRevision", "")).strip().lower() != source_revision.lower():
        return False, "private production values source revision does not match signed evidence", private_values
    if canonical_uuid(release_identity.get("deploymentId"), version=4) != deployment_id:
        return False, "private production values deployment ID does not match signed evidence", private_values
    return True, "signed release identity, deployment ID, source revision, and private overlay checksum are valid", private_values


def validate_registry(
    config: dict[str, Any],
    config_dir: Path,
    base_values: Path,
    public_values: Path,
    private_values: Path | None,
    trusted_approvers: frozenset[str],
) -> tuple[bool, str, int]:
    if private_values is None or not nonempty_file(private_values):
        return False, "private production values overlay is unavailable", 0
    registry = mapping(config.get("registry"))
    private_registry = str(registry.get("privateRegistry", "")).strip().rstrip("/")
    if not private_registry or "example.invalid" in private_registry or private_registry.startswith("localhost"):
        return False, "approved private registry is missing", 0
    evidence_root = resolve_path(registry.get("evidenceRoot"), config_dir)
    index_path = resolve_path(registry.get("imageEvidenceIndex"), evidence_root or config_dir)
    maximum_age_days = int(registry.get("maximumEvidenceAgeDays", 30) or 0)
    if not nonempty_file(index_path):
        return False, "image evidence index is missing", 0
    if not digest_matches(index_path, registry.get("imageEvidenceIndexSha256")):
        return False, "image evidence index checksum is missing or invalid", 0
    try:
        merged, images = merged_images(base_values, public_values, private_values)
        index = load_yaml(index_path)
    except (OSError, ValueError, TypeError) as exc:
        return False, str(exc), 0
    global_values = mapping(merged.get("global"))
    configured_registry = str(global_values.get("imageRegistry", "")).strip().rstrip("/")
    if configured_registry != private_registry:
        return False, "private overlay registry does not match the evidence manifest", len(images)
    if not images:
        return False, "production image inventory is empty", 0
    if int(index.get("version", 0) or 0) != 2:
        return False, "image evidence index version is unsupported", len(images)
    entries = index.get("images")
    if not isinstance(entries, list):
        return False, "image evidence index has no images list", len(images)
    entry_by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("path", "")).strip():
            return False, "image evidence index contains an invalid image entry", len(images)
        path = str(entry["path"]).strip()
        if path in entry_by_path:
            return False, "image evidence index contains duplicate image paths", len(images)
        entry_by_path[path] = entry
    image_paths = {image_key(image) for image in images}
    if image_paths != set(entry_by_path):
        return False, "image evidence index does not cover the complete production image inventory", len(images)
    all_evidence_paths: set[Path] = set()
    for image in images:
        entry = entry_by_path[image_key(image)]
        digest = str(entry.get("digest", "")).strip()
        reference = str(entry.get("reference", "")).strip()
        if not image.digest or not DIGEST_RE.fullmatch(image.digest):
            return False, "a production image is not digest pinned", len(images)
        expected_reference = f"{private_registry}/{image.repository}@{image.digest}"
        if digest != image.digest or reference != expected_reference:
            return False, "an image evidence digest or private reference does not match the overlay", len(images)
        evidence_paths: set[Path] = set()
        for evidence_name in REQUIRED_IMAGE_EVIDENCE:
            evidence_ok, evidence_path = evidence_artifact(
                entry.get(evidence_name),
                evidence_root or config_dir,
                maximum_age_days,
                trusted_approvers,
            )
            if not evidence_ok:
                return False, "an image has missing, stale, unapproved, or checksum-invalid evidence", len(images)
            if evidence_path is None or evidence_path in evidence_paths or evidence_path in all_evidence_paths:
                return False, "an image evidence artifact is reused across controls or images", len(images)
            evidence_paths.add(evidence_path)
            all_evidence_paths.add(evidence_path)
    return True, "all production images are privately promoted, digest pinned, checksum verified, current, and approved", len(images)


def validate_dr(
    config: dict[str, Any],
    config_dir: Path,
    trusted_approvers: frozenset[str],
) -> tuple[bool, str, int]:
    disaster_recovery = mapping(config.get("disasterRecovery"))
    evidence_root = resolve_path(disaster_recovery.get("evidenceRoot"), config_dir)
    artifacts = mapping(disaster_recovery.get("artifacts"))
    maximum_age_days = int(disaster_recovery.get("maximumEvidenceAgeDays", 180) or 0)
    missing: list[str] = []
    evidence_paths: set[Path] = set()
    for name in REQUIRED_DR_ARTIFACTS:
        artifact_ok, artifact_path = evidence_artifact(
            artifacts.get(name),
            evidence_root or config_dir,
            maximum_age_days,
            trusted_approvers,
        )
        if not artifact_ok or artifact_path is None or artifact_path in evidence_paths:
            missing.append(name)
        else:
            evidence_paths.add(artifact_path)
    if missing:
        return False, "required backup, restore, continuity, or drill evidence is missing, stale, unapproved, or checksum-invalid", len(REQUIRED_DR_ARTIFACTS) - len(missing)
    return True, "backup, restore, continuity, and post-drill evidence is checksum verified, current, and approved", len(REQUIRED_DR_ARTIFACTS)


def kubectl_json(kubectl: str, kubeconfig: Path, namespace: str | None, resource: str) -> tuple[dict[str, Any] | None, str]:
    command = [kubectl, "--kubeconfig", str(kubeconfig)]
    if namespace:
        command.extend(["-n", namespace])
    command.extend(["get", resource, "-o", "json", "--request-timeout=15s"])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None, "Kubernetes API query failed"
    if completed.returncode != 0:
        return None, "Kubernetes API query failed"
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "Kubernetes API returned invalid JSON"
    return loaded if isinstance(loaded, dict) else None, "ok"


def ready_condition(status: dict[str, Any]) -> bool:
    return any(
        isinstance(condition, dict)
        and condition.get("type") == "Ready"
        and str(condition.get("status", "")).lower() == "true"
        for condition in status.get("conditions", [])
    )


def condition_is_true(status: dict[str, Any], condition_type: str) -> bool:
    return any(
        isinstance(condition, dict)
        and condition.get("type") == condition_type
        and str(condition.get("status", "")).lower() == "true"
        for condition in status.get("conditions", [])
    )


def signed_resource_names(value: Any) -> set[str] | None:
    """Parse a non-empty, duplicate-free resource-name inventory from evidence."""
    if not isinstance(value, (list, tuple)) or not value:
        return None
    names = [str(item).strip() for item in value]
    if any(not name or "/" in name for name in names) or len(set(names)) != len(names):
        return None
    return set(names)


def resource_names(resources: list[dict[str, Any]]) -> set[str]:
    return {
        str(mapping(item.get("metadata")).get("name", "")).strip()
        for item in resources
        if str(mapping(item.get("metadata")).get("name", "")).strip()
    }


def valid_tls_secret(resource: dict[str, Any] | None) -> bool:
    """Require a Kubernetes TLS Secret with both key material entries present."""
    if resource is None or resource.get("type") != "kubernetes.io/tls":
        return False
    data = mapping(resource.get("data"))
    return valid_encoded_secret_data(data.get("tls.crt")) and valid_encoded_secret_data(data.get("tls.key"))


def valid_encoded_secret_data(value: Any) -> bool:
    """Check presence of non-empty base64 Secret data without exposing its value."""
    encoded = str(value or "").strip()
    if not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    return bool(decoded)


def quantity_matches(actual: Any, expected: Any) -> bool:
    """Compare Kubernetes quantities without exposing their values in reports."""
    return str(actual if actual is not None else "").strip() == str(expected if expected is not None else "").strip()


def resource_quota_matches(resource: dict[str, Any] | None, expected_hard: dict[str, Any]) -> bool:
    if resource is None or not expected_hard:
        return False
    actual_hard = mapping(mapping(resource.get("spec")).get("hard"))
    # Production quotas are reviewed as an exact contract. Extra hard limits
    # can silently change admission behavior and must not pass the live gate.
    return set(actual_hard) == set(expected_hard) and all(
        quantity_matches(actual_hard.get(key), value) for key, value in expected_hard.items()
    )


def limit_range_matches(
    resource: dict[str, Any] | None,
    expected_default: dict[str, Any],
    expected_default_request: dict[str, Any],
) -> bool:
    if resource is None or not expected_default or not expected_default_request:
        return False
    entries = [
        entry
        for entry in mapping(resource.get("spec")).get("limits", [])
        if isinstance(entry, dict) and entry.get("type") == "Container"
    ]
    if len(entries) != 1:
        return False
    actual_default = mapping(entries[0].get("default"))
    actual_default_request = mapping(entries[0].get("defaultRequest"))
    return (
        set(actual_default) == set(expected_default)
        and set(actual_default_request) == set(expected_default_request)
        and all(quantity_matches(actual_default.get(key), value) for key, value in expected_default.items())
        and all(
            quantity_matches(actual_default_request.get(key), value)
            for key, value in expected_default_request.items()
        )
    )


def is_http_redirect_ingress(resource: dict[str, Any]) -> bool:
    """Allow only the explicit HTTP-to-HTTPS redirect Ingress without TLS."""
    annotations = mapping(mapping(resource.get("metadata")).get("annotations"))
    return (
        str(annotations.get("traefik.ingress.kubernetes.io/router.entrypoints", "")).strip() == "web"
        and "redirect-https@kubernetescrd"
        in str(annotations.get("traefik.ingress.kubernetes.io/router.middlewares", ""))
    )


def parse_probe_url(value: Any, expected_scheme: str) -> tuple[Any | None, str]:
    """Validate a signed probe URL without exposing it in failure details."""
    raw = str(value or "").strip()
    if not raw or any(character.isspace() for character in raw):
        return None, "the signed ingress probe URL is missing or malformed"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None, "the signed ingress probe URL has an invalid port"
    if (
        parsed.scheme.lower() != expected_scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None, "the signed ingress probe URL is malformed"
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_loopback or address.is_unspecified or address.is_multicast):
        return None, "the signed ingress probe URL must target the production edge, not a local address"
    if parsed.hostname.lower() == "localhost":
        return None, "the signed ingress probe URL must target the production edge, not localhost"
    return parsed, "ok"


def effective_url_port(parsed: Any) -> int:
    if parsed.port is not None:
        return int(parsed.port)
    return 443 if parsed.scheme.lower() == "https" else 80


def probe_http_endpoint(
    url: str,
    *,
    ca_bundle: Path | None,
    expected_status_codes: frozenset[int],
    redirect_target: Any | None = None,
) -> tuple[bool, str]:
    """Perform a bounded, proxy-free GET while keeping endpoint details private."""
    parsed, parse_detail = parse_probe_url(url, "https" if str(url).lower().startswith("https://") else "http")
    if parsed is None:
        return False, parse_detail
    try:
        context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle is not None else None)
        opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=context),
            NoRedirectHandler(),
        )
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.1",
                "User-Agent": "urban-platform-production-evidence/1",
            },
            method="GET",
        )
        with opener.open(request, timeout=HTTP_PROBE_TIMEOUT_SECONDS) as response:
            status = int(response.getcode() or 0)
            headers = response.headers
            response.read(4096)
    except HTTPError as exc:
        status = int(exc.code or 0)
        headers = exc.headers
        try:
            exc.read(4096)
        except (OSError, ValueError):
            pass
    except (OSError, TimeoutError, URLError, ValueError, ssl.SSLError):
        return False, "the signed ingress endpoint probe could not connect or complete TLS verification"
    if status not in expected_status_codes:
        return False, "the signed ingress endpoint returned an unexpected HTTP status"
    if redirect_target is not None:
        location = str(headers.get("Location", "")).strip() if headers is not None else ""
        if not location:
            return False, "the HTTP ingress probe did not return an HTTPS Location"
        try:
            redirected = urlsplit(urljoin(url, location))
            redirected_port = effective_url_port(redirected)
        except ValueError:
            return False, "the HTTP ingress probe returned a malformed redirect"
        if (
            redirected.scheme.lower() != "https"
            or redirected.hostname != redirect_target.hostname
            or redirected.path != redirect_target.path
            or redirected.query != redirect_target.query
            or redirected_port != effective_url_port(redirect_target)
            or redirected.username is not None
            or redirected.password is not None
        ):
            return False, "the HTTP ingress probe redirected to the wrong HTTPS route"
    return True, "the signed ingress HTTPS endpoint and HTTP redirect probe passed"


def status_codes(value: Any) -> frozenset[int] | None:
    if not isinstance(value, (list, tuple, set)) or not value:
        return None
    parsed: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 100 <= item <= 599:
            return None
        parsed.add(item)
    return frozenset(parsed)


def validate_ingress_probe(live: dict[str, Any], config_dir: Path) -> tuple[bool, str]:
    """Require externally reachable HTTPS plus an authenticated HTTP redirect check."""
    probe = mapping(live.get("ingressProbe"))
    if probe.get("required") is not True:
        return False, "signed live evidence does not require an external ingress probe"
    if probe.get("tlsVerify") is not True:
        return False, "external ingress probing must verify the production TLS certificate"
    https_url = str(probe.get("httpsUrl", "")).strip()
    http_url = str(probe.get("httpUrl", "")).strip()
    https_parsed, detail = parse_probe_url(https_url, "https")
    if https_parsed is None:
        return False, detail
    http_parsed, detail = parse_probe_url(http_url, "http")
    if http_parsed is None:
        return False, detail
    if (
        http_parsed.hostname != https_parsed.hostname
        or http_parsed.path != https_parsed.path
        or http_parsed.query != https_parsed.query
    ):
        return False, "signed HTTP and HTTPS ingress probes must address the same route"
    https_status_codes = status_codes(probe.get("expectedHttpsStatusCodes"))
    http_status_codes = status_codes(probe.get("expectedHttpStatusCodes"))
    if (
        https_status_codes is None
        or not https_status_codes <= HTTPS_PROBE_STATUS_CODES
        or http_status_codes is None
        or not http_status_codes <= HTTP_REDIRECT_STATUS_CODES
        or probe.get("requireHttpRedirect") is not True
    ):
        return False, "signed ingress probe status and redirect policy is incomplete"
    ca_bundle = resolve_path(probe.get("caBundle"), config_dir)
    if probe.get("caBundle") and not nonempty_file(ca_bundle):
        return False, "the signed ingress probe CA bundle is missing"
    https_ok, https_detail = probe_http_endpoint(
        https_url,
        ca_bundle=ca_bundle,
        expected_status_codes=https_status_codes,
    )
    if not https_ok:
        return False, https_detail
    return probe_http_endpoint(
        http_url,
        ca_bundle=None,
        expected_status_codes=http_status_codes,
        redirect_target=https_parsed,
    )


def converged_workload(item: dict[str, Any]) -> bool:
    metadata = mapping(item.get("metadata"))
    spec = mapping(item.get("spec"))
    status = mapping(item.get("status"))
    replicas = int(spec.get("replicas", 1) or 1)
    generation = int(metadata.get("generation", 0) or 0)
    observed = int(status.get("observedGeneration", 0) or 0)
    if generation and observed < generation:
        return False
    kind = str(item.get("kind", ""))
    if kind == "Deployment":
        return all(
            int(status.get(field, 0) or 0) == replicas
            for field in ("readyReplicas", "availableReplicas", "updatedReplicas")
        ) and int(status.get("unavailableReplicas", 0) or 0) == 0
    if kind == "StatefulSet":
        return all(
            int(status.get(field, 0) or 0) == replicas
            for field in ("readyReplicas", "currentReplicas", "updatedReplicas")
        )
    return False


def merged_production_values(
    base_values: Path | None,
    public_values: Path | None,
    private_values: Path | None,
) -> dict[str, Any] | None:
    if not all(nonempty_file(path) for path in (base_values, public_values, private_values)):
        return None
    try:
        return kafka_readiness.merge(
            kafka_readiness.merge(
                kafka_readiness.load_yaml(base_values),
                kafka_readiness.load_yaml(public_values),
            ),
            kafka_readiness.load_yaml(private_values),
        )
    except (OSError, TypeError, ValueError):
        return None


def expected_postgres_clusters(values: dict[str, Any]) -> int:
    databases = mapping(values.get("databases"))
    if databases.get("enabled") is not True:
        return 0
    instances = {
        name: mapping(value)
        for name, value in mapping(databases.get("instances")).items()
        if mapping(value).get("enabled") is True
    }
    topology = mapping(databases.get("topology"))
    mode = str(topology.get("mode", "per-service"))
    if mode == "per-service":
        return len(instances)
    consolidated = mapping(topology.get("consolidated"))
    if consolidated.get("enabled", True) is not True:
        return len(instances)
    if mode == "consolidated":
        return 1 if instances else 0
    if mode == "hybrid":
        included_engines = {
            str(engine) for engine in mapping(topology.get("hybrid")).get("includeEngines", [])
        }
        consolidated_sources = [
            item for item in instances.values() if str(item.get("engine", "")) in included_engines
        ]
        preserved = len(instances) - len(consolidated_sources)
        return preserved + (1 if consolidated_sources else 0)
    return 0


def validate_kafka_data_path(
    base_values: Path | None,
    public_values: Path | None,
    private_values: Path | None,
    kubeconfig: Path,
    namespace: str,
) -> tuple[bool, str]:
    values = merged_production_values(base_values, public_values, private_values)
    if values is None:
        return False, "Kafka-to-ClickHouse values inputs are unavailable"
    try:
        checks = kafka_readiness.static_checks(values) + kafka_readiness.live_checks(
            values,
            kubeconfig,
            namespace,
            True,
        )
    except (OSError, TypeError, ValueError) as exc:
        _ = exc
        return False, "Kafka-to-ClickHouse readiness inputs could not be evaluated"
    score = sum(check.weight for check in checks if check.passed)
    critical_failures = [check for check in checks if check.critical and not check.passed]
    if score != 100 or critical_failures:
        return False, "Kafka-to-ClickHouse did not pass every static and live readiness check"
    return True, "Kafka-to-ClickHouse passed all static and live readiness checks"


def validate_live(
    config: dict[str, Any],
    run_live: bool,
    *,
    base_values: Path | None = None,
    public_values: Path | None = None,
    private_values: Path | None = None,
    config_dir: Path | None = None,
) -> tuple[bool, str]:
    live = mapping(config.get("liveCluster"))
    if live.get("required") is not True:
        return False, "live-cluster verification cannot be disabled for the production gate"
    if not run_live:
        return False, "live-cluster verification was not requested"
    attestation_ok, attestation_detail = validate_attestation_window(config)
    if not attestation_ok:
        return False, attestation_detail
    evidence_base = config_dir or ROOT
    kubeconfig = resolve_path(live.get("kubeconfig"), evidence_base)
    namespace = str(live.get("namespace", "urban-platform")).strip() or "urban-platform"
    if not nonempty_file(kubeconfig):
        return False, "private kubeconfig is missing"
    kubectl = shutil.which("kubectl")
    if not kubectl:
        return False, "kubectl is unavailable on the evidence runner"
    if not kafka_readiness.kubectl_api_ready(kubectl, kubeconfig):
        return False, "authenticated Kubernetes API readyz verification failed"
    ingress_probe_ok, ingress_probe_detail = validate_ingress_probe(live, evidence_base)
    if not ingress_probe_ok:
        return False, ingress_probe_detail
    values = merged_production_values(base_values, public_values, private_values)
    if values is None:
        return False, "merged private production values are unavailable"
    kafka_values = mapping(mapping(values.get("messaging")).get("kafka"))
    strimzi_values = mapping(kafka_values.get("strimzi"))
    expected_kafka_version = str(live.get("expectedKafkaVersion", "")).strip()
    configured_kafka_version = str(strimzi_values.get("kafkaVersion", "")).strip()
    if not expected_kafka_version or expected_kafka_version != configured_kafka_version:
        return False, "signed expected Kafka version does not match the merged production configuration"
    release = mapping(config.get("release"))
    release_tag = str(release.get("tag", "")).strip()
    source_revision = str(release.get("sourceRevision", "")).strip().lower()
    deployment_id = canonical_uuid(release.get("deploymentId"), version=4)
    cluster_uid = canonical_uuid(live.get("clusterUid"))
    if deployment_id is None or cluster_uid is None:
        return False, "signed deployment ID or target cluster UID is invalid"
    release_identity = mapping(mapping(values.get("global")).get("releaseIdentity"))
    if (
        release_identity.get("enabled") is not True
        or str(release_identity.get("tag", "")).strip() != release_tag
        or str(release_identity.get("sourceRevision", "")).strip().lower() != source_revision
        or canonical_uuid(release_identity.get("deploymentId"), version=4) != deployment_id
    ):
        return False, "merged private values do not match the signed release identity"
    release_configmap, detail = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        "configmap/urban-platform-release-identity",
    )
    release_data = mapping((release_configmap or {}).get("data"))
    if (
        release_configmap is None
        or str(release_data.get("releaseTag", "")).strip() != release_tag
        or str(release_data.get("sourceRevision", "")).strip().lower() != source_revision
        or canonical_uuid(release_data.get("deploymentId"), version=4) != deployment_id
    ):
        return False, "live cluster release identity does not match the signed release"
    cluster_identity, detail = kubectl_json(kubectl, kubeconfig, None, "namespace/kube-system")
    observed_cluster_uid = canonical_uuid(
        mapping((cluster_identity or {}).get("metadata")).get("uid")
    )
    if cluster_identity is None or observed_cluster_uid != cluster_uid:
        return False, "authenticated Kubernetes cluster UID does not match signed evidence"
    if base_values is None or public_values is None or private_values is None:
        return False, "production values inputs are unavailable for runtime image verification"
    try:
        approved_images = approved_runtime_image_references(
            base_values,
            public_values,
            private_values,
        )
    except (OSError, TypeError, ValueError):
        return False, "approved production runtime image inventory could not be evaluated"
    nodes, detail = kubectl_json(kubectl, kubeconfig, None, "nodes")
    if nodes is None:
        return False, detail
    node_items = nodes.get("items", [])
    minimum_nodes = int(live.get("minimumReadyNodes", 3) or 3)
    failure_domain_label = str(live.get("failureDomainLabel", "kubernetes.io/hostname")).strip()
    healthy_nodes = []
    failure_domains: set[str] = set()
    for item in node_items:
        spec = mapping(item.get("spec"))
        status = mapping(item.get("status"))
        labels = mapping(mapping(item.get("metadata")).get("labels"))
        healthy = (
            not bool(spec.get("unschedulable"))
            and condition_is_true(status, "Ready")
            and not any(
                condition_is_true(status, condition)
                for condition in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
            )
        )
        if healthy:
            healthy_nodes.append(item)
            domain = str(labels.get(failure_domain_label, "")).strip()
            if domain:
                failure_domains.add(domain)
    if minimum_nodes < 3 or len(healthy_nodes) < minimum_nodes:
        return False, "fewer than three schedulable, pressure-free Kubernetes nodes are Ready"
    if len(failure_domains) < minimum_nodes:
        return False, "Ready Kubernetes nodes do not span the required failure domains"

    namespace_resource, detail = kubectl_json(kubectl, kubeconfig, None, f"namespace/{namespace}")
    if namespace_resource is None:
        return False, detail
    namespace_labels = mapping(mapping(namespace_resource.get("metadata")).get("labels"))
    configured_psa_version = str(
        mapping(mapping(values.get("namespace")).get("podSecurity")).get("version", "")
    ).strip()
    expected_psa_version = str(live.get("expectedPodSecurityVersion", "")).strip()
    if (
        not PSA_VERSION_RE.fullmatch(expected_psa_version)
        or expected_psa_version != configured_psa_version
        or any(
            namespace_labels.get(f"pod-security.kubernetes.io/{mode}-version") != expected_psa_version
            for mode in ("enforce", "audit", "warn")
        )
    ):
        return False, "production namespace Pod Security version labels do not match the signed pinned version"
    if any(
        namespace_labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted"
        for mode in ("enforce", "audit", "warn")
    ):
        return False, "production namespace does not enforce, audit, and warn at restricted Pod Security"

    workloads, detail = kubectl_json(kubectl, kubeconfig, namespace, "deployments,statefulsets")
    if workloads is None:
        return False, detail
    workload_items = workloads.get("items", [])
    if not workload_items:
        return False, "production workload inventory is empty"
    for item in workload_items:
        if not converged_workload(item):
            return False, "one or more production workloads are not fully rolled out"
    pods, detail = kubectl_json(kubectl, kubeconfig, namespace, "pods")
    if pods is None:
        return False, detail
    pod_items = pods.get("items", [])
    if not pod_items:
        return False, "production pod inventory is empty"
    for item in pod_items:
        spec = mapping(item.get("spec"))
        status = mapping(item.get("status"))
        phase = str(mapping(item.get("status")).get("phase", ""))
        if phase not in {"Running", "Succeeded"}:
            return False, "one or more production pods are not Running or Succeeded"
        declared_containers: list[dict[str, Any]] = []
        status_by_name: dict[str, dict[str, Any]] = {}
        for field in ("containers", "initContainers", "ephemeralContainers"):
            declared_containers.extend(
                container
                for container in spec.get(field, [])
                if isinstance(container, dict)
            )
        for field in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses"):
            for container_status in status.get(field, []):
                if isinstance(container_status, dict):
                    status_by_name[str(container_status.get("name", "")).strip()] = container_status
        if not declared_containers:
            return False, "one or more production pods declare no containers"
        for container in declared_containers:
            name = str(container.get("name", "")).strip()
            image = str(container.get("image", "")).strip()
            container_status = status_by_name.get(name, {})
            if image not in approved_images:
                return False, "one or more production pod images are outside the approved digest allowlist"
            declared_digest = resolved_image_digest(image)
            runtime_digest = resolved_image_digest(container_status.get("imageID"))
            if declared_digest is None or runtime_digest is None:
                return False, "one or more production containers have no resolved immutable runtime image ID"
            if runtime_digest != declared_digest:
                return False, "one or more production runtime image IDs do not match their approved declared digest"
        if phase == "Running":
            expected_containers = {
                str(container.get("name", "")).strip()
                for container in spec.get("containers", [])
                if isinstance(container, dict) and str(container.get("name", "")).strip()
            }
            ready_containers = {
                str(status.get("name", "")).strip()
                for status in status.get("containerStatuses", [])
                if isinstance(status, dict) and bool(status.get("ready")) and str(status.get("name", "")).strip()
            }
            if not expected_containers or ready_containers != expected_containers:
                return False, "one or more running production pods have missing or unready containers"

    storage_class_name = str(
        mapping(mapping(values.get("storageTiers")).get("hot")).get("storageClassName", "")
    ).strip()
    if not storage_class_name:
        return False, "production durable StorageClass is not configured"
    storage_class, detail = kubectl_json(
        kubectl,
        kubeconfig,
        None,
        f"storageclass/{storage_class_name}",
    )
    if (
        storage_class is None
        or storage_class.get("allowVolumeExpansion") is not True
        or storage_class.get("reclaimPolicy") != "Retain"
        or not str(storage_class.get("provisioner", "")).strip()
    ):
        return False, "production durable StorageClass is missing expansion or Retain policy"
    pvcs, detail = kubectl_json(kubectl, kubeconfig, namespace, "persistentvolumeclaims")
    pvc_items = [] if pvcs is None else pvcs.get("items", [])
    if pvcs is None or not pvc_items or any(
        mapping(item.get("status")).get("phase") != "Bound"
        or mapping(item.get("spec")).get("storageClassName") != storage_class_name
        for item in pvc_items
    ):
        return False, "one or more production PVCs are unbound or use the wrong StorageClass"

    network_policy_values = mapping(values.get("networkPolicy"))
    if (
        network_policy_values.get("enabled") is not True
        or mapping(network_policy_values.get("defaultDeny")).get("enabled") is not True
    ):
        return False, "production default-deny NetworkPolicy is not enabled in merged values"
    default_deny, detail = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        "networkpolicy/urban-platform-default-deny",
    )
    default_deny_spec = mapping((default_deny or {}).get("spec"))
    if (
        default_deny is None
        or default_deny_spec.get("podSelector") != {}
        or set(default_deny_spec.get("policyTypes", [])) != {"Ingress", "Egress"}
    ):
        return False, "production default-deny NetworkPolicy is missing or drifted"

    namespace_values = mapping(values.get("namespace"))
    quota_values = mapping(namespace_values.get("resourceQuota"))
    limit_range_values = mapping(namespace_values.get("limitRange"))
    if quota_values.get("enabled") is not True or limit_range_values.get("enabled") is not True:
        return False, "production ResourceQuota and LimitRange must both be enabled"
    quotas, detail = kubectl_json(kubectl, kubeconfig, namespace, "resourcequotas")
    expected_hard = mapping(quota_values.get("hard"))
    quota_items = [
        item for item in ([] if quotas is None else quotas.get("items", []))
        if isinstance(item, dict)
    ]
    if quotas is None or not any(resource_quota_matches(item, expected_hard) for item in quota_items):
        return False, "production ResourceQuota is missing or drifted"
    limit_ranges, detail = kubectl_json(kubectl, kubeconfig, namespace, "limitranges")
    expected_default = mapping(limit_range_values.get("default"))
    expected_default_request = mapping(limit_range_values.get("defaultRequest"))
    limit_range_items = [
        item for item in ([] if limit_ranges is None else limit_ranges.get("items", []))
        if isinstance(item, dict)
    ]
    if limit_ranges is None or not any(
        limit_range_matches(item, expected_default, expected_default_request)
        for item in limit_range_items
    ):
        return False, "production LimitRange is missing or drifted"

    pdbs, detail = kubectl_json(kubectl, kubeconfig, namespace, "poddisruptionbudgets.policy")
    pdb_items = [] if pdbs is None else pdbs.get("items", [])
    expected_pdb_names = signed_resource_names(live.get("expectedPodDisruptionBudgets"))
    if expected_pdb_names is None:
        return False, "signed expected PodDisruptionBudget inventory is missing or invalid"
    if pdbs is None or resource_names(pdb_items) != expected_pdb_names or any(
        int(mapping(item.get("status")).get("currentHealthy", 0) or 0)
        < int(mapping(item.get("status")).get("desiredHealthy", 0) or 0)
        for item in pdb_items
    ):
        return False, "one or more production disruption budgets are absent or unhealthy"

    if mapping(values.get("autoscaling")).get("enabled") is True:
        hpas, detail = kubectl_json(
            kubectl,
            kubeconfig,
            namespace,
            "horizontalpodautoscalers.autoscaling",
        )
        hpa_items = [] if hpas is None else hpas.get("items", [])
        expected_hpa_names = signed_resource_names(live.get("expectedAutoscalers"))
        if expected_hpa_names is None:
            return False, "signed expected autoscaler inventory is missing or invalid"
        if hpas is None or resource_names(hpa_items) != expected_hpa_names or any(
            not condition_is_true(mapping(item.get("status")), "AbleToScale")
            or not condition_is_true(mapping(item.get("status")), "ScalingActive")
            for item in hpa_items
        ):
            return False, "one or more production autoscalers are absent or inactive"

    ingress_values = mapping(values.get("ingress"))
    ingress_items: list[dict[str, Any]] = []
    if ingress_values.get("enabled") is not True:
        return False, "production ingress is not enabled"
    ingresses, detail = kubectl_json(kubectl, kubeconfig, namespace, "ingresses.networking.k8s.io")
    ingress_items = [
        item for item in ([] if ingresses is None else ingresses.get("items", []))
        if isinstance(item, dict)
    ]
    if ingresses is None or not ingress_items:
        return False, "production ingresses are absent"
    expected_ingress_class = str(ingress_values.get("className", "")).strip()
    if not expected_ingress_class or any(
        str(mapping(item.get("spec")).get("ingressClassName", "")).strip() != expected_ingress_class
        for item in ingress_items
    ):
        return False, "one or more production ingresses use the wrong ingress class"
    secure_ingresses = [
        item for item in ingress_items if mapping(item.get("spec")).get("tls")
    ]
    if not secure_ingresses:
        return False, "production has no TLS-enabled ingress"
    if any(
        not mapping(item.get("spec")).get("tls") and not is_http_redirect_ingress(item)
        for item in ingress_items
    ):
        return False, "a production ingress without TLS is not an explicit HTTP-to-HTTPS redirect"

    clusters, detail = kubectl_json(kubectl, kubeconfig, namespace, "clusters.postgresql.cnpg.io")
    expected_clusters = expected_postgres_clusters(values)
    declared_clusters = int(live.get("expectedPostgresClusters", expected_clusters) or 0)
    if expected_clusters < 1 or declared_clusters != expected_clusters:
        return False, "declared PostgreSQL cluster count does not match the merged production topology"
    cluster_items = [] if clusters is None else clusters.get("items", [])
    if clusters is None or len(cluster_items) != expected_clusters:
        return False, "CloudNativePG clusters are unavailable"
    for item in cluster_items:
        spec = mapping(item.get("spec"))
        status = mapping(item.get("status"))
        instances = int(spec.get("instances", 0) or 0)
        if (
            instances < 3
            or int(status.get("readyInstances", 0) or 0) != instances
            or not ready_condition(status)
            or not str(status.get("currentPrimary", "")).strip()
            or not mapping(spec.get("backup"))
        ):
            return False, "one or more PostgreSQL clusters are not Ready with three instances"

    scheduled_backups, detail = kubectl_json(
        kubectl,
        kubeconfig,
        namespace,
        "scheduledbackups.postgresql.cnpg.io",
    )
    backup_items = [] if scheduled_backups is None else scheduled_backups.get("items", [])
    if scheduled_backups is None or len(backup_items) != expected_clusters or any(
        mapping(item.get("spec")).get("suspend") is True
        or not str(mapping(item.get("spec")).get("schedule", "")).strip()
        for item in backup_items
    ):
        return False, "CloudNativePG scheduled backups are missing or suspended"

    external_secret_values = mapping(
        mapping(values.get("secretManagement")).get("externalSecrets")
    )
    expected_external_secrets: list[tuple[str, str, str, str, set[str]]] = []
    for name, value in external_secret_values.items():
        secret = mapping(value)
        target_name = str(secret.get("targetName", "")).strip()
        if secret.get("enabled") is not True or not target_name:
            continue
        required_keys = {
            str(item.get("secretKey", "")).strip()
            for item in secret.get("data", [])
            if isinstance(item, dict) and str(item.get("secretKey", "")).strip()
        }
        expected_external_secrets.append(
            (
                str(secret.get("namespace", namespace)).strip() or namespace,
                kubernetes_name(name),
                target_name,
                str(secret.get("type", "Opaque")).strip() or "Opaque",
                required_keys,
            )
        )
    if not expected_external_secrets:
        return False, "production ExternalSecret inventory is empty"
    for secret_namespace, external_secret_name, target_name, target_type, required_keys in expected_external_secrets:
        external_secret, detail = kubectl_json(
            kubectl,
            kubeconfig,
            secret_namespace,
            f"externalsecret/{external_secret_name}",
        )
        if external_secret is None or not ready_condition(mapping(external_secret.get("status"))):
            return False, "one or more expected production ExternalSecrets are not Ready"
        actual_target_name = str(
            mapping(mapping(external_secret.get("spec")).get("target")).get("name", "")
        ).strip()
        if actual_target_name != target_name:
            return False, "one or more production ExternalSecrets target the wrong Secret"
        target_secret, detail = kubectl_json(
            kubectl,
            kubeconfig,
            secret_namespace,
            f"secret/{kubernetes_name(target_name)}",
        )
        target_data = mapping((target_secret or {}).get("data"))
        if (
            target_secret is None
            or target_secret.get("type") != target_type
            or not required_keys
            or any(not valid_encoded_secret_data(target_data.get(key)) for key in required_keys)
        ):
            return False, "one or more production ExternalSecrets did not materialize complete target Secrets"

    ingress_tls = mapping(mapping(values.get("ingress")).get("tls"))
    external_tls = mapping(
        mapping(mapping(values.get("secretManagement")).get("externalSecrets")).get("ingressTls")
    )
    cert_manager = mapping(ingress_tls.get("certManager"))
    if ingress_tls.get("enabled") is not True:
        return False, "production ingress TLS is not enabled"
    tls_secret_name = str(ingress_tls.get("secretName", "urban-platform-tls")).strip()
    if not tls_secret_name:
        return False, "production ingress TLS Secret name is missing"
    if any(
        str(mapping(tls_entry).get("secretName", "")).strip() != tls_secret_name
        for item in ingress_items
        for tls_entry in mapping(item.get("spec")).get("tls", [])
        if isinstance(tls_entry, dict)
    ):
        return False, "one or more production ingresses reference the wrong TLS Secret"
    if external_tls.get("enabled") is True:
        external_tls_name = str(external_tls.get("targetName", "")).strip()
        external_tls_namespace = str(external_tls.get("namespace", namespace)).strip() or namespace
        if external_tls_name != tls_secret_name:
            return False, "production ingress TLS ExternalSecret target does not match the ingress Secret"
        external_tls_resource, detail = kubectl_json(
            kubectl,
            kubeconfig,
            external_tls_namespace,
            f"externalsecret/{kubernetes_name('ingressTls')}",
        )
        if external_tls_resource is None or not ready_condition(mapping(external_tls_resource.get("status"))):
            return False, "the production ingress TLS ExternalSecret is absent or not Ready"
        tls_secret, detail = kubectl_json(
            kubectl,
            kubeconfig,
            external_tls_namespace,
            f"secret/{kubernetes_name(tls_secret_name)}",
        )
        if not valid_tls_secret(tls_secret):
            return False, "the production ingress TLS Secret is absent, not a TLS Secret, or incomplete"
    else:
        if cert_manager.get("enabled") is not True:
            return False, "production ingress TLS has no ExternalSecret or cert-manager owner"
        certificates, detail = kubectl_json(
            kubectl,
            kubeconfig,
            namespace,
            "certificates.cert-manager.io",
        )
        certificate_items = [] if certificates is None else certificates.get("items", [])
        owned_certificates = [
            item
            for item in certificate_items
            if str(mapping(item.get("spec")).get("secretName", "")).strip() == tls_secret_name
        ]
        if certificates is None or not owned_certificates or any(
            not ready_condition(mapping(item.get("status"))) for item in owned_certificates
        ):
            return False, "the production ingress TLS certificate is absent or not Ready"
        tls_secret, detail = kubectl_json(
            kubectl,
            kubeconfig,
            namespace,
            f"secret/{kubernetes_name(tls_secret_name)}",
        )
        if not valid_tls_secret(tls_secret):
            return False, "the production ingress TLS Secret is absent, not a TLS Secret, or incomplete"

    kafka_ok, kafka_detail = validate_kafka_data_path(
        base_values,
        public_values,
        private_values,
        kubeconfig,
        namespace,
    )
    if not kafka_ok:
        return False, kafka_detail
    return True, "short-lived signed deployment and cluster identities, approved runtime images, three failure-domain nodes, converged workloads, PostgreSQL backups, secrets, TLS, and the Kafka-to-ClickHouse path passed live checks"


def report(checks: list[tuple[str, int, bool, str]], image_count: int, dr_count: int) -> str:
    score = sum(weight for _, weight, passed, _ in checks if passed)
    result = "PASS" if score == 100 else "FAIL"
    lines = [
        "# Production Evidence Gate",
        "",
        "This report is public-safe. Private paths, kubeconfig contents, credentials, node addresses, and evidence bodies are intentionally omitted.",
        "",
        f"- Result: `{result}`",
        f"- Operational evidence score: `{score}/100`",
        f"- Promoted image entries checked: `{image_count}`",
        f"- DR/BCP artifacts checked: `{dr_count}`",
        "",
        "## Checks",
        "",
        "| Check | Weight | Status | Detail |",
        "|---|---:|---|---|",
    ]
    for name, weight, passed, detail in checks:
        lines.append(f"| {name} | {weight} | {'PASS' if passed else 'FAIL'} | {detail} |")
    lines.extend(
        [
            "",
            "The gate is fail-closed. A repository render or plan does not substitute for private promotion records, restore drills, or live-cluster verification.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate signed private production evidence and mandatory live Kubernetes health.")
    parser.add_argument("--config", default="/var/lib/urban-platform/private/production-evidence.yaml")
    parser.add_argument("--trust-policy", default="/var/lib/urban-platform/private/production-evidence-trust.yaml")
    parser.add_argument("--base-values", default="helm/urban-platform-infra/values.yaml")
    parser.add_argument("--values", default="helm/urban-platform-infra/values-production.yaml")
    parser.add_argument("--output", default="reports/production-evidence-gate.md")
    parser.add_argument("--live", action="store_true", help="Run read-only kubectl checks described by the private manifest.")
    parser.add_argument("--redact-sensitive", action="store_true", help="Accepted for compatibility; sensitive output is always redacted.")
    args = parser.parse_args(argv)

    config_path = resolve_path(args.config, ROOT)
    trust_policy_path = resolve_path(args.trust_policy, ROOT)
    base_values = resolve_path(args.base_values, ROOT)
    public_values = resolve_path(args.values, ROOT)
    output = resolve_path(args.output, ROOT)
    if output is None:
        raise SystemExit("--output must not be empty")
    output.parent.mkdir(parents=True, exist_ok=True)

    checks: list[tuple[str, int, bool, str]] = []
    image_count = 0
    dr_count = 0
    config: dict[str, Any] = {}
    if config_path is None or not config_path.is_file():
        checks = [
            ("Evidence manifest and release identity", 15, False, "private evidence manifest is unavailable"),
            ("Private image promotion evidence", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Disaster recovery and restore evidence", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Live cluster verification", 25, False, "not assessed because the evidence manifest is unavailable"),
            ("Evidence contract integrity", 10, False, "not assessed because the evidence manifest is unavailable"),
        ]
    else:
        try:
            config = load_yaml(config_path)
            config_valid = int(config.get("version", 0) or 0) == 4
            trust_ok, trust_detail, trust_policy = validate_trust_policy(trust_policy_path, config_path)
            trusted_approvers = trust_policy.trusted_approvers if trust_policy else frozenset()
            checks.append(("Evidence manifest and release identity", 15, config_valid, "signed private evidence manifest is present" if config_valid else "evidence manifest version is unsupported"))
            attestation_ok, attestation_detail = validate_attestation_window(config)
            release_ok, release_detail, private_values = validate_release(config, config_path.parent)
            source_ok, source_detail = validate_source_checkout(
                mapping(config.get("release")).get("sourceRevision")
            )
            identity_ok = config_valid and trust_ok and attestation_ok and release_ok and source_ok
            identity_detail = release_detail if identity_ok else (
                "evidence manifest version is unsupported"
                if not config_valid
                else trust_detail
                if not trust_ok
                else attestation_detail
                if not attestation_ok
                else release_detail
                if not release_ok
                else source_detail
            )
            checks[-1] = ("Evidence manifest and release identity", 15, identity_ok, identity_detail)
            if base_values is None or public_values is None or not nonempty_file(base_values) or not nonempty_file(public_values):
                image_ok, image_detail, image_count = False, "public production values inputs are unavailable", 0
            else:
                image_ok, image_detail, image_count = validate_registry(
                    config,
                    config_path.parent,
                    base_values,
                    public_values,
                    private_values,
                    trusted_approvers,
                )
            checks.append(("Private image promotion evidence", 25, image_ok, image_detail))
            dr_ok, dr_detail, dr_count = validate_dr(config, config_path.parent, trusted_approvers)
            checks.append(("Disaster recovery and restore evidence", 25, dr_ok, dr_detail))
            live_ok, live_detail = validate_live(
                config,
                args.live,
                base_values=base_values,
                public_values=public_values,
                private_values=private_values,
                config_dir=config_path.parent if config_path is not None else None,
            )
            checks.append(("Live cluster verification", 25, live_ok, live_detail))
            live_contract = mapping(config.get("liveCluster"))
            ingress_probe_contract = mapping(live_contract.get("ingressProbe"))
            contract_complete = all(
                bool(config.get(section))
                for section in ("attestation", "release", "registry", "disasterRecovery", "liveCluster")
            ) and live_contract.get("required") is True and ingress_probe_contract.get("required") is True and trust_ok and attestation_ok and source_ok
            checks.append(("Evidence contract integrity", 10, config_valid and contract_complete, "short-lived cluster-bound evidence, clean source identity, independent trust policy, and mandatory live verification are present" if config_valid and contract_complete else "signed evidence contract, trust policy, source identity, or mandatory live verification is incomplete"))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            checks = [
                ("Evidence manifest and release identity", 15, False, "private evidence manifest could not be loaded"),
                ("Private image promotion evidence", 25, False, "not assessed after manifest load failure"),
                ("Disaster recovery and restore evidence", 25, False, "not assessed after manifest load failure"),
                ("Live cluster verification", 25, False, "not assessed after manifest load failure"),
                ("Evidence contract integrity", 10, False, "evidence manifest is invalid"),
            ]
            _ = exc
    output.write_text(report(checks, image_count, dr_count), encoding="utf-8")
    score = sum(weight for _, weight, passed, _ in checks if passed)
    print(f"Production evidence gate report written: {output}")
    print(f"Operational evidence score: {score}/100")
    return 0 if score == 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
