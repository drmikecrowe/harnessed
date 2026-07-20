"""The CONTENT-DELIVERY recipes, migrated from a Dockerfile RUN to `install.sh` — bd harnessed-8px.4.

These are the recipes whose deliverables are files under the agent config dir, and which therefore
came out EMPTY on `harnessed launch --host`: the assembler never ran their Dockerfile, so the skills
they declare in `expect:` simply were not there, with no error (bd harnessed-8px.1, P1).

What this file guards is the migration's invariants, not the mechanism (that is
tests/test_install_script.py):

  * DECLARED      — each one actually has an `install:` block whose script exists on disk.
  * NO DRIFT      — `install.cache` is the SAME pinned ref the script clones. They are two literals
                    in two files; when they disagree the host cache is keyed to a ref nobody fetches
                    and goes permanently stale, silently. This is the one failure the mechanism
                    cannot detect at runtime, so it is asserted here.
  * NO RESIDUE    — the content half no longer lives in a Dockerfile. A recipe that still writes
                    into the agent config dir from a Dockerfile RUN has, by construction, the exact
                    bug this batch fixes.
  * STRADDLERS    — gstack keeps a Dockerfile because one step needs root. That is legal ONLY when
                    declared via `install.system`, which is what makes a host launch say so out loud
                    instead of shipping a half-broken install.
"""

import re
from pathlib import Path

import pytest

from harnessed import emit
from harnessed.schema import load_recipe, validate_install_script, validate_no_raw_npm, validate_pin

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# The batch. superpowers is the template the rest follow (migrated ahead of them); it is included
# because "the template still obeys its own contract" is exactly what regresses unnoticed.
CONTENT_RECIPES = ["superpowers", "hyperpowers", "caveman", "agent-carnet", "gstack"]

# Recipes whose ENTIRE body was content — nothing needed root, so the Dockerfile is gone outright.
PURE_CONTENT = ["superpowers", "hyperpowers", "caveman"]

# Anything that looks like a write into the agent config dir. A migrated recipe's Dockerfile must
# not contain one: that is the half that a host launch cannot execute.
_CONFIG_DIR_WRITE = re.compile(r"~/\.claude|\$HOME/\.claude|/home/harnessed/\.claude")


def _recipe(name):
    return load_recipe(CATALOG / "recipes" / name, strict=True)


def _code(path: Path) -> str:
    """The file minus comment lines — these recipes explain themselves at length, and a rule about
    what a file DOES must not be satisfied (or broken) by prose describing it. Same convention as
    schema._lint_script_file."""
    return "\n".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


@pytest.mark.parametrize("name", CONTENT_RECIPES)
class TestDeclared:
    def test_declares_install_script_that_exists(self, name):
        inst = _recipe(name).install
        assert inst is not None, f"{name} delivers content but declares no `install:` block"
        assert (CATALOG / "recipes" / name / inst.script).is_file()

    def test_script_passes_the_pin_and_npm_lints(self, name):
        # `install:` moved Dockerfile RUN bodies into a .sh, which validate_pin cannot read. If this
        # ever stops being called for these recipes, pin enforcement silently ends for them.
        validate_install_script(_recipe(name))

    def test_declares_a_pinned_cache_key(self, name):
        # Without a cache these clone on EVERY host launch — the home is rmtree'd each time, so the
        # install cannot be skipped, only made cheap.
        assert _recipe(name).install.cache, f"{name} re-downloads on every host launch"

    def test_cache_key_matches_the_ref_the_script_actually_fetches(self, name):
        r = _recipe(name)
        body = (r.root / r.install.script).read_text(encoding="utf-8")
        assert f'"{r.install.cache}"' in body, (
            f"{name}: install.cache {r.install.cache!r} does not appear as a pinned literal in "
            f"{r.install.script} — the host cache would be keyed to a ref the script never fetches, "
            "so it is populated once and never refreshed."
        )

    def test_script_installs_into_the_contract_config_dir(self, name):
        # The whole mode-portability story: one env var names the destination in both modes.
        body = (CATALOG / "recipes" / name / _recipe(name).install.script).read_text(encoding="utf-8")
        assert "$HARNESSED_CONFIG_DIR" in body

    def test_script_treats_a_missing_cache_dir_as_the_miss(self, name):
        # harnessed creates only the cache's PARENT; the dir's own absence is the miss signal, and a
        # populate must be atomic or an interrupted clone becomes a permanent phantom hit.
        body = (CATALOG / "recipes" / name / _recipe(name).install.script).read_text(encoding="utf-8")
        assert "HARNESSED_INSTALL_CACHE" in body
        assert "mv " in body, "populate temp-then-`mv`, or an interrupted fetch looks like a hit"

    def test_expect_block_survives_the_migration(self, name):
        # `expect:` is the capability-test oracle for content the assembler cannot see. Delivering
        # that content by script rather than by RUN does not change what must be found.
        assert _recipe(name).expect.skills, f"{name} declares no expected skills"


@pytest.mark.parametrize("name", PURE_CONTENT)
def test_pure_content_recipes_have_no_dockerfile_left(name):
    assert not (CATALOG / "recipes" / name / "Dockerfile").exists(), (
        f"{name} was entirely content; a leftover Dockerfile means part of it is still "
        "container-only and invisible to a host launch."
    )


@pytest.mark.parametrize("name", CONTENT_RECIPES)
def test_no_migrated_dockerfile_still_writes_into_the_agent_config_dir(name):
    dockerfile = CATALOG / "recipes" / name / "Dockerfile"
    if not dockerfile.is_file():
        return
    body = "\n".join(
        ln for ln in dockerfile.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert not _CONFIG_DIR_WRITE.search(body), (
        f"{name}: its Dockerfile still writes into the agent config dir. That is the half a "
        "`--host` launch never executes (bd harnessed-8px.1) — move it into install.sh."
    )


class TestGstackStraddles:
    """gstack delivers content AND needs root. Both halves have to be honest about which is which."""

    def test_declares_why_root_is_needed(self):
        system = _recipe("gstack").install.system
        assert system and "root" in system.lower()

    def test_the_root_step_stays_in_the_dockerfile(self):
        # harnessed never sudos, so an apt install cannot move into install.sh. It stays a build
        # layer; `install.system` is what turns the host-side gap into a printed warning.
        body = (CATALOG / "recipes" / "gstack" / "Dockerfile").read_text(encoding="utf-8")
        assert "USER root" in body
        assert "playwright install-deps" in body

    def test_the_content_step_moved_out_of_the_dockerfile(self):
        assert "./setup" not in _code(CATALOG / "recipes" / "gstack" / "Dockerfile")
        assert "./setup" in _code(CATALOG / "recipes" / "gstack" / "install.sh")

    def test_install_layers_before_the_root_dockerfile_body(self):
        # emit puts a recipe's install block BEFORE its Dockerfile body, so the root steps layer on
        # top of the install rather than under it. gstack's chown of ~/.bun depends on that order.
        r = _recipe("gstack")
        lines = emit._install_dockerfile_lines(r, "claude")
        assert any(line.startswith("RUN ") and "install.sh" in line for line in lines)
        assert "USER root" not in "\n".join(lines)

    def test_install_fails_loudly_when_bun_is_missing(self):
        # A host launch without bun cannot run upstream's ./setup. Failing loudly is the acceptance
        # criterion of bd harnessed-8px.1 — the bug WAS the silence.
        script = (CATALOG / "recipes" / "gstack" / "install.sh").read_text(encoding="utf-8")
        assert "command -v bun" in script
        assert "exit 1" in script


class TestAgentCarnetPartial:
    """agent-carnet migrated only its CONTENT half; the CLI install is deliberately container-only."""

    def test_the_skill_comes_from_the_install_script(self):
        script = (CATALOG / "recipes" / "agent-carnet" / "install.sh").read_text(encoding="utf-8")
        assert "skills/agent-carnet" in script
        assert "SKILL.md" in script, "verify the copy, or an empty skill dir ships silently"

    def test_the_cli_install_stays_in_the_dockerfile(self):
        # `pnpm add -g` host-side would write into the user's global pnpm store — outside every
        # harnessed-owned directory. Putting the CLI on PATH host-side is `provision:`'s job.
        assert "pnpm add -g agent-carnet@" in _code(CATALOG / "recipes" / "agent-carnet" / "Dockerfile")
        assert "pnpm add -g" not in _code(CATALOG / "recipes" / "agent-carnet" / "install.sh")

    def test_one_version_literal_binds_the_cli_and_the_skill(self):
        r = _recipe("agent-carnet")
        version = r.install.cache
        docker = (r.root / "Dockerfile").read_text(encoding="utf-8")
        assert f"ARG AGENT_CARNET_VERSION={version}" in docker, (
            "the CLI and the skill must come from the SAME immutable npm artifact"
        )

    def test_the_declarative_rule_survived(self):
        # The partial migration must not have swallowed what the assembler could already see.
        assert [rule.path for rule in _recipe("agent-carnet").rules] == ["rules/agent-carnet"]


class TestCatalogWideInvariants:
    def test_every_migrated_recipe_still_passes_the_full_recipe_lint_set(self):
        # The same gates assemble() runs before emitting anything.
        for name in CONTENT_RECIPES:
            r = _recipe(name)
            validate_no_raw_npm(r)
            validate_install_script(r)
            dockerfile = r.root / "Dockerfile"
            if dockerfile.is_file():
                validate_pin(r.name, dockerfile.read_text(encoding="utf-8"))

    def test_derived_dockerfile_carries_an_install_step_for_each(self):
        recipes = [_recipe(n) for n in CONTENT_RECIPES]
        lines = [ln for r in recipes for ln in emit._install_dockerfile_lines(r, "claude")]
        text = "\n".join(lines)
        for name in CONTENT_RECIPES:
            assert f"# --- recipe install: {name} ---" in text
            assert f"{emit.CTR_RECIPE_DIR}/{name}/install.sh" in text

    def test_container_install_cache_never_ships_in_the_image(self):
        # A cached clone left behind would bake the whole upstream repo into every derived image.
        for name in CONTENT_RECIPES:
            run = [
                ln for ln in emit._install_dockerfile_lines(_recipe(name), "claude")
                if ln.startswith("RUN ")
            ]
            assert len(run) == 1
            assert f"rm -rf {emit._CTR_INSTALL_CACHE}" in run[0], (
                f"{name}: the build-time cache must be removed in the SAME layer that creates it"
            )
