#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DIGEST_RE = re.compile(r'^sha256:[A-Fa-f0-9]{64}$')
COMPOSE_DEFAULT_RE = re.compile(
    r'\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<operator>:-|-)?(?P<default>[^}]*)\}'
)


def as_text(value: Any) -> str:
    return str(value).strip()


def load_yaml(path: str) -> Any:
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))


def is_mutable_tag(tag: str, blocked: set[str]) -> bool:
    normalized = tag.strip()
    return normalized in blocked or normalized.startswith('latest-') or normalized.endswith('-latest')


def resolve_compose_default_variables(image: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group('operator'):
            return match.group('default')
        return match.group(0)

    return COMPOSE_DEFAULT_RE.sub(replace, image)


def parse_image_ref(image: str) -> tuple[str, str | None, str | None]:
    value = resolve_compose_default_variables(image.strip())
    if '@' in value:
      repository, digest = value.rsplit('@', 1)
      return repository, None, digest
    slash = value.rfind('/')
    colon = value.rfind(':')
    if colon > slash:
        return value[:colon], value[colon + 1:], None
    return value, None, None


def walk(value: Any, path: str = ''):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            child_path = f'{path}.{key}' if path else str(key)
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f'{path}[{index}]')


def image_objects_from_values(values: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    objects = []
    for path, value in walk(values):
        if isinstance(value, dict) and 'repository' in value and ('tag' in value or 'digest' in value):
            objects.append((path, value))
    return objects


def image_refs_from_yaml(path: str) -> list[tuple[str, str]]:
    loaded = load_yaml(path)
    refs: list[tuple[str, str]] = []
    for item_path, value in walk(loaded):
        if not isinstance(value, dict):
            continue
        image = value.get('image')
        if isinstance(image, str):
            refs.append((f'{path}:{item_path}.image', image))
        images = value.get('images')
        if isinstance(images, list):
            for index, candidate in enumerate(images):
                if isinstance(candidate, str):
                    refs.append((f'{path}:{item_path}.images[{index}]', candidate))
    return refs


def image_refs_from_compose(path: str) -> list[tuple[str, str]]:
    loaded = load_yaml(path)
    refs: list[tuple[str, str]] = []
    for name, service in loaded.get('services', {}).items():
        image = service.get('image')
        if isinstance(image, str):
            refs.append((f'{path}:services.{name}.image', image))
    return refs


def main() -> int:
    errors: list[str] = []
    policy = load_yaml('config/image-policy.yaml')['policy']
    blocked = {as_text(tag) for tag in policy['disallowMutableTags']}
    default_app_tag = as_text(policy['defaultApplicationTag'])
    approved = {
        (as_text(item['repository']), as_text(item['tag']))
        for item in policy['approvedRuntimeImages']
    }

    values = load_yaml('helm/urban-platform-infra/values.yaml')
    for path, image in image_objects_from_values(values):
        repository = as_text(image.get('repository', ''))
        tag = image.get('tag')
        digest = image.get('digest')
        if not repository:
            errors.append(f'{path}: image.repository is required')
        if tag is None and digest is None:
            errors.append(f'{path}: image.tag or image.digest is required')
            continue
        if tag is not None:
            tag_text = as_text(tag)
            if is_mutable_tag(tag_text, blocked):
                errors.append(f'{path}: mutable image tag is not allowed: {repository}:{tag_text}')
            if repository.startswith('example-app-') and tag_text != default_app_tag:
                errors.append(f'{path}: placeholder app image must use sanitized tag {default_app_tag}')
            if not repository.startswith('example-app-') and (repository, tag_text) not in approved:
                errors.append(f'{path}: runtime image is not approved by config/image-policy.yaml: {repository}:{tag_text}')
        if digest is not None and not DIGEST_RE.fullmatch(as_text(digest)):
            errors.append(f'{path}: image.digest must be a sha256 digest')

    for source in [
        *image_refs_from_yaml('config/services.catalog.yaml'),
        *image_refs_from_yaml('config/webservers.yaml'),
        *image_refs_from_yaml('config/databases.catalog.yaml'),
        *image_refs_from_compose('compose/docker-compose.ha.yml'),
    ]:
        path, image_ref = source
        repository, tag, digest = parse_image_ref(image_ref)
        if tag is None and digest is None:
            errors.append(f'{path}: image ref must include an explicit tag or digest: {image_ref}')
            continue
        if tag is not None:
            if is_mutable_tag(tag, blocked):
                errors.append(f'{path}: mutable image tag is not allowed: {image_ref}')
            if repository.startswith('example-app-') and tag != default_app_tag:
                errors.append(f'{path}: placeholder app image must use sanitized tag {default_app_tag}')
            if not repository.startswith('example-app-') and (repository, tag) not in approved:
                errors.append(f'{path}: runtime image is not approved by config/image-policy.yaml: {image_ref}')
        if digest is not None and not DIGEST_RE.fullmatch(digest):
            errors.append(f'{path}: image digest must be sha256: {image_ref}')

    if errors:
        for error in errors:
            print(f'IMAGE-POLICY: {error}', file=sys.stderr)
        return 1
    print('Image policy checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
