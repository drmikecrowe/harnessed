"""Compose a stack from a recipe set at launch time, without authoring a stack.yaml.

The name is derived from the CONTENT of the recipe set, so the same set resolves to the same stack
in every repo that asks for it — one image, one pair of volumes, shared. That is what stops ad-hoc
composition from multiplying build artifacts.

A real `stack.yaml` is minted rather than passing a recipe list straight to the assembler because
profile location, volume labels, staleness checks, `harnessed list`, and BOTH garbage collectors are
already keyed on "a stack that resolves in the catalog". Minting the file makes all of them work
unchanged; skipping it would mean teaching five subsystems about a new kind of thing.
"""
from __future__ import annotations

import hashlib
import re

from pathlib import Path

from . import paths

# Names appear in `harnessed list`, volume labels and podman image tags. The cap keeps a
# pathological set from producing an unwieldy (or illegal) directory name.
NAME_MAX = 64
_HASH_LEN = 8

# The name is interpolated into a podman tag by `_derived_image` on the build path
# (`harnessed-<harness>-<stack>:latest`), so it must satisfy the OCI name-component grammar:
# alphanumerics separated by `.`, `_`, `__` or runs of `-`, with no leading or trailing separator.
# That alphabet is STRICTLY SMALLER than a filesystem's, and podman rejects a bad tag at build time
# — which the suite cannot catch, because it runs no podman. Hence:
#
#   _JOIN must be legal in a tag AND impossible for _sanitize to emit. If a sanitized ref could
#   contain the separator, `["a<sep>b", "c"]` and `["a", "b<sep>c"]` would both join to
#   `a<sep>b<sep>c` with neither flagged lossy — a silent collision onto one manifest, one image
#   and one pair of volumes.
#
# `.` and `_` are the only tag-legal separators, so the sanitizer's output alphabet is narrowed to
# `[a-z0-9-]` and `.` is reserved for the join. Folding `_` and `.` into `-` also closes a second
# hole: a ref like `_foo` or `.foo` would otherwise survive intact and produce a component starting
# with a separator, which the grammar forbids. No catalog recipe name contains `.` or `_`, so this
# costs nothing in readability.
_JOIN = "."
_UNSAFE = re.compile(r"[^a-z0-9-]+")


def normalize(recipes: list[str], extends: str | None) -> tuple[str | None, tuple[str, ...]]:
    """Deduped, sorted recipe refs plus the base — the canonical form the name is derived from.

    Sorting is what makes `--recipe a --recipe b` and `--recipe b --recipe a` the same stack.
    """
    return extends, tuple(sorted({r.strip() for r in recipes if r.strip()}))


# Components that would escape or collapse the target directory. An all-unsafe ref like `***`, and
# now `.`/`..` too (the narrowed alphabet folds their dots to `-`, which the trailing strip then
# removes), sanitize to the empty string; mint would write to the stacks dir itself or to its PARENT
# instead of a stack of its own. `.` and `..` stay listed because the check must hold whatever the
# alphabet is — they are the names that are dangerous, not the route by which they arrive.
_RESERVED = frozenset({"", ".", ".."})


def _sanitize(ref: str) -> str:
    """A catalog ref reduced to one legal path component (`fam/var` -> `fam-var`).

    LOSSY BY DESIGN: it lowercases and folds every unsafe character to `-`, so `Foo`/`foo` and
    `foo bar`/`foo-bar` collapse together. `derive_name` detects that loss and appends a digest —
    do not try to make this reversible, because a path component genuinely cannot carry those
    characters.
    """
    return _UNSAFE.sub("-", ref.strip().lower().replace("/", "-")).strip("-")


def _normalize_services(services: list[str] | None) -> tuple[str, ...]:
    """Deduped, sorted service names — the THIRD input to a stack's identity, alongside the base
    and the recipe set. `run --service` writes these into the manifest, so two invocations that
    differ only here are genuinely different stacks."""
    return tuple(sorted({s.strip() for s in (services or []) if s.strip()}))


def _digest(base: str | None, refs: tuple[str, ...], svcs: tuple[str, ...] = ()) -> str:
    """Stable short hash over the canonical form — computed from the UNSANITIZED inputs, so two
    sets that sanitize to the same string still hash differently.

    The `\\x1f` between groups keeps `(refs=("a","b"), svcs=())` distinct from
    `(refs=("a",), svcs=("b",))`, which a single flat join would collapse.
    """
    payload = "\x00".join([base or "", *refs]) + "\x1f" + "\x00".join(svcs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_HASH_LEN]


def derive_name(recipes: list[str], extends: str | None, services: list[str] | None = None) -> str:
    """The deterministic stack name for this recipe set.

    Readable join by default. A hash is appended when the readable form is not a faithful encoding
    of the input — because a ref had to be sanitized (lossy: `fam/var` and `fam-var` both
    flatten to `fam-var`), because the join exceeded NAME_MAX, or because explicit `services`
    were selected.

    `services` MUST be passed by every caller that will hand the same list to `mint`. They are not
    part of the readable join — that would bloat every name for a rarely-used escape hatch — so the
    digest is the only thing that can distinguish them, and omitting them here lets two different
    service selections mint over each other's manifest and share one image and volume pair.
    """
    base, refs = normalize(recipes, extends)
    if not refs:
        raise ValueError("a dynamic stack needs at least one recipe")
    svcs = _normalize_services(services)

    values = ([base] if base is not None else []) + list(refs)
    parts = [_sanitize(v) for v in values]

    for original, clean in zip(values, parts, strict=True):
        if clean in _RESERVED:
            raise ValueError(
                f"catalog ref {original!r} does not yield a usable stack-name component"
            )

    readable = _JOIN.join(parts)
    # Any value whose sanitized form differs from the original has LOST information, so the readable
    # join is no longer a faithful encoding and two different sets could land on one name. Checking
    # only for "/" missed case folding (`Foo` vs `foo`) and space folding (`foo bar` vs `foo-bar`).
    lossy = any(clean != original for original, clean in zip(values, parts, strict=True))

    # `svcs` forces a digest for the reason in the docstring: services never appear in the readable
    # join, so without this the digest is their only carrier and it would not be emitted.
    if not lossy and not svcs and len(readable) <= NAME_MAX:
        return readable

    suffix = "-" + _digest(base, refs, svcs)
    # Truncation can land mid-component and leave a trailing separator, which the grammar forbids
    # directly before the suffix's `-`. Strip both the join char and `-`.
    return readable[: NAME_MAX - len(suffix)].rstrip(_JOIN + "-") + suffix


def mint(
    recipes: list[str], extends: str | None, services: list[str] | None = None
) -> tuple[str, Path]:
    """Write (or refresh) the generated stack.yaml for this recipe set. Returns (name, stack_dir).

    Idempotent: identical inputs rewrite identical bytes, so a repeat launch does not perturb the
    staleness check. Writes only when the content differs, so the file's mtime tracks real change.
    """
    base, refs = normalize(recipes, extends)
    svcs = _normalize_services(services)
    name = derive_name(recipes, extends, services)

    # An AUTHORED stack of the same name wins resolution — the generated root is deliberately last
    # in precedence — so `find_in_catalog` would hand both build and launch the authored manifest
    # while this one sat ignored, and `run` would silently execute something the user did not ask
    # for. Refuse rather than shadow. (Reported on PR #176.)
    existing = paths.find_in_catalog("stacks", name)
    generated_root = paths.generated_catalog_root().resolve()
    if (existing / "stack.yaml").is_file() and not existing.resolve().is_relative_to(generated_root):
        raise ValueError(
            f"derived name {name!r} collides with an authored stack at {existing} — that stack "
            f"would win resolution and be launched instead. Rename it, or change the recipe set."
        )

    stack_dir = paths.generated_catalog_root() / "stacks" / name
    stack_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# GENERATED by `harnessed run` — do not edit.",
        "# Regenerated from its recipe set on every launch; hand edits are lost. The name is derived",
        "# from the content, so an identical recipe set in another repo resolves to this same stack.",
        "# A stack manifest rejects unknown fields, so 'generated' is a comment, not a key: what",
        "# marks this stack machine-made is its LOCATION under the generated catalog root.",
        f"name: {name}",
    ]
    if base:
        lines.append(f"extends: {base}")
    lines.append("recipes:")
    lines.extend(f"  - {r}" for r in refs)
    if svcs:
        lines.append("services:")
        lines.extend(f"  - {s}" for s in svcs)
    else:
        lines.append("services: []")

    content = "\n".join(lines) + "\n"
    manifest = stack_dir / "stack.yaml"
    if not manifest.is_file() or manifest.read_text(encoding="utf-8") != content:
        manifest.write_text(content, encoding="utf-8")
    return name, stack_dir
