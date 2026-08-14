"""Catalog-wide uniformity rules. Every check here DISCOVERS its subjects.

harnessed does not curate individual recipes: what a recipe installs, and whether it works, is the
recipe author's problem, verified by the recipe's own tests and its `expect:` block. What harnessed
owns is the CONTRACT every recipe must satisfy, and a contract is only worth asserting over the
whole catalog.

So nothing in this file names a recipe or a version. A rule that applies to one recipe is either a
rule that applies to all of them, or it is not harnessed's rule. These replace a set of per-recipe
migration tests that asserted the same properties against a hand-maintained roster: the roster went
stale on every pin bump and covered only the recipes someone remembered to list.

Docstrings name recipes as historical motivation ("this caught X") — that is provenance for why a
rule exists, not a dependency on X still being in the catalog.
"""

import re
from pathlib import Path

from harnessed import paths
from harnessed.schema import RecipeLintError, load_recipe, validate_install_script

# Package managers that FETCH. A recipe's binary comes from its `tools:` pin, which is what
# `harnessed update` reads and what the lockfile records; a fetch inside install.sh is a second,
# invisible pin that drifts against it.
_FETCHERS = (
    "pnpm add -g",
    "npm i -g",
    "npm install -g",
    "uv tool install",
    "pipx install",
    "cargo install",
    "mise use -g",
)


def _recipe_dirs() -> list[Path]:
    root = paths.harnessed_home() / "catalog" / "recipes"
    return sorted(d.parent for d in root.rglob("recipe.yaml"))


def _uncommented(script: Path) -> list[tuple[int, str]]:
    """Script lines with comment-only lines dropped, kept with their 1-based line numbers."""
    return [
        (n, line)
        for n, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1)
        if not line.lstrip().startswith("#")
    ]


class TestEveryRecipeDeclaresAnInstallItActuallyShips:
    def test_a_declared_install_script_exists_on_disk(self):
        offenders = []
        for d in _recipe_dirs():
            r = load_recipe(d, strict=True)
            if r.install is None or r.install.script is None:
                continue
            if not (r.root / r.install.script).is_file():
                offenders.append(f"{r.name}: declares {r.install.script}, no such file")
        assert offenders == [], (
            f"recipe declares an install script it does not ship: {offenders}. "
            "A missing script is a silent no-op install on both host and container."
        )

    def test_every_install_script_passes_the_lint(self):
        """`validate_pin` only ever read Dockerfile text. Once the pin moved into the .sh, this lint
        is the only thing standing between the catalog and a floating ref."""
        offenders = []
        for d in _recipe_dirs():
            r = load_recipe(d, strict=True)
            if r.install is None or r.install.script is None:
                continue
            try:
                validate_install_script(r)
            except RecipeLintError as exc:
                offenders.append(f"{r.name}: {exc}")
        assert offenders == [], f"install.sh fails the catalog lint: {offenders}"


class TestNoInstallScriptFetchesItsOwnBinary:
    """The pin belongs in `tools:` and nowhere else. This generalises what used to be asserted
    against a roster of six recipes, so a recipe added tomorrow is covered without editing a list."""

    def test_no_install_script_shells_out_to_a_package_manager(self):
        offenders = []
        for d in _recipe_dirs():
            script = d / "install.sh"
            if not script.is_file():
                continue
            for n, line in _uncommented(script):
                for fetch in _FETCHERS:
                    if fetch in line:
                        offenders.append(f"{d.name}:{n}: {line.strip()[:70]}")
        assert offenders == [], (
            f"install.sh fetches a package: {offenders}. Declare it in the recipe's `tools:` "
            "instead — that pin is what `harnessed update` reads and what the lockfile records. "
            "A fetch here is a second pin that drifts against it invisibly."
        )


class TestNoContainerAbsolutePathSurvivesIntoHostMode:
    """`/home/harnessed/...` in a script that ALSO runs on the host is a path that cannot resolve
    there. Paths must come from $HARNESSED_CONFIG_DIR / $HARNESSED_INSTALL_CACHE / $HOME."""

    def test_no_install_script_hardcodes_the_container_home(self):
        offenders = []
        for d in _recipe_dirs():
            script = d / "install.sh"
            if not script.is_file():
                continue
            for n, line in _uncommented(script):
                if re.search(r"/home/harnessed\b", line):
                    offenders.append(f"{d.name}:{n}: {line.strip()[:70]}")
        assert offenders == [], (
            f"install.sh hardcodes the container home: {offenders}. "
            "Use $HARNESSED_CONFIG_DIR / $HARNESSED_INSTALL_CACHE / $HOME so the same script "
            "works on a host launch."
        )
