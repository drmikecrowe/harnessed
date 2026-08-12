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
from support import patch_all

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# The batch. superpowers is the template the rest follow (migrated ahead of them); it is included
# because "the template still obeys its own contract" is exactly what regresses unnoticed.
CONTENT_RECIPES = ["superpowers", "hyperpowers", "caveman", "gstack"]

# Recipes whose ENTIRE body was content — nothing needed root, so the Dockerfile is gone outright.
PURE_CONTENT = ["superpowers", "hyperpowers", "caveman"]

# Anything that looks like a write into the agent config dir. A migrated recipe's Dockerfile must
# not contain one: that is the half that a host launch cannot execute.
_CONFIG_DIR_WRITE = re.compile(r"~/\.claude|\$HOME/\.claude|/home/harnessed/\.claude")


def _yaml_comments(text: str) -> str:
    """Every comment in a YAML file — inline ones too, which is the whole point.

    A full-line filter (`line.lstrip().startswith("#")`) misses `ref: manifest-owned  # v6.0.3`,
    so the guard could pass while recipe.yaml still carried a second copy of the pin. Raised in
    review of PR #353, second pass.

    Not a YAML parse: comments do not survive one. This walks each line tracking quote state and
    takes the tail from the first `#` that is OUTSIDE quotes and preceded by whitespace or
    start-of-line. Both conditions matter and both are load-bearing:

      * inside quotes    `summary: "pass #1 of 2"`     is a string, not a comment
      * mid-token        `reference: https://x/y#frag` is a URL fragment, not a comment

    Declaration lines carry no `#` at all, so `repo:`/`ref:` remain the single ownership location
    exactly as before — this widens what counts as a comment, never what counts as a declaration.
    """
    out: list[str] = []
    for line in text.splitlines():
        in_single = in_double = False
        for i, ch in enumerate(line):
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double and (i == 0 or line[i - 1] in " \t"):
                out.append(line[i:])
                break
    return "\n".join(out)


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


class TestYamlCommentExtraction:
    """The helper the pin guard depends on. Its two exclusions are claims, so they are asserted.

    A guard is only as good as what it can SEE — three times this epic a test passed because it
    was blind to the copy it was meant to reject. Testing the extractor directly is cheaper than
    rediscovering that through a missed literal.
    """

    def test_full_line_comments_are_captured(self):
        assert "# a full line" in _yaml_comments("# a full line\nkey: value\n")

    def test_inline_comments_are_captured(self):
        # The case a `lstrip().startswith("#")` filter misses, and the reason this helper exists.
        assert "# v6.0.3" in _yaml_comments("ref: manifest-owned  # v6.0.3\n")

    def test_a_hash_inside_double_quotes_is_not_a_comment(self):
        assert _yaml_comments('summary: "pass #1 of 2"\n') == ""

    def test_a_hash_inside_single_quotes_is_not_a_comment(self):
        assert _yaml_comments("summary: 'issue #329'\n") == ""

    def test_a_url_fragment_is_not_a_comment(self):
        # `reference:` fields carry real URLs; a `#` with no preceding space is part of the token.
        assert _yaml_comments("reference: https://example.com/x#frag\n") == ""

    def test_a_declaration_line_yields_nothing(self):
        # The ownership location must stay invisible to the guard, or the pin would flag itself.
        assert _yaml_comments("      repo: obra/superpowers\n      ref: v6.0.3\n") == ""


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
        """The two-literal drift guard — for the recipes that still HAVE two literals.

        Phase 3 of #329 retires this shape one recipe at a time. A recipe on `install.refs:` has a
        DERIVED cache key and no pin literal in the script at all, so there is nothing to keep in
        sync and this assertion would be checking for a hash inside a shell file. The successor
        guarantee is asserted below, in `test_a_refs_recipe_carries_no_pin_literal_at_all` — strictly
        stronger, because "the pin exists once" cannot drift, where "two copies agree" can.
        """
        r = _recipe(name)
        inst = r.install
        assert inst is not None and inst.script
        if inst.refs:
            pytest.skip(f"{name} is on install.refs: — see the refs test below")
        body = (r.root / inst.script).read_text(encoding="utf-8")
        assert f'"{inst.cache}"' in body, (
            f"{name}: install.cache {inst.cache!r} does not appear as a pinned literal in "
            f"{inst.script} — the host cache would be keyed to a ref the script never fetches, "
            "so it is populated once and never refreshed."
        )

    def test_a_refs_recipe_carries_no_pin_literal_at_all(self, name):
        """The successor to the drift guard: for a refs recipe, the pin exists in ONE place.

        Asserted as "no ref value appears anywhere in the script", not merely "the old variable is
        gone": a reader re-introducing the tag as a different variable name would satisfy the weaker
        check while recreating exactly the drift `install.refs:` removes.

        Checked against the RAW file, comments included. The first version of this test read the
        comment-stripped body and passed while the very comment explaining the migration still spelled
        out `v1.9.0` — caught in review of PR #352. A comment carrying the version is the "kept in
        sync by a comment" failure this epic exists to delete; it just fails more quietly than a
        shell variable, and a test that cannot see it is not guarding the property it claims.

        `repo` gets the same treatment as `ref`. A script that reads the ref from env but hard-codes
        `owner/repo` still ignores half the manifest, so changing `repo:` would move nothing.
        """
        r = _recipe(name)
        inst = r.install
        assert inst is not None and inst.script
        if not inst.refs:
            pytest.skip(f"{name} has not migrated to install.refs: yet")
        raw = (r.root / inst.script).read_text(encoding="utf-8")
        # recipe.yaml's COMMENTS are held to the same rule as the script. The manifest is where
        # `repo:`/`ref:` legitimately live, so only comment TEXT is scanned — but a comment beside
        # the declaration is the easiest copy of all to write and the last one anybody re-reads.
        # Caught in review of PR #353, where a comment three lines above the `refs:` block repeated
        # the repo while claiming values are never repeated.
        manifest_comments = _yaml_comments((r.root / "recipe.yaml").read_text(encoding="utf-8"))
        for key, ref in inst.refs.items():
            for field, value in (("ref", ref.ref), ("repo", ref.repo)):
                assert value not in raw, (
                    f"{name}: {inst.script} still contains the literal {value!r} ({field} of ref "
                    f"'{key}') — the pin must live only in install.refs, in comments too, or the "
                    "two copies can drift again."
                )
                assert value not in manifest_comments, (
                    f"{name}: a recipe.yaml COMMENT repeats {value!r} ({field} of ref '{key}'). "
                    "The declaration below it is the one source; a comment copy drifts silently."
                )
            for var in (f"HARNESSED_REF_{key.upper()}", f"HARNESSED_REPO_{key.upper()}"):
                assert var in raw, (
                    f"{name}: {inst.script} never reads ${var}, so that half of the declared ref "
                    f"'{key}' is inert data — `harnessed update` would rewrite the manifest and the "
                    "script would keep fetching what it always did."
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

    def test_the_dockerfile_body_carries_only_the_root_step(self):
        # INVERTED by bd harnessed-8px.21.4. install: used to be emitted BEFORE this recipe's
        # Dockerfile body so the root steps layered on top of it. Now every Dockerfile body runs at
        # BUILD and every install at container runtime, so the orders are decoupled entirely.
        #
        # That is only safe because no Dockerfile body consumes its own install output — all five
        # were read on 2026-07-27 and none does. gstack's `chown -R harnessed:harnessed ~/.bun`
        # targets what the BASE image installed, not what its install.sh writes.
        r = _recipe("gstack")
        body = (r.root / "Dockerfile").read_text(encoding="utf-8")
        assert "USER root" in body
        instructions = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        assert not any("install.sh" in ln for ln in instructions), (
            "a Dockerfile body must not invoke its own install script — the executor owns that now"
        )

    def test_install_fails_loudly_when_bun_is_missing(self):
        # A host launch without bun cannot run upstream's ./setup. Failing loudly is the acceptance
        # criterion of bd harnessed-8px.1 — the bug WAS the silence.
        script = (CATALOG / "recipes" / "gstack" / "install.sh").read_text(encoding="utf-8")
        assert "command -v bun" in script
        assert "exit 1" in script


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

    def test_the_container_executor_runs_an_install_step_for_each(self, monkeypatch):
        from harnessed import launcher

        recipes = [_recipe(n) for n in CONTENT_RECIPES]
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(cmd))
        launcher._run_container_installs(
            "podman", "s", "claude", "img", recipes, "cfgvol", "toolsvol",
        )
        text = "\n".join(" ".join(c) for c in calls)
        for name in CONTENT_RECIPES:
            assert f"{emit.CTR_RECIPE_DIR}/{name}/install.sh" in text

    def test_no_install_cache_can_ship_in_the_image(self):
        # A cached clone left behind would have baked the whole upstream repo into every derived
        # image, which is why the build had to `rm -rf` it in the same layer. bd harnessed-8px.21.4
        # removes the hazard at the source: the image has no install step at all, so the cache is a
        # runtime bind mount of the SHARED host cache and is never a layer in the first place.
        from harnessed.emit import write_derived_dockerfile
        import tempfile
        from pathlib import Path as _P

        with tempfile.TemporaryDirectory() as td:
            body = write_derived_dockerfile(
                _P(td), "s", "claude", [_recipe(n) for n in CONTENT_RECIPES]
            ).read_text(encoding="utf-8")
        instructions = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        assert not any(emit.CTR_INSTALL_CACHE in ln for ln in instructions)
        assert not any("install.sh" in ln for ln in instructions)
