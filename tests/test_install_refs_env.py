"""Phase 0, unit 2 — what `install.refs:` actually DOES: rules 2 and 5.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §D1a, "The `install.refs` contract".
Unit 1 (#337) landed the declaration and its derived cache key; nothing consumed it. This unit
makes it load-bearing:

  rule 2  key -> env is deterministic and TOTAL: `oakoss` yields exactly HARNESSED_REF_OAKOSS and
          HARNESSED_REPO_OAKOSS, and the repo var carries `owner/repo` rather than a URL so a
          recipe switching from `git clone` to a tarball needs no manifest change.
  rule 5  `hold:` scope is the single ref — a recipe with three refs may hold one and auto-bump two.

The contract calls out rule 2 specifically as the one "an implementer is most likely to satisfy
'close enough'", and asks for a test over a real multi-ref recipe's generated environment. That is
`TestTheGeneratedEnvironment` below.
"""

import pytest

from harnessed.emit import install_env
from harnessed.schema import load_recipe
from harnessed import update as pinupdate

_TWO_REFS = """\
name: caveman
install:
  script: install.sh
  refs:
    caveman:
      repo: JuliusBrussee/caveman
      ref: v1.9.0
    oakoss:
      repo: oakoss/agent-skills
      ref: v1.0.0
      hold: 'structural: repo publishes no releases or tags'
"""


def _recipe(tmp_path, body: str = _TWO_REFS, name: str = "r"):
    d = tmp_path / name
    # exist_ok: a test that loads the same recipe twice (e.g. once per mode) rewrites it rather
    # than colliding. Same body, same result — the second write is a no-op in effect.
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    (d / "install.sh").write_text("#!/usr/bin/env bash\ntrue\n")
    return d


def _env(tmp_path, body: str = _TWO_REFS, *, mode: str = "container"):
    return install_env(
        load_recipe(_recipe(tmp_path, body)), mode=mode, harness="claude",
        config_dir="/c", cache_dir="/x", bin_dir="/b", home_shim="/h",
    )


class TestRule2KeyToEnvIsDeterministicAndTotal:
    def test_each_key_yields_exactly_its_two_variables(self, tmp_path):
        env = _env(tmp_path)
        assert env["HARNESSED_REF_CAVEMAN"] == "v1.9.0"
        assert env["HARNESSED_REPO_CAVEMAN"] == "JuliusBrussee/caveman"
        assert env["HARNESSED_REF_OAKOSS"] == "v1.0.0"
        assert env["HARNESSED_REPO_OAKOSS"] == "oakoss/agent-skills"

    def test_the_repo_var_is_owner_slash_repo_not_a_url(self, tmp_path):
        """The script composes the URL. If harnessed emitted one, a recipe moving from `git clone`
        to a tarball fetch would need a manifest change for a decision that is the script's."""
        repo = _env(tmp_path)["HARNESSED_REPO_CAVEMAN"]
        assert repo == "JuliusBrussee/caveman"
        assert "://" not in repo and not repo.endswith(".git")

    def test_the_mapping_is_upper_casing_and_nothing_cleverer(self, tmp_path):
        """Rule 1 restricted the key charset precisely so this transformation stays total. A key
        of `some_repo` must not acquire a dash, a dot, or a stripped underscore on the way."""
        body = _TWO_REFS.replace("caveman:\n      repo:", "some_repo:\n      repo:", 1)
        env = _env(tmp_path, body)
        assert "HARNESSED_REF_SOME_REPO" in env and "HARNESSED_REPO_SOME_REPO" in env

    def test_a_recipe_with_no_refs_emits_no_ref_variables(self, tmp_path):
        env = _env(tmp_path, "name: r\ninstall:\n  script: install.sh\n")
        assert not [k for k in env if k.startswith(("HARNESSED_REF_", "HARNESSED_REPO_"))]

    def test_the_same_KEYS_are_emitted_in_both_modes(self, tmp_path):
        """`install_env`'s standing invariant, which this change must not break: the KEY SET is
        identical host and container, because an author who tests one mode must not discover a
        missing variable in the other. Ref VALUES are mode-independent too — a ref is a ref."""
        container = _env(tmp_path, mode="container")
        host = _env(tmp_path, _TWO_REFS, mode="host")
        assert set(container) == set(host)
        for k in container:
            if k.startswith(("HARNESSED_REF_", "HARNESSED_REPO_")):
                assert container[k] == host[k]


class TestTheGeneratedEnvironmentForARealMultiRefRecipe:
    """The contract asks for this by name — rule 2 is the one most likely to be satisfied
    'close enough', and a whole-environment assertion is what catches close-enough."""

    def test_the_full_ref_namespace_is_exactly_what_the_manifest_declares(self, tmp_path):
        env = _env(tmp_path)
        emitted = {k: v for k, v in env.items()
                   if k.startswith(("HARNESSED_REF_", "HARNESSED_REPO_"))}
        assert emitted == {
            "HARNESSED_REF_CAVEMAN": "v1.9.0",
            "HARNESSED_REPO_CAVEMAN": "JuliusBrussee/caveman",
            "HARNESSED_REF_OAKOSS": "v1.0.0",
            "HARNESSED_REPO_OAKOSS": "oakoss/agent-skills",
        }, "no extra variables, no missing ones — the mapping is total in both directions"


class TestRule5HoldIsPerRef:
    def _report(self, tmp_path, body: str = _TWO_REFS, latest: str = "v2.0.0"):
        return pinupdate.build_report(
            [_recipe(tmp_path, body)],
            resolve=lambda _b, _n: [pinupdate.Release(version=latest, published=None)],
            minimum_release_age_minutes=0,
        )

    def test_an_unheld_ref_is_offered_for_bump(self, tmp_path):
        report = self._report(tmp_path)
        assert "v1.9.0" in [f.pin.current for f in report.stale]

    def test_a_held_ref_is_listed_but_never_offered(self, tmp_path):
        """Three refs may hold one and auto-bump two — the hold attaches to the ref, not the
        recipe, which is what distinguishes it from the recipe-wide `install.hold`."""
        report = self._report(tmp_path)
        held = [(f.pin.name, f.pin.current) for f in report.held]
        assert ("oakoss/agent-skills", "v1.0.0") in held
        assert "oakoss/agent-skills" not in [f.pin.name for f in report.stale], (
            "a held ref must never be OFFERED, even when a newer version exists"
        )

    def test_the_hold_reason_travels_into_the_report(self, tmp_path):
        """A hold with no visible reason is one nobody can decide whether to lift."""
        report = self._report(tmp_path)
        reasons = [f.pin.hold for f in report.held if f.pin.hold]
        assert any("no releases or tags" in r for r in reasons)

    def test_refs_resolve_against_their_repo_not_the_recipe_name(self, tmp_path):
        """The resolver must ask GitHub about `JuliusBrussee/caveman`, not about `caveman`."""
        asked: list[tuple[str, str]] = []

        def resolve(backend, name):
            asked.append((backend, name))
            return [pinupdate.Release(version="v2.0.0", published=None)]

        pinupdate.build_report([_recipe(tmp_path)], resolve=resolve, minimum_release_age_minutes=0)
        assert ("github", "JuliusBrussee/caveman") in asked


class TestTheRefPinCarriesItsIdentity:
    """A Pin is not just a version — the report prints `recipe (file)` and `apply` DISPATCHES on
    `pin.file.suffix` to choose a rewriter. Mutation testing found every one of these fields
    unasserted: blanking `recipe`, `file`, `spec` or `key` left all tests green while producing a
    report row that names nothing and an apply path that cannot route.
    """

    def _pin(self, tmp_path):
        pins = pinupdate.discover_pins(_recipe(tmp_path))
        return next(p for p in pins if p.name == "JuliusBrussee/caveman")

    def test_it_names_its_recipe_and_manifest(self, tmp_path):
        pin = self._pin(tmp_path)
        assert pin.recipe == "caveman"
        assert pin.file.name == "recipe.yaml", "apply() dispatches on this suffix"

    def test_it_carries_the_ref_key_for_the_report_identity(self, tmp_path):
        assert self._pin(tmp_path).key == "caveman"

    def test_its_spec_shows_repo_and_ref_together(self, tmp_path):
        """What the human reads in the report row — a bare version would not say which repo."""
        assert self._pin(tmp_path).spec == "JuliusBrussee/caveman@v1.9.0"

    def test_it_is_resolvable_rather_than_opaque(self, tmp_path):
        """The whole point of D1a: Family B pins stop being unanswerable."""
        assert self._pin(tmp_path).resolvable


class TestTheDerivedCacheIsNotReportedAsAnUpstreamPin:
    """With `refs:`, `install.cache` is DERIVED — reporting it would be a second entry for the
    same underlying pins, and a bump offer against a digest nobody can act on."""

    def test_a_derived_cache_produces_no_cache_pin(self, tmp_path):
        report = pinupdate.build_report(
            [_recipe(tmp_path)],
            resolve=lambda _b, _n: [pinupdate.Release(version="v2.0.0", published=None)],
            minimum_release_age_minutes=0,
        )
        everything = report.stale + report.held + report.current + report.unresolved + report.cooling
        assert not [f for f in everything if f.pin.name == "install.cache"]

    def test_a_HAND_WRITTEN_cache_is_still_reported(self, tmp_path):
        """NC-5: a recipe with no `refs:` is unchanged, and that includes its cache pin."""
        body = "name: r\ninstall:\n  script: install.sh\n  cache: v1.0.0\n"
        report = pinupdate.build_report(
            [_recipe(tmp_path, body)],
            resolve=lambda _b, _n: [], minimum_release_age_minutes=0,
        )
        everything = report.stale + report.held + report.current + report.unresolved + report.cooling
        assert [f for f in everything if f.pin.name == "install.cache"]


@pytest.mark.parametrize("mode", ["container", "host"])
def test_the_install_env_key_set_still_carries_no_reserved_collision(tmp_path, mode):
    """Rule 3 again, now that the namespace is actually populated: every emitted
    HARNESSED_REF_*/HARNESSED_REPO_* must come from a declared ref and nothing else."""
    env = _env(tmp_path, mode=mode)
    declared = {"CAVEMAN", "OAKOSS"}
    for key in env:
        for prefix in ("HARNESSED_REF_", "HARNESSED_REPO_"):
            if key.startswith(prefix):
                assert key[len(prefix):] in declared, f"{key} is not backed by a declared ref"
