"""The pin HOLD marker — bd harnessed-c5t.

A pin can be correct AND deliberately frozen. `harnessed update` (bd harnessed-tfm) exists to find
stale pins and offer to bump them, but some pins must never be offered: a SKILL is agent
INSTRUCTIONS executed with the agent's full tool permissions, so a skill upgrade is a
prompt-injection / instruction-substitution surface, not a CVE. No scanner in the osv/trivy/grype
family vets it. Skill pins therefore upgrade only when a human has diffed the new SHA.

That decision needs a MACHINE-READABLE seam, and `install.cache` is not one: a cache key can be
used for any combination of CLI and content, so its presence classifies nothing about pin class.
Hence `install.hold` — a non-empty reason string, the same idiom `install.system` already uses,
meaning "every pin behind this install script is manual-upgrade-only".

The contract tfm reads:

  * `recipe.install.hold` is not None  -> pins discovered in that recipe's install.sh / install.cache
    are INFORMATIONAL ONLY: never in the interactive bump set, never a --check failure.
  * `recipe.tools_hold[spec]`          -> the same, for one entry of the declarative `tools:` list.

The reason string is not decoration. It is printed to the human who has to decide, which is why an
empty one is rejected — a hold nobody can justify is a hold nobody can lift.
"""

import json
import re
from pathlib import Path

import pytest

from harnessed.schema import SchemaError, load_recipe

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

SKILL_HOLD_REASON = "skill content: agent instructions no scanner vets"


def _recipe(tmp_path, name="r", *, install: str | None = None, extra: str = ""):
    """A loadable recipe dir, optionally carrying an `install:` block and its script file."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    body = f"name: {name}\n{extra}"
    if install is not None:
        body += install
    (d / "recipe.yaml").write_text(body)
    (d / "install.sh").write_text("true\n")
    return load_recipe(d, strict=True)


class TestInstallHold:
    """`install.hold` — the recipe-level declaration, held as a unit."""

    def test_hold_parses_into_the_install_spec(self, tmp_path):
        r = _recipe(
            tmp_path,
            install=f"install:\n  script: install.sh\n  hold: {SKILL_HOLD_REASON!r}\n",
        )
        assert r.install is not None, "expected install block to be parsed"
        assert r.install.hold == SKILL_HOLD_REASON

    def test_absent_hold_is_none(self, tmp_path):
        """The default is NOT held. A pin is offered for bumping unless a recipe says otherwise —
        holding by accident is how a genuinely stale pin hides forever."""
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n")
        assert r.install is not None, "expected install block to be parsed"
        assert r.install.hold is None

    def test_hold_is_whitespace_stripped(self, tmp_path):
        r = _recipe(tmp_path, install="install:\n  script: install.sh\n  hold: '  why  '\n")
        assert r.install is not None, "expected install block to be parsed"
        assert r.install.hold == "why"

    @pytest.mark.parametrize("bad", ["''", "'   '", "true", "[]"])
    def test_hold_must_be_a_non_empty_reason_string(self, tmp_path, bad):
        """`hold: true` is the tempting shorthand and is rejected on purpose: the string is shown to
        the human deciding whether to lift the hold, so a bare boolean throws away the only part
        that makes the decision reviewable."""
        with pytest.raises(SchemaError, match=re.escape("install.hold")):
            _recipe(tmp_path, install=f"install:\n  script: install.sh\n  hold: {bad}\n")

    def test_hold_without_a_script_is_rejected(self, tmp_path):
        """A root-only install (`system:` alone) has no script, hence no pins behind a script to
        hold — the same reasoning that rejects `cache` without `script`."""
        with pytest.raises(SchemaError, match=re.escape("install.hold")):
            _recipe(
                tmp_path,
                install=f"install:\n  system: 'apt-get cmake'\n  hold: {SKILL_HOLD_REASON!r}\n",
            )

    def test_hold_coexists_with_cache_and_system(self, tmp_path):
        r = _recipe(
            tmp_path,
            install=(
                "install:\n  script: install.sh\n  cache: v6.0.3\n"
                f"  system: 'apt-get cmake'\n  hold: {SKILL_HOLD_REASON!r}\n"
            ),
        )
        assert r.install is not None, "expected install block to be parsed"
        assert (r.install.cache, r.install.system, r.install.hold) == (
            "v6.0.3", "apt-get cmake", SKILL_HOLD_REASON,
        )

    def test_unknown_install_field_is_still_rejected(self, tmp_path):
        """Adding `hold` to the allowlist must not turn the allowlist off."""
        with pytest.raises(SchemaError, match="unknown field"):
            _recipe(tmp_path, install="install:\n  script: install.sh\n  holdd: x\n")


class TestToolsHold:
    """`tools:` entries gain an optional mapping form so ONE hold mechanism covers both surfaces."""

    def test_plain_string_entries_still_parse_and_hold_nothing(self, tmp_path):
        r = _recipe(tmp_path, extra="tools:\n  - npm:ccstatusline@2.2.22\n")
        assert r.tools == ["npm:ccstatusline@2.2.22"]
        assert r.tools_hold == {}

    def test_mapping_form_splits_spec_from_reason(self, tmp_path):
        """The spec still lands in `tools` verbatim — emit/launcher iterate that list to build the
        `mise use -g` layer and must not learn about holds."""
        r = _recipe(
            tmp_path,
            extra="tools:\n  - spec: github:foo/bar@1.2.3\n    hold: 'upstream 2.x drops our API'\n",
        )
        assert r.tools == ["github:foo/bar@1.2.3"]
        assert r.tools_hold == {"github:foo/bar@1.2.3": "upstream 2.x drops our API"}

    def test_both_forms_mix_in_one_list(self, tmp_path):
        r = _recipe(
            tmp_path,
            extra=(
                "tools:\n"
                "  - npm:ccstatusline@2.2.22\n"
                "  - spec: github:foo/bar@1.2.3\n    hold: 'pinned deliberately'\n"
            ),
        )
        assert r.tools == ["npm:ccstatusline@2.2.22", "github:foo/bar@1.2.3"]
        assert r.tools_hold == {"github:foo/bar@1.2.3": "pinned deliberately"}

    def test_mapping_form_still_enforces_the_pin(self, tmp_path):
        """A hold is not an excuse to float. Held or not, the ref must be explicit."""
        with pytest.raises(SchemaError, match="must be pinned"):
            _recipe(
                tmp_path,
                extra="tools:\n  - spec: github:foo/bar@latest\n    hold: 'held'\n",
            )

    def test_mapping_form_requires_a_spec(self, tmp_path):
        with pytest.raises(SchemaError, match="spec"):
            _recipe(tmp_path, extra="tools:\n  - hold: 'held but nameless'\n")

    @pytest.mark.parametrize("bad", ["''", "true"])
    def test_mapping_form_hold_must_be_a_non_empty_reason_string(self, tmp_path, bad):
        with pytest.raises(SchemaError, match="hold"):
            _recipe(
                tmp_path,
                extra=f"tools:\n  - spec: npm:x@1.0.0\n    hold: {bad}\n",
            )

    def test_unknown_key_in_the_mapping_form_is_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="unknown"):
            _recipe(
                tmp_path,
                extra="tools:\n  - spec: npm:x@1.0.0\n    reason: 'wrong key'\n",
            )


class TestCatalogDeclaresTheHold:
    """The marker exists to be READ. A comment in a recipe is not readable by tfm."""

    def test_mikes_universal_setup_declares_its_skill_hold(self):
        """PR #141 fetches oakoss/agent-skills + blader/humanizer at pinned SHAs from install.sh and
        recorded the HOLD as prose only. This is that prose promoted to a field."""
        r = load_recipe(CATALOG / "recipes" / "mikes-universal-setup", strict=True)
        assert r.install is not None and r.install.hold, (
            "mikes-universal-setup fetches SKILL content at pinned SHAs — it must declare "
            "install.hold so harnessed update never offers to auto-bump them"
        )
        assert "skill" in r.install.hold.lower(), (
            "the hold reason is printed to the human deciding whether to lift it — it must say "
            f"WHAT is held, got {r.install.hold!r}"
        )

    def test_no_recipe_holds_without_a_reason(self):
        """Sweep the whole catalog: every hold that exists carries a justification."""
        for manifest in sorted((CATALOG / "recipes").glob("*/recipe.yaml")):
            r = load_recipe(manifest.parent, strict=True)
            if r.install is not None and r.install.hold is not None:
                assert r.install.hold.strip(), f"{manifest}: empty install.hold"
            for spec, reason in r.tools_hold.items():
                assert reason.strip(), f"{manifest}: empty hold on tools entry {spec!r}"


class TestJsonSchemaDocumentsTheMarker:
    """The published JSON schema drives editor completion — a field it omits is a field nobody
    discovers, and `additionalProperties: false` would make a correct recipe look invalid."""

    def test_install_hold_is_declared(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "recipe.schema.json").read_text())
        install = schema["properties"]["install"]
        assert "hold" in install["properties"], "recipe.schema.json must document install.hold"
        assert install["properties"]["hold"]["minLength"] == 1
        assert install["dependentRequired"]["hold"] == ["script"]

    def test_tools_accepts_both_the_string_and_the_mapping_form(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "recipe.schema.json").read_text())
        items = schema["properties"]["tools"]["items"]
        forms = items.get("oneOf") or items.get("anyOf")
        assert forms, "tools items must accept a string OR a {spec, hold} mapping"
        assert any(f.get("type") == "string" for f in forms)
        mapping = next(f for f in forms if f.get("type") == "object")
        assert mapping["required"] == ["spec"]
        assert mapping["additionalProperties"] is False
        assert set(mapping["properties"]) == {"spec", "hold"}
