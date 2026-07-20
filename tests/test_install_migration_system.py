"""The SYSTEM-LEVEL half of the `install:` migration — bd harnessed-8px.5 (batch D).

`install.script` moves a Dockerfile RUN into one bash file both executors run. Some RUNs cannot
move: they need `USER root` — `apt-get`, a binary landing in `/usr/local/bin`. harnessed never sudos
and never mutates the user's machine, so those stay in the recipe Dockerfile and are container-only.

The failure mode that policy exists to prevent is NOT the missing tool. It is the SILENCE about the
missing tool — bd harnessed-8px.1, where a `--host` launch shipped a stack with 0 of 14 promised
skills and printed nothing. So the recipe declares `install.system: "<reason>"` and a host launch
prints that reason verbatim, naming the recipe. Every test here is ultimately about that noise.

Two shapes, both real in the catalog after this migration:

  * ROOT-ONLY (`system:`, no `script:`) — solidspec, tokensave. There is no user-level half to run
    in either mode; the declaration's whole job is the host warning. This shape is why `script` is
    optional: requiring it would force a root-only recipe to either invent an empty script or stay
    silent, and silence is the bug.
  * FULLY USER-LEVEL (`script:`, no `system:`) — beads/team, beads/stealth. Their Dockerfiles LOOKED
    system-level (two `USER root` lines) but every statement under those lines was a comment; the
    install itself ran as `harnessed`. Nothing is skipped on a host, so nothing is warned about.

Kept out of tests/test_install_script.py deliberately — that file covers the mechanism, this one
covers the migration's system-level policy and its catalog consumers.
"""

import re
import subprocess
from pathlib import Path

import pytest

from harnessed import emit, launcher, paths
from harnessed.schema import (
    RecipeLintError,
    SchemaError,
    load_recipe,
    validate_container_only_declared,
    validate_install_script,
)

CATALOG = Path(__file__).resolve().parents[1] / "catalog"
RECIPES = CATALOG / "recipes"

# The catalog recipes this batch migrated, by shape.
ROOT_ONLY = ["solidspec", "tokensave"]
USER_LEVEL = ["beads/team", "beads/stealth"]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """rich styles its output and wraps long lines; assert on the words, not the escapes."""
    return " ".join(_ANSI.sub("", text).split())


def _catalog_recipe(ref: str):
    return load_recipe(RECIPES / paths.catalog_relpath(ref), strict=True)


def _tmp_recipe(tmp_path, name="r", *, install: str, with_script: bool = True):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(f"name: {name}\n{install}")
    if with_script:
        (d / "install.sh").write_text("true\n")
    return load_recipe(d, strict=True)


class TestRootOnlyInstallParses:
    """`system:` alone is a legal `install:` — the shape a root-only recipe needs."""

    def test_system_without_script_parses(self, tmp_path):
        r = _tmp_recipe(tmp_path, install="install:\n  system: 'apt-get cmake'\n", with_script=False)
        assert r.install.script is None
        assert r.install.system == "apt-get cmake"

    def test_neither_script_nor_system_is_rejected(self, tmp_path):
        """An `install:` that declares neither executes nothing AND explains nothing — the exact
        combination this epic exists to make impossible. (A wholly empty `install: {}` is a
        different case, and older than this change: it parses to no install at all.)"""
        with pytest.raises(SchemaError, match="at least one"):
            _tmp_recipe(tmp_path, install="install:\n  script: ~\n  system: ~\n", with_script=False)

    def test_empty_system_is_still_rejected(self, tmp_path):
        """The reason string IS the anti-silence mechanism, so it may never be blank."""
        with pytest.raises(SchemaError, match="install.system"):
            _tmp_recipe(tmp_path, install="install:\n  system: '   '\n", with_script=False)

    def test_cache_without_script_is_rejected(self, tmp_path):
        """The cache exists to be populated and read BY the script. Root-only has no script, so a
        cache key would be bookkeeping nothing ever reads."""
        with pytest.raises(SchemaError, match="install.script"):
            _tmp_recipe(tmp_path, install="install:\n  cache: v1.0.0\n", with_script=False)


class TestHostLaunchWarnsInsteadOfSkippingSilently:
    """THE test of this batch: every recipe declaring `system:` is audible on a host launch."""

    def _run(self, tmp_path, recipe, monkeypatch, capsys):
        monkeypatch.setattr(launcher, "load_stack_with_recipes", lambda root, s: (None, [recipe]))
        launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")
        return _plain(capsys.readouterr().err)

    @pytest.mark.parametrize("ref", ROOT_ONLY)
    def test_real_catalog_recipe_warns_with_its_reason_verbatim(
        self, ref, tmp_path, monkeypatch, capsys
    ):
        r = _catalog_recipe(ref)
        assert r.install and r.install.system, f"{ref} must declare install.system"
        err = self._run(tmp_path, r, monkeypatch, capsys)
        assert "WARNING" in err
        assert r.name in err, "the warning must NAME the recipe — a user with 8 recipes needs to know which"
        assert _plain(r.install.system) in err, "the declared reason is printed verbatim, not summarized"
        assert "will not sudo" in err

    @pytest.mark.parametrize("ref", ROOT_ONLY)
    def test_root_only_install_executes_nothing_on_a_host(
        self, ref, tmp_path, monkeypatch, capsys
    ):
        """A root-only install has no script; the warning IS the entire host-side behaviour. If it
        ever tried to run something, that something would be the user's machine being mutated."""
        def _boom(*a, **kw):
            raise AssertionError("a root-only install must not execute anything host-side")

        monkeypatch.setattr(subprocess, "run", _boom)
        err = self._run(tmp_path, _catalog_recipe(ref), monkeypatch, capsys)
        assert "WARNING" in err

    def test_a_host_launch_does_not_fail_on_a_system_only_recipe(
        self, tmp_path, monkeypatch, capsys
    ):
        """Documented skip, NOT a hard failure: several default-set stacks carry a root-only
        recipe, and hard-failing them would make `--host` unusable."""
        r = _tmp_recipe(tmp_path, install="install:\n  system: 'needs root'\n", with_script=False)
        self._run(tmp_path, r, monkeypatch, capsys)  # raises typer.Exit on failure

    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_fully_user_level_recipes_warn_about_nothing(self, ref):
        """beads' `USER root` lines had only comments under them. Declaring `system:` anyway would
        train users to ignore the warning — the one thing that must not happen to it."""
        r = _catalog_recipe(ref)
        assert r.install and r.install.system is None, (
            f"{ref} has no root-level step; a `system:` reason here would be noise"
        )


class TestTheRootStepStaysInTheDockerfile:
    def test_root_only_install_emits_no_build_step(self, tmp_path):
        """Container-side the root work is already in the recipe's own Dockerfile. Emitting a COPY
        and a `bash` for a script that does not exist would break the build."""
        r = _tmp_recipe(tmp_path, install="install:\n  system: 'needs root'\n", with_script=False)
        assert emit._install_dockerfile_lines(r, "claude") == []

    @pytest.mark.parametrize("ref", ROOT_ONLY)
    def test_catalog_root_only_recipes_keep_their_dockerfile(self, ref):
        r = _catalog_recipe(ref)
        dockerfile = r.root / "Dockerfile"
        assert dockerfile.is_file(), f"{ref}: the root step has nowhere else to live"
        assert "USER root" in dockerfile.read_text(), (
            f"{ref}: declares install.system but its Dockerfile has no root step — one of the two is wrong"
        )

    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_migrated_recipes_dropped_their_dockerfile(self, ref):
        r = _catalog_recipe(ref)
        assert not (r.root / "Dockerfile").exists(), (
            f"{ref}: install.sh replaced the Dockerfile entirely — a leftover one would run twice"
        )


class TestPartialMigrationMustDeclareWhatAHostLoses:
    """bd harnessed-8px.1, criterion 2. A recipe with an `install:` runs its script in BOTH modes, so
    any RUN left in its Dockerfile is container-only and a host launch delivers less than the recipe
    promises. `install.system` is the reason the launcher prints; without it the shortfall reaches
    the user as nothing at all — the original 14-missing-skills failure, in miniature.

    agent-carnet is why this lint exists: it kept `pnpm add -g` in its Dockerfile, documented the gap
    in a YAML comment, and shipped a host launch that silently lacked the binary. Comments are
    invisible at runtime.
    """

    def test_undeclared_run_is_rejected(self, tmp_path):
        r = _tmp_recipe(tmp_path, install="install:\n  script: install.sh\n")
        with pytest.raises(RecipeLintError, match="install.system"):
            validate_container_only_declared(r, "FROM x\nRUN pnpm add -g foo@1.0.0\n")

    def test_declared_reason_passes(self, tmp_path):
        r = _tmp_recipe(tmp_path, install="install:\n  script: install.sh\n  system: 'no binary'\n")
        validate_container_only_declared(r, "RUN apt-get install -y thing")  # must not raise

    def test_recipe_without_install_is_not_gated(self, tmp_path):
        """Never migrated → container-only by construction, with no half-delivered state to misreport."""
        r = _tmp_recipe(tmp_path, install="", with_script=False)
        validate_container_only_declared(r, "RUN anything")  # must not raise

    def test_commented_out_run_does_not_trigger(self, tmp_path):
        r = _tmp_recipe(tmp_path, install="install:\n  script: install.sh\n")
        validate_container_only_declared(r, "# RUN this is prose\nFROM x")  # must not raise

    def test_every_catalog_recipe_declares_its_container_only_half(self):
        """The real net: run the lint over the whole shipped catalog, exactly as assemble() does."""
        offenders = []
        for recipe_yaml in sorted(RECIPES.glob("*/recipe.yaml")):
            r = load_recipe(recipe_yaml.parent, strict=True)
            dockerfile = r.root / "Dockerfile"
            if not dockerfile.is_file():
                continue
            try:
                validate_container_only_declared(r, dockerfile.read_text(encoding="utf-8"))
            except RecipeLintError:
                offenders.append(r.name)
        assert offenders == [], (
            f"recipes with an undeclared container-only RUN: {offenders}. "
            "Set install.system to what a host launch does not get, or move the step into install.script."
        )


class TestHomeShimRecipesRewriteRecordedPaths:
    """bd harnessed-8px.9. The $HOME-shim pattern (mktemp -d + .claude symlink) makes an upstream
    installer's FILE writes land in the stack config dir, but any path it RECORDS is written with the
    shim $HOME — which the trap deletes on exit. gsd-core shipped 12 hooks pointing at a dead /tmp
    path this way, failing every launch after the one that installed them.

    Any recipe adopting the shim must therefore rewrite recorded paths before the shim goes away.
    """

    def test_every_shim_using_install_script_rewrites_recorded_paths(self):
        offenders = []
        for script in sorted(RECIPES.glob("*/install.sh")):
            body = script.read_text(encoding="utf-8")
            if "shim_home=" not in body:
                continue  # not using the pattern; nothing to rewrite
            if "_rewrite_shim_paths" not in body:
                offenders.append(script.parent.name)
        assert offenders == [], (
            f"install.sh uses a $HOME shim but never rewrites recorded paths: {offenders}. "
            "The shim is deleted on exit, so any absolute path the installer baked into "
            "settings.json dies with it — call _rewrite_shim_paths \"$shim_home\" after the installer."
        )


class TestMigratedBeadsRecipes:
    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_install_script_exists_and_lints(self, ref):
        r = _catalog_recipe(ref)
        assert r.install.script == "install.sh"
        assert (r.root / "install.sh").is_file()
        validate_install_script(r)  # raises on raw npm/npx or a floating ref

    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_script_pins_the_version_the_recipe_documents(self, ref):
        """The pin lives in the script now, where `validate_pin` (Dockerfile text only) cannot see
        it — `validate_install_script` is the gate, and this asserts the pin is actually there."""
        body = (_catalog_recipe(ref).root / "install.sh").read_text()
        assert "github:gastownhall/beads@${BEADS_VERSION}" in body
        assert 'BEADS_VERSION="1.1.0"' in body

    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_script_is_idempotent_across_the_per_launch_rerun(self, ref):
        """The host home is rmtree'd every launch, so this script runs every launch. Without a
        short-circuit it would rewrite the user's global mise config each time."""
        body = (_catalog_recipe(ref).root / "install.sh").read_text()
        assert "command -v bd" in body

    @pytest.mark.parametrize("ref", USER_LEVEL)
    def test_readme_documents_removal_of_out_of_bounds_writes(self, ref):
        """bd harnessed-8px.6: these recipes write `.beads/` and (via `bd setup`) `CLAUDE.md` +
        `.claude/settings.json` INTO the project — outside every harnessed-owned dir. A user who
        drops the recipe must be able to find the undo."""
        readme = (_catalog_recipe(ref).root / "README.md").read_text()
        assert "## Footprint and removal" in readme
        for expected in (".beads", "CLAUDE.md", ".claude/settings.json", "mise unuse"):
            assert expected in readme, f"{ref}: README does not document removing {expected}"


def test_every_recipe_with_a_root_dockerfile_step_declares_it():
    """The policy, enforced across the whole catalog rather than recipe by recipe.

    A recipe that has migrated to `install:` while KEEPING a `USER root` Dockerfile step has, by
    construction, a container-only component. If it does not declare `system:`, a host launch drops
    that component in silence — the regression this epic closed. (A recipe with no `install:` at all
    is out of scope here: it has not been migrated yet and its Dockerfile is still the whole story.)
    """
    offenders = []
    for recipe_yaml in sorted(RECIPES.glob("*/recipe.yaml")) + sorted(RECIPES.glob("*/*/recipe.yaml")):
        r = load_recipe(recipe_yaml.parent, strict=True)
        if not r.install or r.install.system:
            continue
        dockerfile = r.root / "Dockerfile"
        if not dockerfile.is_file():
            continue
        body = "\n".join(
            ln for ln in dockerfile.read_text().splitlines() if not ln.lstrip().startswith("#")
        )
        if "USER root" in body:
            offenders.append(r.name)
    assert not offenders, (
        f"recipes with a root Dockerfile step and an `install:` but no `install.system` reason: "
        f"{offenders} — a host launch skips their root step silently"
    )
