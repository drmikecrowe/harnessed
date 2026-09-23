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


class TestNoInstallScriptUsesAGnuOnlySedInPlace:
    """The same install.sh runs in the container (GNU coreutils) and on the HOST, which on macOS is
    BSD. `sed -i` is the one idiom where those two disagree irreconcilably: GNU takes the suffix as
    an optional attached argument (`-i`), BSD as a mandatory separate one (`-i ''`). Written either
    way, the other platform misreads the next token — BSD takes the sed script as the backup suffix
    and then fails on the filename.

    Caught in context-mode, whose rewrite loop was unreachable on every platform until the skills
    probe was fixed, so the container had never run it either. Write `sed … > tmp && mv tmp file`.
    """

    def test_no_install_script_calls_sed_dash_i(self):
        offenders = []
        for d in _recipe_dirs():
            script = d / "install.sh"
            if not script.is_file():
                continue
            for n, line in _uncommented(script):
                if re.search(r"\bsed\b[^|;&]*\s-i\b", line):
                    offenders.append(f"{d.name}:{n}: {line.strip()[:70]}")
        assert offenders == [], (
            f"install.sh uses `sed -i`: {offenders}. GNU and BSD sed disagree about its argument, "
            "and this script runs on both. Use `sed '...' f > f.tmp && mv f.tmp f`."
        )


class TestEveryLockfileMatchesThePinBesideIt:
    """A recipe's `mise.lock` records the bytes of the version its `tools:` names. When the two
    disagree, mise must MIGRATE the lock at install time — and that migration re-resolves every
    platform in the file, not only the one installing.

    That is how a stale lock becomes a launch failure on a machine that bumped nothing: an older
    mise that cannot see the new version's attestation for some OTHER platform trips its
    provenance-downgrade guard and refuses the whole `tools:` install as a possible supply-chain
    attack. Caught after `chore(catalog): upgrade pins 2026-09-14` bumped two recipes' pins and
    neither lockfile, which broke every macos-arm64 launch of both.
    """

    def test_no_recipe_lockfile_names_a_version_its_tools_pin_does_not(self):
        offenders = []
        for d in _recipe_dirs():
            lock = d / "mise.lock"
            if not lock.is_file():
                continue
            r = load_recipe(d, strict=True)
            pinned = {spec.rpartition("@")[2] for spec in r.tools}
            locked = set(re.findall(r'^version = "([^"]+)"', lock.read_text(), re.M))
            if locked - pinned:
                offenders.append(f"{r.name}: lock has {sorted(locked)}, tools: pin {sorted(pinned)}")
        assert offenders == [], (
            f"mise.lock has drifted from the `tools:` pin beside it: {offenders}. "
            "Regenerate the lockfile in the same commit as the bump — `harnessed update` does "
            "this itself; a hand-edited pin must do it too."
        )
