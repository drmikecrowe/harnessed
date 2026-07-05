"""Guard against JSON-schema ↔ parser drift.

Every catalog manifest declares `# yaml-language-server: $schema=…/schemas/<kind>.schema.json`, which
editors validate against. Those JSON schemas are hand-maintained alongside the authoritative Python
parser in `schema.py` and CAN silently drift (the recipe schema once described `persist` as an
object and omitted `init:`, so every recipe with the current shapes showed editor errors while the
runtime happily loaded them).

This module validates (1) each schema is itself well-formed, and (2) every shipped catalog manifest
validates against its schema — so a future parser change that isn't mirrored into the JSON schema
fails here instead of in someone's editor.
"""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402
from ruamel.yaml import YAML  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_yaml = YAML(typ="safe", pure=True)

# kind -> (schema path, catalog subdir, manifest filename)
_KINDS = {
    "recipe": ("schemas/recipe.schema.json", "catalog/recipes", "recipe.yaml"),
    "stack": ("schemas/stack.schema.json", "catalog/stacks", "stack.yaml"),
    "service": ("schemas/service.schema.json", "catalog/services", "service.yaml"),
    "agent": ("schemas/agent.schema.json", "catalog/agents", "agent.yaml"),
}


def _manifests(kind: str):
    _, subdir, fn = _KINDS[kind]
    base = _ROOT / subdir
    if not base.is_dir():
        return []
    return sorted(d / fn for d in base.iterdir() if (d / fn).is_file())


def _schema(kind: str) -> dict:
    return json.loads((_ROOT / _KINDS[kind][0]).read_text())


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_schema_is_well_formed(kind):
    Draft202012Validator.check_schema(_schema(kind))


def _all_manifests():
    return [
        pytest.param(kind, f, id=f"{kind}:{f.parent.name}")
        for kind in sorted(_KINDS)
        for f in _manifests(kind)
    ]


@pytest.mark.parametrize("kind,manifest", _all_manifests())
def test_catalog_manifest_matches_its_json_schema(kind, manifest):
    validator = Draft202012Validator(_schema(kind))
    data = _yaml.load(manifest.read_text())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        f"@ {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors
    )
