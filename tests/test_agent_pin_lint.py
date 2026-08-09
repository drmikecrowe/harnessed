"""A6 / AC-9 — the pin lint reaches AGENT images, and can see ABSENT as well as FLOATING.

Spec: `.agents/plans/2026-08-08-recipe-rtk-pattern.md` §3 AC-9, §Phase A/A6.

`validate_pin` has only ever read RECIPE Dockerfiles (`assemble.py:195`). Agent images —
`catalog/base/Dockerfile.harnessed-*` — were never linted at all, which is how three agents reached
`main` acquiring their CLI with no version at all. A floating `@latest` was already rejected
everywhere it appeared; the gap this closes is the shape with NO marker to find, where the absence
of a version is the whole defect and there is no token to match on.

The rule is stated POSITIVELY, deliberately, mirroring `_IMMUTABLE_REF_RE`'s reasoning three
hundred lines up: an acquisition is acceptable only if it can be SEEN to carry a version. A
negative rule ("reject the bad spellings") would pass every spelling nobody enumerated, and the
whole class here is "nothing was written."

NOT wired into `assemble.py` by this change — see the plan's REVISION 9. claude and codex still
acquire unpinned, so switching the gate on would fail their builds while A2/A3 remain deferred.
The tests below therefore call the function directly, including against the three REAL bodies.
"""

from pathlib import Path

import pytest

from harnessed.schema import PinValidationError, validate_agent_pin

REPO = Path(__file__).resolve().parent.parent
AGENT_DOCKERFILES = REPO / "catalog" / "base"


def _body(harness: str) -> str:
    return (AGENT_DOCKERFILES / f"Dockerfile.harnessed-{harness}").read_text(encoding="utf-8")


class TestFloatingIsStillRejected:
    """The pre-existing class, now reaching agents. Regression armor, not new behaviour."""

    @pytest.mark.parametrize("line", [
        "RUN mise use -g npm:@openai/codex@latest",
        "RUN git clone --branch main https://example.com/x",
        "FROM something:latest",
    ])
    def test_a_floating_ref_raises(self, line):
        with pytest.raises(PinValidationError, match=r"floating|moving"):
            validate_agent_pin("codex", line, unpinnable={})


class TestTheOtherTwoImmutabilityGatesReachAgentsToo:
    """`validate_agent_pin` inherits three checks from `validate_pin`, not one.

    Added after mutation testing: deleting the clone-ref and archive-ref checks outright left every
    other test in this file passing, because `--branch main` is caught by the FLOATING regex before
    those checks are ever reached. The shapes below are the ones only these two gates can see — a
    branch that is mutable without being called `main` (bd harnessed-1t4.6, where
    `--branch "feat/per-server-tool-filtering"` walked through the earlier gate), and an archive URL
    at a moving ref. An agent image is exactly as entitled to those defects as a recipe is.
    """

    def test_a_feature_branch_clone_is_rejected(self):
        body = 'RUN git clone --branch "feat/some-work" https://github.com/o/r /tmp/r\n'
        with pytest.raises(PinValidationError) as exc:
            validate_agent_pin("x", body, unpinnable={})
        message = str(exc.value)
        assert "moving ref" in message
        # The remedy, not just the complaint. An error that names a defect without naming the fix
        # sends the reader to the source to find out what shape is acceptable — and mutation
        # testing showed nothing here asserted this sentence at all, so it was free to say
        # anything, including the opposite.
        assert "clone a tag" in message

    def test_a_tag_clone_is_accepted(self):
        body = 'RUN git clone --branch "v1.2.3" https://github.com/o/r /tmp/r\n'
        validate_agent_pin("x", body, unpinnable={})

    def test_an_archive_at_a_branch_is_rejected(self):
        body = "RUN curl -fsSL https://github.com/o/r/archive/refs/heads/main.tar.gz -o /tmp/r.tgz\n"
        with pytest.raises(PinValidationError, match="archive"):
            validate_agent_pin("x", body, unpinnable={})

    def test_an_unpinnable_declaration_excuses_neither(self):
        """Same principle as the floating case: `unpinnable:` concedes that no selector exists.
        A clone or archive ref IS a selector, used mutably — a different defect, not a waiver."""
        body = 'RUN git clone --branch "feat/some-work" https://github.com/o/r /tmp/r\n'
        with pytest.raises(PinValidationError, match="moving ref"):
            validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "reason"})


class TestAbsentIsRejected:
    """The new class: no version written at all, so there is no token to match on."""

    def test_a_mise_spec_with_no_version_raises(self):
        body = "RUN mise use -g npm:@openai/codex && mise install\n"
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("codex", body, unpinnable={})

    def test_a_piped_installer_with_no_version_raises(self):
        body = "RUN curl -fsSL https://claude.ai/install.sh | bash\n"
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("claude", body, unpinnable={})

    def test_the_error_names_the_agent_and_the_installer_url(self):
        """A gate that says 'something is unpinned' sends the reader hunting; this one must not.

        Asserting the ABSENCE of the shell noise as well as the presence of the URL, because
        mutation testing showed the presence check alone was a superset assertion: dumping the
        whole RUN line also contains the URL, so every mutant that broke the URL extraction and
        fell back to the raw line survived. The property is that the error is PRECISE, and only
        the negative half of this test can tell precise from verbose.
        """
        body = "RUN curl -fsSL --retry 3 https://claude.ai/install.sh | bash\n"
        with pytest.raises(PinValidationError) as exc:
            validate_agent_pin("claude", body, unpinnable={})
        message = str(exc.value)
        assert "claude" in message
        assert "https://claude.ai/install.sh" in message
        assert "--retry" not in message and "curl" not in message


class TestPinnedIsAccepted:
    """Whatever else it does, it must not reject the agents that ARE correctly pinned."""

    @pytest.mark.parametrize("body", [
        'RUN mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}"\n',
        'RUN curl -fsSL https://opencode.ai/install | bash -s -- --version "${OPENCODE_VERSION}"\n',
        "RUN mise use -g npm:@openai/codex@0.139.0\n",
    ])
    def test_a_versioned_acquisition_passes(self, body):
        validate_agent_pin("x", body, unpinnable={})

    def test_a_line_that_acquires_nothing_is_not_examined(self):
        validate_agent_pin("x", "RUN mkdir -p /home/harnessed/.codex\nCOPY a b\n", unpinnable={})

    @pytest.mark.parametrize("indent", ["", "    ", "\t"])
    def test_a_comment_describing_the_problem_does_not_trigger_the_gate(self, indent):
        """Same reasoning `validate_pin` already applies: prose about the rule is not a violation.

        Parametrized over indentation after mutation testing: swapping `lstrip` for `rstrip` in the
        comment check survived, because every comment in this file started at column zero. An
        INDENTED comment — which is how these Dockerfiles annotate continuation lines — would then
        have been linted as code, and this gate would fail an agent over its own documentation.
        """
        body = f"{indent}# the old line was: curl -fsSL https://claude.ai/install.sh | bash\nRUN true\n"
        validate_agent_pin("claude", body, unpinnable={})


class TestTheCarveOutIsNarrow:
    """`FROM harnessed-base:latest` is exempt. Exactly that, and nothing adjacent to it.

    The exemption exists because `emit.py` GENERATES the identical form for derived stack images —
    it names a first-party image built by this same pipeline, so there is no upstream to float
    against. Recipe Dockerfiles never needed it because they carry no FROM at all. An exemption
    this convenient is worth three tests proving it does not spread.
    """

    def test_the_first_party_base_is_exempt(self):
        validate_agent_pin("omp", "FROM harnessed-base:latest\nRUN true\n", unpinnable={})

    def test_the_generated_parameterised_form_is_exempt(self):
        """What `emit.py` writes for derived images."""
        validate_agent_pin("omp", "FROM harnessed-${HARNESS}:latest\nRUN true\n", unpinnable={})

    @pytest.mark.parametrize("line", [
        "FROM ubuntu:latest",
        "FROM harnessedfoo:latest",
        "FROM docker.io/harnessed-base:latest",
    ])
    def test_a_third_party_latest_still_fails(self, line):
        with pytest.raises(PinValidationError, match="floating"):
            validate_agent_pin("x", line + "\nRUN true\n", unpinnable={})

    def test_latest_anywhere_but_a_FROM_line_still_fails(self):
        body = "FROM harnessed-base:latest\nRUN podman pull registry/thing:latest\n"
        with pytest.raises(PinValidationError, match="floating"):
            validate_agent_pin("x", body, unpinnable={})


class TestBareMiseInstallAcquiresNothing:
    """`mise install` with no argument installs what the config already declares.

    Regression for a defect this file's real-body tests caught: the spec pattern swallowed the
    following shell operator, so `mise use -g "github:owner/repo@${VER}" && mise install` reported
    an unpinned acquisition of '&&'. A correctly pinned agent was being failed by the gate.
    """

    def test_a_trailing_bare_install_does_not_trip_the_gate(self):
        body = 'RUN mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}" && mise install\n'
        validate_agent_pin("omp", body, unpinnable={})

    def test_a_real_unpinned_spec_beside_a_bare_install_still_fails(self):
        """The fix must not have bought its silence by ignoring the whole line."""
        body = "RUN mise use -g npm:@openai/codex && mise install\n"
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("codex", body, unpinnable={})


class TestUnpinnableSuppresses:
    def test_a_declaration_suppresses_the_error(self):
        body = "RUN curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
        validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "no version selector"})

    def test_the_declaration_is_what_suppresses_it(self):
        """AC-9 names this explicitly: an UNDECLARED unpinned agent must still fail. Without this
        test the suppression could be keyed on the agent's NAME and nobody would notice."""
        body = "RUN curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
        with pytest.raises(PinValidationError):
            validate_agent_pin("antigravity", body, unpinnable={})

    def test_a_declaration_does_NOT_excuse_a_floating_ref(self):
        """UNPINNABLE means 'no version selector exists', not 'pinning rules are waived here'.
        A floating ref is a version selector used WRONGLY, which is a different defect and one the
        declaration must not launder — otherwise `unpinnable:` becomes the escape hatch that
        `hold:` was explicitly stopped from becoming (schema.py, tools: hold semantics)."""
        body = "RUN mise use -g npm:@openai/codex@latest\n"
        with pytest.raises(PinValidationError, match="floating"):
            validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "reason"})


class TestAgainstTheRealBodies:
    """AC-9's own test instruction: feed it each of the three real pre-migration bodies.

    These assert the CURRENT state of the tree, so they are also the tripwire for A2/A3: when codex
    and claude get pinned, the two xfail-shaped assertions below start failing and must be flipped
    to `validate_agent_pin(...)` passing. That is deliberate — a test that silently keeps passing
    through the migration would prove nothing about it.
    """

    def test_codex_is_currently_absent(self):
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("codex", _body("codex"), unpinnable={})

    def test_claude_is_currently_absent(self):
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("claude", _body("claude"), unpinnable={})

    def test_antigravity_passes_only_because_it_declares(self):
        body = _body("antigravity")
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("antigravity", body, unpinnable={})
        validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "declared"})

    @pytest.mark.parametrize("harness", ["omp", "opencode"])
    def test_the_migrated_agents_pass(self, harness):
        validate_agent_pin(harness, _body(harness), unpinnable={})

    def test_every_agent_is_covered_by_this_file(self):
        """If someone adds a sixth agent, this file must be updated rather than silently not
        covering it — the failure mode A6 exists to prevent is an agent nobody looked at."""
        shipped = {p.name.removeprefix("Dockerfile.harnessed-")
                   for p in AGENT_DOCKERFILES.glob("Dockerfile.harnessed-*")}
        assert shipped == {"base", "antigravity", "claude", "codex", "omp", "opencode"}
