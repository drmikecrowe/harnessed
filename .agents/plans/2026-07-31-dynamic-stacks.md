# Dynamic Stacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user compose a stack from a recipe list at launch time (`harnessed run --recipe a --recipe b claude`) instead of authoring a `stack.yaml`, so the only stack anyone writes by hand is their `default`.

**Architecture:** `harnessed run` normalizes a recipe set into a deterministic content-derived name, mints a real `stack.yaml` under a new generated catalog root (`$XDG_DATA_HOME/harnessed/generated/`), builds it if needed, and delegates to the existing launch path. Minting a real manifest is the point: profile location, volume labels, staleness checks, `harnessed list`, and both GCs are already keyed on "a stack that resolves in the catalog", so they all keep working untouched. A prerequisite change lets a recipe declare the services it requires, without which a recipe-only list cannot reproduce a working beads stack.

**Tech Stack:** Python 3, Typer (CLI), ruamel.yaml (manifest parsing), pytest, podman.

## Global Constraints

- Beads epic: `harnessed-7rx`. Read `bd show harnessed-7rx` for the recorded design and the rejected alternatives before starting.
- **Never commit to `main`.** Work in a worktree; sign every commit (`git commit -S`). See `.claude/rules/signed-commits`.
- **Run tests with `tools/run-tests.sh`** — never hand-compose `mise`/`uv`/`pytest`. `tools/run-tests.sh tests/test_schema.py` for one file; `tools/run-tests.sh -k name -x` to filter.
- **Record the baseline test count before your first change.** A drop is a regression even if your new tests pass.
- `catalog/` ships inside the wheel: nothing host-local may be written into it, and nothing may key off the CWD. Anchor to `paths.harnessed_home()`.
- Stack manifests **reject unknown fields** (`schema.py` `_KNOWN_STACK_FIELDS`). A generated stack therefore carries **no** marker field — it is identified by its location alone.
- JSON schemas in `schemas/` are hand-maintained and have `"additionalProperties": false`. `tests/test_catalog_json_schemas.py` validates every shipped manifest against them, so any new manifest field must be mirrored there in the same commit.

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `src/harnessed/schema.py` | `services:` on `Recipe`; parser; field whitelist | Modify |
| `schemas/recipe.schema.json` | Editor-facing mirror of the recipe parser | Modify |
| `catalog/recipes/beads/team/recipe.yaml` | Declare its own `beads-server` | Modify |
| `catalog/recipes/beads/stealth/recipe.yaml` | Declare its own `beads-server` | Modify |
| `src/harnessed/launcher.py` | `_service_refs` union; `run` command; `_COMMANDS` | Modify |
| `src/harnessed/paths.py` | `generated_catalog_root()`; third catalog root | Modify |
| `src/harnessed/dynstack.py` | **New.** Normalize a recipe set, derive its name, mint its manifest. Kept out of `launcher.py`, which is already ~7000 lines. | Create |
| `tests/test_dynstack.py` | **New.** Naming + minting unit tests | Create |
| `tests/test_schema.py` | Recipe `services:` parsing | Modify |
| `tests/test_paths.py` | Generated root precedence + enumeration | Modify or create |
| `ARCHITECTURE.md` | Two catalog roots become three; document `run` | Modify |

**Module boundary — this is the seed for the launcher.py split (bd `harnessed-4l8`).** `launcher.py`
is 7016 lines, 53% of the codebase, with 20 commands and 179 private helpers. `dynstack.py` is
deliberately the first module extracted under the rule that split should follow:

> Pure, derivable logic lives in a focused module. `launcher.py` keeps only the Typer surface and
> podman orchestration. Command bodies stay thin and delegate immediately. Dependencies point
> **into** the modules, never back out.

`dynstack.py` has no launcher import and its tests never construct a CLI runner or touch podman —
that is what makes it an exemplar rather than just another file. Task 3 ships a test asserting the
direction, because a documented convention with no enforcement erodes at the third extraction.

Note what is deliberately **not** moved: the `run` command itself. It needs `_build_stack`,
`_runtime`, `launch`, `_require_supported_harness` and `_err`, so a module holding it could only
resolve those through an import cycle or an indirection layer. Commands are the most coupled things
in `launcher.py`; starting a refactor there buys a hard problem and a bad precedent. Start with pure
logic, keep the command thin (Task 4's `run` body is ~15 lines), and let 4l8 extend the pattern.

---

### Task 0: Baseline

- [ ] **Step 1: Record the passing test count**

Run: `tools/run-tests.sh 2>&1 | tail -5`

Expected: `1626 passed, 21 skipped` — measured on this branch at plan time (2026-07-31). If your number differs, use **yours** as the baseline and note the discrepancy; the arithmetic in later tasks (`baseline + N`) is what matters, not the absolute figure.

Write the summary line into the epic so a later drop is detectable:

```bash
bd update harnessed-7rx --notes="Baseline before dynamic-stacks work: <paste summary line>"
```

Expected: a green run. If it is not green before you touch anything, stop and report — do not start on a red baseline.

---

### Task 1: Recipes declare their own services

Bead: `harnessed-7rx.1`. This is a prerequisite, not a cleanup — `beads-server` speaks MySQL, has no MCP surface, and so cannot ride `McpServer.service`. Today only a stack can attach it, and both beads recipes work around that by failing at runtime with a message telling you to hand-edit a stack file.

**Files:**
- Modify: `src/harnessed/schema.py` (add parser near `_parse_conflicts` at :812; `KNOWN_RECIPE_FIELDS` at :1075; `Recipe` dataclass at :827; `load_recipe` return at :1350)
- Modify: `src/harnessed/launcher.py:3182-3200` (`_service_refs`)
- Modify: `schemas/recipe.schema.json`
- Modify: `catalog/recipes/beads/team/recipe.yaml`, `catalog/recipes/beads/stealth/recipe.yaml`
- Test: `tests/test_schema.py`, `tests/test_launcher_services.py` (create if absent)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Recipe.services: list[str]` — the service names a recipe requires. `_service_refs(stack: str) -> list[str]` keeps its existing signature and return type; only its sources widen.

- [ ] **Step 1: Write the failing parser tests**

Append to `tests/test_schema.py`, following the `TestRecipeConflicts` pattern already at :886:

```python
class TestRecipeServices:
    def test_parse_defaults_to_empty(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\n")
        assert load_recipe(d).services == []

    def test_parse_services_list(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nservices: [beads-server]\n")
        assert load_recipe(d).services == ["beads-server"]

    def test_non_list_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nservices: beads-server\n")
        with pytest.raises(SchemaError, match="'services' must be a list"):
            load_recipe(d)

    def test_empty_entry_rejected(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nservices: ['']\n")
        with pytest.raises(SchemaError, match="non-empty strings"):
            load_recipe(d)

    def test_services_is_a_known_field(self, tmp_path):
        """strict=True must NOT reject it — otherwise the field is unusable in `build`."""
        d = tmp_path / "r"
        d.mkdir()
        (d / "recipe.yaml").write_text("name: r\nservices: [beads-server]\n")
        assert load_recipe(d, strict=True).services == ["beads-server"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/run-tests.sh tests/test_schema.py -k TestRecipeServices -v`
Expected: FAIL — `AttributeError: 'Recipe' object has no attribute 'services'`, and the strict test failing with an unknown-field `SchemaError`.

- [ ] **Step 3: Add the parser**

In `src/harnessed/schema.py`, directly after `_parse_conflicts` (ends :823):

```python
def _parse_services(raw_services) -> list[str]:
    """Parse the optional `services:` list — sidecars this recipe REQUIRES.

    For a service with no MCP surface, which therefore cannot be referenced through
    `mcp.servers[].service`: a `dolt sql-server` speaks MySQL, not MCP. Before this field the
    dependency could only be declared by the STACK, so a recipe list alone could not describe a
    working stack and the beads recipes had to fail at runtime telling the user to edit one.
    Unioned with the stack's own `services:` in `launcher._service_refs`.
    """
    if not raw_services:
        return []
    if not isinstance(raw_services, list):
        raise SchemaError("recipe 'services' must be a list of service names")
    services: list[str] = []
    for entry in raw_services:
        if not isinstance(entry, str) or not entry.strip():
            raise SchemaError(f"recipe 'services' entries must be non-empty strings, got {entry!r}")
        services.append(entry.strip())
    return services
```

- [ ] **Step 4: Add the field, whitelist it, and wire it in**

In the `Recipe` dataclass (`schema.py:827`), after `conflicts` (:847):

```python
    # Sidecars this recipe REQUIRES that have no MCP surface, so they cannot be declared through
    # `mcp.servers[].service` (a dolt sql-server speaks MySQL). Unioned with the stack's own
    # `services:` by launcher._service_refs. Lets a bare recipe list describe a working stack.
    services: list[str] = field(default_factory=list)
```

In `KNOWN_RECIPE_FIELDS` (`schema.py:1075`), add `"services"` to the first (typed) line:

```python
KNOWN_RECIPE_FIELDS = frozenset({
    "name", "description", "mcp", "skills", "commands", "rules", "expect", "persist", "init",  # typed
    "conflicts", "hooks", "setup", "install", "egress", "tools", "env", "services",  # typed
    "plugins", "deps", "scripts",  # D-14 forward fields (see _recipe_raw_strings)
})
```

In the `Recipe(...)` construction inside `load_recipe` (`schema.py:1350`), beside `conflicts=`:

```python
        services=_parse_services(raw.get("services")),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `tools/run-tests.sh tests/test_schema.py -k TestRecipeServices -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Write the failing `_service_refs` test**

Create `tests/test_launcher_services.py`:

```python
"""`_service_refs` must union recipe-declared services with the stack's own.

Before harnessed-7rx.1 a service with no MCP surface (beads-server speaks MySQL) could only be
attached by a STACK, so a bare recipe list could not describe a working stack.
"""
from __future__ import annotations

import textwrap

from harnessed.launcher import _service_refs


def _catalog(tmp_path, *, recipe_services: str, stack_services: str):
    root = tmp_path / "catalog"
    rd = root / "recipes" / "r1"
    rd.mkdir(parents=True)
    (rd / "recipe.yaml").write_text(f"name: r1\n{recipe_services}")
    sd = root / "stacks" / "s1"
    sd.mkdir(parents=True)
    (sd / "stack.yaml").write_text(textwrap.dedent(f"""\
        name: s1
        recipes: [r1]
        {stack_services}
        """))
    return root


def test_recipe_declared_service_is_collected(tmp_path, monkeypatch):
    root = _catalog(tmp_path, recipe_services="services: [beads-server]\n", stack_services="services: []")
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server"]


def test_stack_and_recipe_services_are_unioned_without_duplicates(tmp_path, monkeypatch):
    root = _catalog(
        tmp_path,
        recipe_services="services: [beads-server]\n",
        stack_services="services: [beads-server, other-svc]",
    )
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server", "other-svc"]


def test_stack_only_services_still_work(tmp_path, monkeypatch):
    """Regression guard: existing stacks that declare services themselves must be unaffected."""
    root = _catalog(tmp_path, recipe_services="", stack_services="services: [beads-server]")
    monkeypatch.setattr("harnessed.paths.catalog_roots", lambda: [root])
    assert _service_refs("s1") == ["beads-server"]
```

- [ ] **Step 7: Run it to verify it fails**

Run: `tools/run-tests.sh tests/test_launcher_services.py -v`
Expected: FAIL on the first two tests — the recipe-declared service is not collected, so the list is `[]` / `["beads-server", "other-svc"]` misses nothing but the first assertion returns `[]`.

- [ ] **Step 8: Union recipe services in `_service_refs`**

In `src/harnessed/launcher.py`, inside `_service_refs` (:3182), extend the per-recipe loop and update the docstring:

```python
def _service_refs(stack: str) -> list[str]:
    """Distinct service names a stack requires as host-published sidecars.

    Three sources, unioned (first-seen order, de-duped): (1) recipe `service:` MCP-server refs
    (the assembler proxies these by URL), (2) recipe `services:` — sidecars a RECIPE requires that
    have no MCP surface, and (3) the stack's own `services:` list. (2) is what lets a bare recipe
    list describe a working stack: a `dolt sql-server` speaks MySQL, not MCP, so it can never be a
    `service:` MCP ref, and before harnessed-7rx.1 only a stack could attach it. All three feed
    `_ensure_services`, which starts each one idempotently at launch.
    """
    stk, recipes = load_stack_with_recipes(None, stack)
    names: list[str] = []
    for recipe in recipes:
        for server in recipe.servers:
            if server.service and server.service not in names:
                names.append(server.service)
        for name in recipe.services:
            if name not in names:
                names.append(name)
    for name in (stk.services if stk else []):
        if name not in names:
            names.append(name)
    return names
```

- [ ] **Step 9: Run it to verify it passes**

Run: `tools/run-tests.sh tests/test_launcher_services.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 10: Mirror the field into the JSON schema**

`schemas/recipe.schema.json` has `"additionalProperties": false`, so a `services:` key in a shipped recipe fails `tests/test_catalog_json_schemas.py` until it is described here. Add to the top-level `"properties"` object, alongside `conflicts`:

```json
    "services": {
      "type": "array",
      "description": "Sidecar services this recipe requires that have no MCP surface (e.g. beads-server, which speaks MySQL). Unioned with the stack's own services: at launch.",
      "items": { "type": "string", "minLength": 1 }
    },
```

- [ ] **Step 11: Declare the dependency in both beads recipes**

In `catalog/recipes/beads/team/recipe.yaml` and `catalog/recipes/beads/stealth/recipe.yaml`, add a top-level block. Both need it — they are two varieties running the same engine.

```yaml
# The dolt sql-server this recipe is a pure CLIENT of. `bd` never starts an engine, so without this
# service the socket never exists and `bd init` has nothing to connect to. Declared HERE rather than
# in every stack because the dependency belongs to the recipe: a MySQL server has no MCP surface, so
# it cannot be an `mcp.servers[].service` ref.
services: [beads-server]
```

- [ ] **Step 12: Run the schema-drift and full suites**

Run: `tools/run-tests.sh tests/test_catalog_json_schemas.py -v`
Expected: PASS.

Run: `tools/run-tests.sh 2>&1 | tail -5`
Expected: the Task 0 baseline count **plus 8** new tests, no failures.

- [ ] **Step 13: Commit**

```bash
git add src/harnessed/schema.py src/harnessed/launcher.py schemas/recipe.schema.json \
        catalog/recipes/beads/team/recipe.yaml catalog/recipes/beads/stealth/recipe.yaml \
        tests/test_schema.py tests/test_launcher_services.py
git commit -S -m "feat(schema): let a recipe declare the services it requires

A service with no MCP surface (beads-server speaks MySQL) could only be
attached by a stack, so a bare recipe list could not describe a working
stack and both beads recipes failed at runtime telling the user to edit
one. Union recipe services: into _service_refs alongside the stack's.

Refs: harnessed-7rx.1"
```

---

### Task 2: Generated stack root

Bead: `harnessed-7rx.2`. A third catalog root for machine-minted stacks, kept out of the authoring surface so `harnessed list` can tell them apart and a regenerated file can never clobber something you wrote.

**Files:**
- Modify: `src/harnessed/paths.py` (`catalog_roots` at :140; add `generated_catalog_root` near `profiles_root` at :243)
- Test: `tests/test_paths_generated_root.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `paths.generated_catalog_root() -> Path` returning `$XDG_DATA_HOME/harnessed/generated` — a **catalog root**, i.e. the directory that *contains* `stacks/`, matching what `catalog_roots()` entries mean everywhere else (`list_catalog` iterates `root / kind`). Generated manifests therefore land at `$XDG_DATA_HOME/harnessed/generated/stacks/<name>/stack.yaml`. `paths.catalog_roots()` gains a third entry, **last** in precedence.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths_generated_root.py`:

```python
"""The generated-stack root (harnessed-7rx.2).

Machine-minted stacks live under XDG DATA, NOT in the user's authoring overlay, so `harnessed list`
can distinguish them and a regenerated manifest can never clobber a hand-written one. It must be
enumerable, because volume-gc/host-gc define an orphan as "its stack no longer resolves".
"""
from __future__ import annotations

from harnessed import paths


def test_generated_root_is_under_xdg_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.generated_catalog_root() == tmp_path / "harnessed" / "generated"


def test_generated_root_is_a_catalog_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "harnessed" / "generated").mkdir(parents=True)
    assert paths.generated_catalog_root() in paths.catalog_roots()


def test_generated_root_loses_to_the_user_overlay(tmp_path, monkeypatch):
    """An authored stack must win over a generated one of the same name."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "data" / "harnessed" / "generated").mkdir(parents=True)
    (tmp_path / "config" / "harnessed" / "catalog").mkdir(parents=True)
    roots = paths.catalog_roots()
    assert roots.index(paths.user_catalog()) < roots.index(paths.generated_catalog_root())


def test_absent_generated_root_is_omitted(tmp_path, monkeypatch):
    """Never hand podman or the resolver a path that does not exist."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.generated_catalog_root() not in paths.catalog_roots()


def test_generated_stacks_are_enumerated(tmp_path, monkeypatch):
    """volume-gc/host-gc orphan detection depends on this.

    Note the shape: the ROOT contains `stacks/`, exactly like the other two catalog roots, because
    `list_catalog` iterates `root / kind`.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = tmp_path / "harnessed" / "generated" / "stacks" / "gen-stack"
    d.mkdir(parents=True)
    (d / "stack.yaml").write_text("name: gen-stack\nrecipes: []\nservices: []\n")
    assert "gen-stack" in paths.list_catalog_stacks()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/run-tests.sh tests/test_paths_generated_root.py -v`
Expected: FAIL — `AttributeError: module 'harnessed.paths' has no attribute 'generated_catalog_root'`.

- [ ] **Step 3: Add the root**

In `src/harnessed/paths.py`, beside `profiles_root` (:243):

```python
def generated_catalog_root() -> Path:
    """Catalog root for MACHINE-MINTED stacks (`harnessed run`) — XDG DATA, never the overlay.

    A CATALOG ROOT, i.e. the dir that CONTAINS `stacks/` — the same shape as the other two, because
    `list_catalog` iterates `root / kind`. Manifests land at `<root>/stacks/<name>/stack.yaml`.

    Deliberately not `~/.config/harnessed/catalog`: that is where the user authors, and mixing
    generated manifests into it means `harnessed list` cannot tell them apart and a regenerated
    file silently clobbers a hand edit. Derived, disposable, reproducible from its inputs — the
    same category as `profiles_root`, and stored beside it for that reason.
    """
    return xdg_data_home() / "harnessed" / "generated"
```

Then extend `catalog_roots` (:140), appending **after** the repo catalog:

```python
def catalog_roots() -> list[Path]:
    """Catalog search roots in PRECEDENCE order (first wins on name clash).

    User catalog overlays the repo catalog: ~/.config/harnessed/catalog overrides the shipped
    catalog/ for any same-named agent/recipe/service/stack, and adds names the repo doesn't have.

    The generated-stack root (`generated_catalog_root`) is LAST: a machine-minted stack must never
    shadow one you authored under the same name. It is included only when it exists, so a user who
    has never run `harnessed run` gets exactly the previous two roots.
    """
    roots: list[Path] = []
    uc = user_catalog()
    if uc.is_dir():
        roots.append(uc)
    roots.append(harnessed_home() / "catalog")
    gen = generated_catalog_root()
    if gen.is_dir():
        roots.append(gen)
    return roots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `tools/run-tests.sh tests/test_paths_generated_root.py -v`
Expected: PASS, 5 tests.

The shape matters and is fixed: `list_catalog` resolves `<root>/<kind>/<name>/<marker>`, so a catalog root is the dir that *contains* `stacks/`. `generated_catalog_root()` returns `$XDG_DATA_HOME/harnessed/generated`, and manifests live at `$XDG_DATA_HOME/harnessed/generated/stacks/<name>/stack.yaml`. Task 3 writes to that same path.

- [ ] **Step 5: Run the full suite**

Run: `tools/run-tests.sh 2>&1 | tail -5`
Expected: baseline + 13, no failures. Watch specifically for fallout in `tests/test_harnessed_home.py` and anything asserting the exact length of `catalog_roots()`.

- [ ] **Step 6: Commit**

```bash
git add src/harnessed/paths.py tests/test_paths_generated_root.py
git commit -S -m "feat(paths): add the generated-stack catalog root

Machine-minted stacks resolve from \$XDG_DATA_HOME, last in precedence so
they can never shadow an authored stack. Enumerable, so volume-gc and
host-gc orphan detection covers them with no change.

Refs: harnessed-7rx.2"
```

---

### Task 3: Content-derived naming and minting

Bead: `harnessed-7rx.3`. A new module rather than more `launcher.py`, which is already ~7000 lines.

**Files:**
- Create: `src/harnessed/dynstack.py`
- Test: `tests/test_dynstack.py`

**Interfaces:**
- Consumes: `paths.generated_catalog_root()` (Task 2).
- Produces:
  - `normalize(recipes: list[str], extends: str | None) -> tuple[str | None, tuple[str, ...]]` — deduped, sorted recipe refs plus the base.
  - `derive_name(recipes: list[str], extends: str | None) -> str` — the deterministic stack name.
  - `mint(recipes: list[str], extends: str | None, services: list[str] | None = None) -> tuple[str, Path]` — returns `(name, stack_dir)`, writing `stack.yaml` if absent or changed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dynstack.py`:

```python
"""Content-derived naming + minting for `harnessed run` (harnessed-7rx.3).

The name is MACHINE-FACING — it is never typed, only read back out of `harnessed list`,
`volume-gc` and `podman images`. So it is optimised for recognisability, not brevity, and falls
back to a hash only when the readable form would be ambiguous or over-long.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harnessed import dynstack


class TestNormalize:
    def test_sorts_and_dedupes(self):
        assert dynstack.normalize(["serena", "superpowers", "serena"], None) == (
            None, ("serena", "superpowers"),
        )

    def test_keeps_the_base_separate(self):
        assert dynstack.normalize(["serena"], "default") == ("default", ("serena",))


class TestDeriveName:
    def test_order_does_not_matter(self):
        a = dynstack.derive_name(["superpowers", "serena"], "default")
        b = dynstack.derive_name(["serena", "superpowers"], "default")
        assert a == b

    def test_readable_join_for_a_simple_set(self):
        assert dynstack.derive_name(["superpowers", "serena"], "default") == (
            "default+serena+superpowers"
        )

    def test_no_base_omits_the_prefix(self):
        assert dynstack.derive_name(["serena"], None) == "serena"

    def test_differing_bases_differ(self):
        assert dynstack.derive_name(["serena"], "default") != dynstack.derive_name(["serena"], None)

    def test_slashed_ref_is_sanitised_and_hashed(self):
        """`beads/team` -> `beads-team` is lossy, so the hash disambiguates it from a real
        recipe literally named `beads-team`."""
        slashed = dynstack.derive_name(["beads/team"], None)
        flat = dynstack.derive_name(["beads-team"], None)
        assert slashed.startswith("beads-team-")
        assert slashed != flat

    def test_long_set_is_truncated_with_a_hash(self):
        name = dynstack.derive_name([f"recipe-number-{i}" for i in range(20)], "default")
        assert len(name) <= dynstack.NAME_MAX
        assert name != dynstack.derive_name([f"recipe-number-{i}" for i in range(19)], "default")

    def test_name_is_a_legal_single_path_component(self):
        name = dynstack.derive_name(["beads/team", "superpowers"], "default")
        assert "/" not in name and name not in (".", "..")

    def test_empty_recipe_set_is_rejected(self):
        with pytest.raises(ValueError, match="at least one recipe"):
            dynstack.derive_name([], None)


class TestMint:
    def test_writes_a_manifest_that_names_itself(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        name, d = dynstack.mint(["serena"], "default")
        text = (d / "stack.yaml").read_text()
        assert f"name: {name}" in text
        assert "extends: default" in text
        assert "- serena" in text

    def test_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        n1, d1 = dynstack.mint(["serena"], "default")
        first = (d1 / "stack.yaml").read_text()
        n2, d2 = dynstack.mint(["serena"], "default")
        assert (n1, d1) == (n2, d2)
        assert (d2 / "stack.yaml").read_text() == first

    def test_carries_explicit_services(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["beads/team"], "default", services=["beads-server"])
        assert "- beads-server" in (d / "stack.yaml").read_text()

    def test_no_base_emits_no_extends_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["serena"], None)
        assert "extends:" not in (d / "stack.yaml").read_text()

    def test_manifest_is_marked_generated_in_a_comment_not_a_field(self, tmp_path, monkeypatch):
        """Stack manifests REJECT unknown fields, so the marker must be a comment."""
        monkeypatch.setattr(dynstack.paths, "generated_catalog_root", lambda: tmp_path)
        _, d = dynstack.mint(["serena"], "default")
        text = (d / "stack.yaml").read_text()
        assert text.lstrip().startswith("#")
        assert "generated:" not in text


class TestModuleBoundary:
    """`dynstack` is the exemplar for the launcher.py split (bd harnessed-4l8).

    launcher.py is 7016 lines — 53% of the codebase — with 20 commands and 179 private helpers.
    The extraction pattern it needs is a DIRECTION rule: pure, derivable logic lives in a focused
    module; launcher.py keeps only the Typer surface and podman orchestration; dependencies point
    INTO the modules and never back out.

    This test is the enforcement. The moment `dynstack` reaches back into `launcher`, the direction
    reverses and every later extraction inherits an import cycle — which is precisely why the `run`
    COMMAND stays in launcher.py: it needs `_build_stack`, `_runtime`, `launch` and `_err`, so a
    module holding it could only work through a cycle or an indirection. Commands are the most
    coupled thing in that file and are the wrong place to start; pure logic is the right place.
    """

    def test_dynstack_does_not_import_launcher(self):
        src = (Path(__file__).parent.parent / "src" / "harnessed" / "dynstack.py").read_text()
        assert "launcher" not in src, (
            "dynstack must not depend on launcher — the dependency points INTO modules, never "
            "back out (bd harnessed-4l8)"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/run-tests.sh tests/test_dynstack.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'harnessed.dynstack'`.

- [ ] **Step 3: Write the module**

Create `src/harnessed/dynstack.py`:

```python
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
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def normalize(recipes: list[str], extends: str | None) -> tuple[str | None, tuple[str, ...]]:
    """Deduped, sorted recipe refs plus the base — the canonical form the name is derived from.

    Sorting is what makes `--recipe a --recipe b` and `--recipe b --recipe a` the same stack.
    """
    return extends, tuple(sorted({r.strip() for r in recipes if r.strip()}))


def _sanitize(ref: str) -> str:
    """A catalog ref reduced to one legal path component (`beads/team` -> `beads-team`)."""
    return _UNSAFE.sub("-", ref.strip().lower().replace("/", "-")).strip("-")


def _digest(base: str | None, refs: tuple[str, ...]) -> str:
    """Stable short hash over the canonical form — computed from the UNSANITIZED refs, so two sets
    that sanitize to the same string still hash differently."""
    payload = "\x00".join([base or "", *refs])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_HASH_LEN]


def derive_name(recipes: list[str], extends: str | None) -> str:
    """The deterministic stack name for this recipe set.

    Readable join by default. A hash is appended when the readable form is not a faithful encoding
    of the input — either because a ref had to be sanitized (lossy: `beads/team` and `beads-team`
    both flatten to `beads-team`) or because the join exceeded NAME_MAX.
    """
    base, refs = normalize(recipes, extends)
    if not refs:
        raise ValueError("a dynamic stack needs at least one recipe")

    parts = [_sanitize(p) for p in ([base] if base else []) + list(refs)]
    readable = "+".join(parts)
    lossy = any("/" in r for r in refs) or (base is not None and "/" in base)

    if not lossy and len(readable) <= NAME_MAX:
        return readable

    suffix = "-" + _digest(base, refs)
    return readable[: NAME_MAX - len(suffix)].rstrip("+-") + suffix


def mint(
    recipes: list[str], extends: str | None, services: list[str] | None = None
) -> tuple[str, Path]:
    """Write (or refresh) the generated stack.yaml for this recipe set. Returns (name, stack_dir).

    Idempotent: identical inputs rewrite identical bytes, so a repeat launch does not perturb the
    staleness check. Writes only when the content differs, so the file's mtime tracks real change.
    """
    base, refs = normalize(recipes, extends)
    name = derive_name(recipes, extends)
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
    if services:
        lines.append("services:")
        lines.extend(f"  - {s}" for s in sorted(set(services)))
    else:
        lines.append("services: []")

    content = "\n".join(lines) + "\n"
    manifest = stack_dir / "stack.yaml"
    if not manifest.is_file() or manifest.read_text(encoding="utf-8") != content:
        manifest.write_text(content, encoding="utf-8")
    return name, stack_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `tools/run-tests.sh tests/test_dynstack.py -v`
Expected: PASS, 16 tests.

`mint` writes to `<generated_catalog_root>/stacks/<name>/stack.yaml`, which is why the tests patch `generated_catalog_root` to return `tmp_path` and then find the manifest under `tmp_path/stacks/<name>/`.

- [ ] **Step 5: Commit**

```bash
git add src/harnessed/dynstack.py tests/test_dynstack.py
git commit -S -m "feat(dynstack): derive a stack name from its recipe set and mint its manifest

Identical recipe sets resolve to one identity, so repos sharing a set
share one image and one pair of volumes. A hash is appended only when the
readable join would be lossy or over-long.

Refs: harnessed-7rx.3"
```

---

### Task 4: The `run` subcommand

Bead: `harnessed-7rx.4`.

**Files:**
- Modify: `src/harnessed/launcher.py` (new command; `_COMMANDS` at :6654)
- Test: `tests/test_run_command.py` (create)

**Interfaces:**
- Consumes: `dynstack.mint` (Task 3), `paths.generated_catalog_root` (Task 2).
- Produces: the `run` CLI verb. Internally calls the existing `_build_stack(rt, stack, harness, root=None, strict=True)` (`launcher.py:773`) and then the existing `launch(...)` function.

**Two traps this task exists to avoid:**

1. `main()` (`launcher.py:7000`) treats the first non-option token as a **stack name** unless it is in `_COMMANDS`. Omit `"run"` and `harnessed run --recipe x claude` silently becomes `harnessed launch run --recipe x claude`, failing with a usage error that reads like the user's mistake. `tests/test_cli_commands.py` enforces the registry both ways.
2. `launch` hard-errors when `is_built(stack, harness)` is false (`launcher.py:5374`). A freshly minted stack has no profile, so `run` **must** build before delegating.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_command.py`:

```python
"""`harnessed run` — compose a stack from a recipe set at launch (harnessed-7rx.4)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from harnessed import launcher

runner = CliRunner()


def test_run_is_registered_and_routable():
    """Absent from _COMMANDS, main() routes `run` to `launch` and it fails confusingly."""
    assert "run" in launcher._COMMANDS


def test_run_mints_builds_then_launches(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(
        launcher, "_build_stack",
        lambda rt, stack, harness, root=None, **kw: calls.__setitem__("built", (stack, harness)),
    )
    monkeypatch.setattr(
        launcher, "launch",
        lambda **kw: calls.__setitem__("launched", (kw["stack"], kw["harness"])),
    )

    result = runner.invoke(
        launcher.app, ["run", "--recipe", "superpowers", "--recipe", "serena", "claude"]
    )
    assert result.exit_code == 0, result.output
    assert calls["built"] == ("default+serena+superpowers", "claude")
    assert calls["launched"] == ("default+serena+superpowers", "claude")


def test_run_defaults_to_extending_default(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)

    runner.invoke(launcher.app, ["run", "--recipe", "serena", "claude"])
    text = (tmp_path / "stacks" / "default+serena" / "stack.yaml").read_text()
    assert "extends: default" in text


def test_no_extends_drops_the_base(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_runtime", lambda: "podman")
    monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "launch", lambda **kw: None)

    runner.invoke(launcher.app, ["run", "--recipe", "serena", "--no-extends", "claude"])
    assert "extends:" not in (tmp_path / "stacks" / "serena" / "stack.yaml").read_text()


def test_run_requires_at_least_one_recipe(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["run", "claude"])
    assert result.exit_code != 0
    # NOTE: `_err` writes to stderr via rich. Depending on the CliRunner's stderr handling the text
    # may not land in `result.output`, so the EXIT CODE is the contract here. If you want to assert
    # the wording, capture stderr explicitly with `CliRunner(mix_stderr=False)` and read
    # `result.stderr` — do not weaken this to `exit_code == 0`.


def test_unknown_harness_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.dynstack.paths, "generated_catalog_root", lambda: tmp_path)
    result = runner.invoke(launcher.app, ["run", "--recipe", "serena", "not-a-harness"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/run-tests.sh tests/test_run_command.py -v`
Expected: FAIL — `"run" in launcher._COMMANDS` is False and the CLI reports no such command.

- [ ] **Step 3: Import dynstack in the launcher**

At the top of `src/harnessed/launcher.py`, beside the other first-party imports:

```python
from . import dynstack
```

- [ ] **Step 4: Add the command**

In `src/harnessed/launcher.py`, immediately before `@app.command("build")` (:5783):

```python
@app.command("run")
def run(
    harness: str = typer.Argument(..., help="Harness to use (claude|omp|opencode|antigravity|codex)"),
    recipe: List[str] = typer.Option(
        [], "--recipe", "-r",
        help="Recipe to include; repeat for each. Order is irrelevant — the set is sorted.",
    ),
    extends: str = typer.Option(
        "default", "--extends",
        help="Stack to inherit from (baseline recipes, permissions, credential forwarding).",
    ),
    no_extends: bool = typer.Option(
        False, "--no-extends", help="Inherit from nothing — the recipe list stands alone.",
    ),
    service: List[str] = typer.Option(
        [], "--service",
        help="Extra service sidecar. Rarely needed: a recipe declares the services it requires.",
    ),
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
) -> None:
    """Launch a stack composed from a recipe set, without authoring a stack.yaml.

    `harnessed run --recipe superpowers --recipe serena claude`

    The set is normalized and named by its CONTENT, so an identical set in another repo resolves to
    the same stack and shares its image and volumes. A real manifest is minted under the generated
    catalog root, which is what lets `harnessed list`, the staleness check and both GCs treat it
    like any other stack.
    """
    _require_supported_harness(harness)

    base = None if no_extends else extends
    try:
        stack, _ = dynstack.mint(list(recipe), base, services=list(service))
    except ValueError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1)

    # A freshly minted stack has no assembled profile, and `launch` hard-errors without one. Build
    # unconditionally: _build_stack is fingerprint-gated downstream, so an unchanged set is cheap.
    _build_stack(_runtime(), stack, harness)

    launch(stack=stack, harness=harness, path=path, fresh=False, rm=False, no_firewall=False,
           agent_start_folder=None, mount_folder=None, shell=False)
```

- [ ] **Step 5: Register it**

In `_COMMANDS` (`launcher.py:6654`) add `"run"`:

```python
_COMMANDS = {
    "launch", "build", "list", "stop", "rm", "prune", "clean", "test", "new",
    "install", "uninstall", "scan", "rescan", "svc", "aws-sso", "host-gc", "host-run",
    "update", "volume-gc", "run",
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `tools/run-tests.sh tests/test_run_command.py tests/test_cli_commands.py -v`
Expected: PASS. `test_cli_commands.py` must stay green in **both** directions — registered-but-unrouted and listed-but-unregistered.

- [ ] **Step 7: Run the full suite**

Run: `tools/run-tests.sh 2>&1 | tail -5`
Expected: baseline + 35, no failures.

- [ ] **Step 8: Verify by hand against a real stack**

The suite runs no `podman build` and no `harnessed launch`, so a green run is not end-to-end proof. In a scratch git repo:

```bash
harnessed run --recipe superpowers --recipe serena claude
harnessed list
```

Expected: `harnessed list` shows `default+serena+superpowers`; the agent starts with both recipes' skills present. Then confirm reuse and GC:

```bash
harnessed run --recipe serena --recipe superpowers claude   # reversed order — same stack, no rebuild
harnessed volume-gc
```

- [ ] **Step 9: Commit**

```bash
git add src/harnessed/launcher.py tests/test_run_command.py
git commit -S -m "feat(cli): add \`harnessed run\` to compose a stack from a recipe set

Mints a content-named stack under the generated root, builds it, then
delegates to the existing launch path. Registered in _COMMANDS, without
which main() routes it to \`launch\` and it fails with a misleading usage
error. Builds before launching because launch requires a profile.

Refs: harnessed-7rx.4"
```

---

### Task 5: Migration and docs

Bead: `harnessed-7rx.5`.

**Files:**
- Modify: `ARCHITECTURE.md`
- Delete: five stacks in `~/.config/harnessed/catalog/stacks/` (**user overlay — outside the repo, not part of any commit**)

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Update ARCHITECTURE.md — the catalog roots**

In the **Vocabulary** section, the `catalog` bullet currently reads "Two roots, searched in order". Replace with:

```markdown
- **catalog** — the collection of agents/recipes/services/stacks. Three roots, searched in order:
  the user overlay **`~/.config/harnessed/catalog`** (wins on a name clash), the repo `catalog/`,
  and last the **generated** root `$XDG_DATA_HOME/harnessed/generated/` holding machine-minted stacks
  (`harnessed run`). Generated is last so it can never shadow a stack you authored, and it is kept
  out of the overlay so `harnessed list` can tell authored from generated and a regenerated
  manifest can never clobber a hand edit. It is included only when it exists.
```

- [ ] **Step 2: Update ARCHITECTURE.md — document the verb**

In **Two launch verbs, one per backend**, add a row and a paragraph beneath the table:

```markdown
| `harnessed run --recipe <r> … <harness>` | container, composed at launch | same as `launch` |

`run` is `launch` without a hand-written stack. It normalizes the recipe set, derives a name from
its CONTENT, mints a `stack.yaml` under the generated catalog root, builds it, and hands off to
`launch`. Because the name is content-derived, the same recipe set in five repos is one stack — one
image, one pair of volumes. `--extends` defaults to `default`; `--no-extends` stands alone.

A generated stack cannot use `ssh_keys:` — the private-key gate honors that field only from the
user's own overlay. That is correct rather than unfortunate: `ssh_keys` is per-stack and a generated
stack is shared across repos, so it could never express "the key for *this* repo". Per-repo SSH
identity comes from the forwarded agent plus your own `~/.ssh/config` (bd harnessed-ji6).
```

- [ ] **Step 3: Document the per-repo binding**

Add to ARCHITECTURE.md after the `run` paragraph:

```markdown
**Per-repo binding.** A project records its recipe set as a mise task:

```toml
[tasks.start-harness]
run = "harnessed run --recipe superpowers --recipe serena claude"
```

No env var, no discovery, no precedence rules — and the trust question answers itself, because
`mise run` refuses an untrusted config, so a cloned repo's task cannot select anything until you
`mise trust` it. Rejected alternatives are recorded in bd harnessed-7rx: an unknown top-level
`[harnessed]` table warns on every mise invocation, and `[env] HARNESSED_RECIPES` is live only when
mise is activated, failing silently and expensively when it is not.
```

- [ ] **Step 4: Verify the docs build clean and commit the repo half**

Run: `tools/run-tests.sh 2>&1 | tail -5`
Expected: unchanged from Task 4 — no test reads ARCHITECTURE.md prose, but run it to confirm nothing else drifted.

```bash
git add ARCHITECTURE.md
git commit -S -m "docs(architecture): document the generated catalog root and \`harnessed run\`

Refs: harnessed-7rx.5"
```

- [ ] **Step 5: Migrate the overlay stacks — one at a time, verifying each**

These live in `~/.config/harnessed/catalog/stacks/`, **outside the repo**. Nothing here is committed. Do them one at a time, and confirm the replacement works before deleting anything.

| Stack | Replacement command |
| --- | --- |
| `superpowers` | `harnessed run --recipe superpowers claude` |
| `superpowers_beads` | `harnessed run --recipe beads/team --recipe superpowers claude` |
| `superpowers_beads_serena` | `harnessed run --recipe beads/team --recipe superpowers --recipe serena claude` |
| `gsd-core` | `harnessed run --recipe gsd-core --recipe context-mode --recipe repowise claude` |
| `gsd-core_serena` | `harnessed run --recipe gsd-core --recipe serena claude` |

For each: run the replacement, confirm the agent starts with the expected skills and (for the beads ones) that `bd ready` works — which is the real test of Task 1, since the `beads-server` service now comes from the recipe rather than the stack. Only then `rm -r ~/.config/harnessed/catalog/stacks/<name>`.

`default` stays. Do not delete it — every generated stack extends it.

- [ ] **Step 6: Reclaim the old stacks' artifacts**

```bash
harnessed volume-gc --dry-run
```

Expected: the deleted stacks' `harnessed-cfg-*` / `harnessed-tools-*` volumes now report as orphans, because their stack no longer resolves. That output is the live proof that Task 2's root is properly enumerable. Then:

```bash
harnessed volume-gc --prune
harnessed host-gc
```

- [ ] **Step 7: Close the beads**

```bash
bd close harnessed-7rx.1 harnessed-7rx.2 harnessed-7rx.3 harnessed-7rx.4 harnessed-7rx.5
bd close harnessed-7rx --reason="Dynamic stacks shipped: recipes declare their services, generated catalog root, content-derived naming, harnessed run, overlay stacks migrated to mise tasks."
```

---

## Notes for the implementer

- **The suite proves less than it looks.** It runs no `podman build` and no `harnessed launch`. Tasks 4 and 5 carry manual verification steps for exactly that reason; do not skip them and call the work done.
- **A plain-text-vs-ANSI assertion failure means your environment is wrong**, not the assertion. Read the run-tests skill; never "fix" it by editing the assertion.
- **One path shape, used by three tasks.** `generated_catalog_root()` is a *catalog root* — `$XDG_DATA_HOME/harnessed/generated`, containing `stacks/` — because `list_catalog` iterates `root / kind`. Manifests are at `<root>/stacks/<name>/stack.yaml`. Tasks 2, 3 and 4 all assume exactly this; if you change it, change all three.
- `harnessed new` is deliberately untouched. It writes to `paths.harnessed_home()/catalog/stacks` — the repo/wheel catalog, which on an installed wheel is site-packages — so it cannot serve a user overlay. That is a pre-existing defect, not this plan's scope.
