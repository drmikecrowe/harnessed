"""Guard against JSON-schema ↔ parser drift.

Every catalog manifest declares `# yaml-language-server: $schema=…/schemas/<kind>.schema.json`, which
editors validate against. Those JSON schemas are hand-maintained alongside the authoritative Python
parser in `schema.py` and CAN silently drift (the recipe schema once described `persist` as an
object and omitted `init:`, so every recipe with the current shapes showed editor errors while the
runtime happily loaded them).

This module validates (1) each schema is itself well-formed, (2) every shipped catalog manifest
validates against its schema — so a future parser change that isn't mirrored into the JSON schema
fails here instead of in someone's editor — and (3) every manifest names its schema by the canonical
raw-GitHub URL.

(3) exists because that ref used to be a path RELATIVE to the manifest (`../../../schemas/...`),
which resolves ONLY inside a source checkout. It resolved to nothing in the user overlay
(~/.config/harnessed/catalog/... has no sibling schemas/), nothing in a `uv tool` install (the wheel
ships no schemas/, and site-packages moves every upgrade), and there is no on-disk path to point at
under `uvx` at all — its environment is ephemeral. An absolute URL is the only form that resolves
from all four, at any manifest depth. Copying an old header back in is the likely regression, hence
the guard.
"""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

_ROOT = Path(__file__).resolve().parent.parent
_yaml = YAML(typ="safe", pure=True)

# kind -> (schema path, catalog subdir, manifest filename)
_KINDS = {
    "recipe": ("schemas/recipe.schema.json", "catalog/recipes", "recipe.yaml"),
    "stack": ("schemas/stack.schema.json", "catalog/stacks", "stack.yaml"),
    "service": ("schemas/service.schema.json", "catalog/services", "service.yaml"),
    "agent": ("schemas/agent.schema.json", "catalog/agents", "agent.yaml"),
}


# The canonical `$schema` ref. Pinned to `main` deliberately: an editor hint must describe the parser
# you are authoring against, and the "pin every download" rule covers image-build inputs, not this.
_SCHEMA_URL = "https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/{kind}.schema.json"


def _manifests(kind: str):
    """Every manifest of `kind`, INCLUDING recipe varieties one level deeper.

    A recipe family (catalog/recipes/beads/) has no manifest of its own; its children do
    (beads/stealth/recipe.yaml → the `beads/stealth` ref). A one-level glob alone would skip them.
    """
    _, subdir, fn = _KINDS[kind]
    base = _ROOT / subdir
    if not base.is_dir():
        return []
    return sorted({*base.glob(f"*/{fn}"), *base.glob(f"*/*/{fn}")})


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
def test_manifest_declares_the_canonical_schema_url(kind, manifest):
    """An absolute URL, never a manifest-relative path — see the module docstring."""
    hint = f"# yaml-language-server: $schema={_SCHEMA_URL.format(kind=kind)}"
    text = manifest.read_text()
    assert hint in text, f"{manifest} must declare:\n{hint}"
    assert "$schema=../" not in text, f"{manifest} still has a manifest-relative $schema ref"


@pytest.mark.parametrize("kind,manifest", _all_manifests())
def test_catalog_manifest_matches_its_json_schema(kind, manifest):
    validator = Draft202012Validator(_schema(kind))
    data = _yaml.load(manifest.read_text())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        f"@ {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors
    )
