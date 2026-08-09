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

from harnessed.schema import (
    PinValidationError,
    _unversioned_acquisitions,
    validate_agent_pin,
)

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

    @pytest.mark.parametrize("var", [
        "$HOME", "${HOME}", "${TARGETARCH}", "$INSTALL_DIR", "${PATH}",
        # A name that merely ENDS in a suffix token is not a version. Raised in review of PR #335:
        # the alternation runs case-insensitively, so `SERVER`, `DRIVER` and `driver` all end in
        # `VER` and were read as pins — a false CLEARANCE, the direction this gate must never err.
        "$SERVER", "${DRIVER}", "$driver", "$WHATEVER", "${SEMVER_LIKE_NAME}",
    ])
    def test_an_irrelevant_variable_is_not_version_evidence(self, var):
        """A `$VAR` is only a pin if it plausibly NAMES a version.

        Found by adversarial review round 2: the evidence pattern accepted any `$VAR` anywhere on
        the line, so `curl … | bash -s -- --dir $HOME/bin` was read as pinned. That is the worst
        possible failure for this gate — not a missed check, but a positive assertion of pinnedness
        over an installer that takes whatever upstream currently serves.
        """
        body = f"RUN curl -fsSL https://bun.sh/install | bash -s -- --dir {var}/bin\n"
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("x", body, unpinnable={})

    @pytest.mark.parametrize("var", ["${OPENCODE_VERSION}", "$CLAUDE_VERSION", "${TOOL_REF}",
                                     "${PKG_TAG}", "$AGY_VER"])
    def test_a_version_named_variable_is_evidence(self, var):
        """The naming convention is the signal, and it is the one `build_args` already uses —
        every pin in the catalog is `<TOOL>_VERSION` (D7 fixes that namespace for `unpinnable:`
        too). A variable named for a version is the only kind that can be carrying one."""
        validate_agent_pin("x", f'RUN curl -fsSL https://x.example/i.sh | bash -s -- "{var}"\n',
                           unpinnable={})

    def test_an_explicit_version_flag_is_still_evidence(self):
        validate_agent_pin("x", "RUN curl -fsSL https://x.example/i.sh | bash -s -- --version 1.2.3\n",
                           unpinnable={})

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
        # BALANCED single quotes must not read as an unbalanced-quote truncation. Mutation testing
        # found the `% 2` on the single-quote count unasserted in the passing direction — every
        # existing quoted-spec test used double quotes, so a `'`-quoted pin would have been
        # reported as unverifiable: a false alarm on a correctly pinned line.
        "RUN mise use -g 'github:can1357/oh-my-pi@${OMP_VERSION}'\n",
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


class TestEverySpecOnALineIsExamined:
    """`mise use -g A B C` installs THREE tools. All three must be checked.

    Found by adversarial review of 659cea2, and it was not hypothetical: the shipped omp Dockerfile
    reads `mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}" bun && …`. The old pattern matched
    once per `mise` keyword, saw only the first spec, and passed — so the lint certified a file that
    installs `bun` at whatever version happened to be current. A gate whose blind spot is "the
    second argument" is worse than no gate, because the green result is believed.
    """

    def test_a_bare_second_spec_is_caught(self):
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("x", "RUN mise use -g node@20 python\n", unpinnable={})

    def test_a_bare_third_spec_is_caught(self):
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("x", "RUN mise use -g node@20 python@3.12 bun\n", unpinnable={})

    def test_the_error_names_the_offending_spec_not_the_first_one(self):
        with pytest.raises(PinValidationError) as exc:
            validate_agent_pin("x", "RUN mise use -g node@20 python\n", unpinnable={})
        assert "python" in str(exc.value)
        assert "node" not in str(exc.value)

    def test_all_specs_versioned_passes(self):
        validate_agent_pin("x", "RUN mise use -g node@20 python@3.12 bun@1.1.0\n", unpinnable={})

    def test_scanning_stops_at_a_shell_operator(self):
        """`&& mise install` and `&& omp …` are not specs of the preceding `mise use`."""
        body = 'RUN mise use -g "github:o/r@${VER}" && mise install && omp tiny-models download\n'
        validate_agent_pin("x", body, unpinnable={})

    def test_a_flag_after_the_specs_is_not_a_spec(self):
        validate_agent_pin("x", "RUN mise use -g node@20 --yes\n", unpinnable={})

    def test_a_second_mise_command_on_the_same_line_is_still_scanned(self):
        """`break` must end THIS command's arguments, not abandon the whole line.

        Mutation testing: swapping the `break` for a `return` survived, because no test put two
        `mise use` invocations on one line — and `A && B` on one RUN is the most ordinary shell
        there is. The second command's specs would simply never have been examined.
        """
        body = 'RUN mise use -g node@20 && mise use -g python\n'
        with pytest.raises(PinValidationError, match="python"):
            validate_agent_pin("x", body, unpinnable={})

    def test_a_spec_AFTER_a_flag_is_still_scanned(self):
        """Mutation testing: `continue` → `break` on a flag survived, because every test put its
        flag last. `mise use -g node@20 --yes python` would then have hidden `python`."""
        with pytest.raises(PinValidationError, match="python"):
            validate_agent_pin("x", "RUN mise use -g node@20 --yes python\n", unpinnable={})

    def test_the_same_unversioned_spec_twice_counts_once(self):
        """The count drives how many `unpinnable:` entries are owed, so double-counting a repeated
        acquisition would demand a second declaration for a single real concession. Mutation
        testing found the dedup key unasserted."""
        body = "RUN mise use -g bun\nRUN mise use -g bun\n"
        validate_agent_pin("x", body, unpinnable={"BUN_VERSION": "one concession, one entry"})

    @pytest.mark.parametrize("token", ["$(cat tools.txt)", "@scope/pkg", '"unterminated'])
    def test_a_token_this_cannot_read_fails_CLOSED(self, token):
        """An unreadable token is one whose version cannot be verified, so it must be reported.

        The first spelling skipped it, which is indistinguishable from having verified it. Caught
        by the changed-line coverage gap it left, and corrected to the posture `_IMMUTABLE_REF_RE`
        states for exactly this situation: an unrecognised shape fails closed rather than being
        guessed at.
        """
        with pytest.raises(PinValidationError, match="cannot verify"):
            validate_agent_pin("x", f"RUN mise use -g {token}\n", unpinnable={})

    def test_an_unreadable_token_does_not_stop_the_scan(self):
        """Mutation testing: `continue` → `break` after an unreadable token survived, because every
        such test made the bad token the only one. One unreadable spec must not blind the gate to
        everything after it — that would turn a fail-closed report into a fail-open one."""
        with pytest.raises(PinValidationError, match="2 unversioned"):
            validate_agent_pin("x", "RUN mise use -g @scope/pkg bun\n", unpinnable={"ONE": "reason"})

    def test_a_pipe_inside_a_quoted_spec_does_not_hide_what_follows(self):
        """Found by adversarial review round 2: the tail stops at any `|`, including one inside
        quotes, so `mise use -g "a|b" node` reported only the truncated `"a` and `node` vanished.

        Fail-closed matters more than precision here: `|` is not valid mise spec syntax, so the
        realistic case is a typo — but the miscount was in the UNSAFE direction (one declared
        `unpinnable:` entry would have excused the invisible `node` too).
        """
        found = _unversioned_acquisitions('RUN mise use -g "a|b" node\n')
        assert any("cannot verify" in f for f in found)
        assert len(found) >= 2, f"everything after the pipe must still be accounted for: {found}"

    def test_the_same_holds_for_SINGLE_quotes(self):
        """Mutation testing: every mutant of the single-quote half of the balance check survived,
        because the tests only ever used double quotes. One finding, two instances — the skill's
        'each finding is a class' rule, caught by the tool rather than by remembering it."""
        found = _unversioned_acquisitions("RUN mise use -g 'a|b' node\n")
        assert any("cannot verify" in f for f in found)
        assert len(found) >= 2, f"everything after the pipe must still be accounted for: {found}"

    def test_a_substitution_containing_spaces_over_reports_rather_than_under_reports(self):
        """`$(cat x)` is split on whitespace like any other token, so it is reported as more than
        one unreadable acquisition. Imprecise, and deliberately left that way: the error is in the
        fail-CLOSED direction (too many concessions demanded, never too few), and teaching this
        lint to parse shell quoting would be a shell parser — the thing `update.py`'s docstring
        already refuses to write.
        """
        found = _unversioned_acquisitions("RUN mise use -g $(cat x) bun\n")
        assert len(found) >= 2
        assert any("bun" in f for f in found)


class TestMultiStageBaseIsExempt:
    """`FROM harnessed-base:latest AS builder` — the standard multi-stage alias form.

    Found by adversarial review: the carve-out's `$` anchor rejected it, so a legitimate
    multi-stage agent Dockerfile would have been failed by a rule that exists to catch upstream
    drift. No agent uses this form yet, which is exactly why it would have been discovered by
    whoever first tried, as an undocumented quirk.
    """

    def test_the_alias_form_is_exempt(self):
        validate_agent_pin("x", "FROM harnessed-base:latest AS builder\nRUN true\n", unpinnable={})

    @pytest.mark.parametrize("line", [
        "FROM --platform=$TARGETPLATFORM harnessed-base:latest",
        "FROM --platform=linux/amd64 harnessed-base:latest AS builder",
    ])
    def test_a_platform_flag_does_not_break_the_exemption(self, line):
        """Raised in review of PR #335 — the same defect class as `AS builder`, which adversarial
        review had already found: a legitimate first-party line failed a rule that exists to catch
        upstream drift. Multi-arch builds make `--platform` likely. Finding the class once should
        have meant sweeping the diff for its other instances; it did not, so here is the sweep."""
        validate_agent_pin("x", line + "\nRUN true\n", unpinnable={})

    def test_a_platform_flag_does_not_smuggle_a_third_party_image(self):
        with pytest.raises(PinValidationError, match="floating"):
            validate_agent_pin("x", "FROM --platform=linux/amd64 ubuntu:latest\nRUN true\n",
                               unpinnable={})

    def test_the_alias_form_of_a_third_party_image_still_fails(self):
        with pytest.raises(PinValidationError, match="floating"):
            validate_agent_pin("x", "FROM ubuntu:latest AS builder\nRUN true\n", unpinnable={})


class TestACommentCannotSwallowTheNextLine:
    """A `#` line is a comment in Docker even when it ends with a backslash.

    Found by adversarial review. The continuation join ran BEFORE the comment filter, so a comment
    ending in `\\` absorbed the following physical line and the whole thing was then dropped as a
    comment — hiding a real acquisition Docker would go on to execute. Reached by ordinary editing:
    delete a RUN from a continuation block, leave the trailing backslash above it.
    """

    def test_a_comment_ending_in_a_backslash_does_not_hide_the_next_line(self):
        body = "# Install tools \\\nRUN mise use -g npm:@openai/codex\n"
        with pytest.raises(PinValidationError, match="no version"):
            validate_agent_pin("x", body, unpinnable={})

    def test_a_genuine_continuation_is_still_joined(self):
        """The fix must not break the joining that opencode's real body depends on."""
        body = 'RUN curl -fsSL https://opencode.ai/install | bash -s -- \\\n    --version "${V}"\n'
        validate_agent_pin("x", body, unpinnable={})


class TestUnpinnableSuppresses:
    def test_a_declaration_suppresses_the_error(self):
        body = "RUN curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
        validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "no version selector"})

    def test_one_declaration_does_not_excuse_a_SECOND_unversioned_acquisition(self):
        """Raised by adversarial review: the check was `if absent and not unpinnable`, so a single
        entry opened the gate for every other unversioned acquisition in the same file, silently.

        A per-acquisition MAPPING is not expressible — a genuinely unpinnable install references no
        ARG, so there is nothing in the Dockerfile to match a key against. What IS expressible is
        the count: each conceded acquisition costs one declared, reviewable entry. That keeps the
        exception explicit and diff-visible, which is the property AC-9 asks of it.
        """
        body = ("RUN curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
                "RUN mise use -g npm:@openai/codex\n")
        with pytest.raises(PinValidationError, match="2 unversioned"):
            validate_agent_pin("antigravity", body, unpinnable={"AGY_VERSION": "one reason"})

    def test_two_distinct_mise_specs_owe_two_declarations(self):
        """Mutation testing: blanking the dedup KEY survived, because every count test mixed one
        mise spec with one piped installer — so collapsing all mise keys into one still totalled
        two. Two unversioned specs of the SAME kind is the case that distinguishes them."""
        with pytest.raises(PinValidationError, match="2 unversioned"):
            validate_agent_pin("x", "RUN mise use -g bun deno\n", unpinnable={"ONE": "reason"})

    @pytest.mark.parametrize("body", [
        # separate RUN lines
        ("RUN curl -fsSL https://a.example/install.sh | bash\n"
         "RUN curl -fsSL https://b.example/install.sh | bash\n"),
        # ...and both on ONE line, which the per-line `search` could not reach. Raised in review of
        # PR #335: this is the same defect class as the multi-spec `mise` bug — one match per line,
        # so the second installer was invisible and an unrelated `unpinnable:` entry excused it.
        ("RUN curl -fsSL https://a.example/install.sh | bash && "
         "curl -fsSL https://b.example/install.sh | bash\n"),
    ])
    def test_two_distinct_piped_installers_owe_two_declarations(self, body):
        with pytest.raises(PinValidationError, match="2 unversioned"):
            validate_agent_pin("x", body, unpinnable={"ONE": "reason"})

    def test_version_evidence_does_not_leak_across_commands_on_one_line(self):
        """A `--version` belonging to the FIRST command must not excuse the second.

        The evidence check ran over the whole logical line, so any pinned installer anywhere on it
        vouched for every other. Same scoping error as the count itself.
        """
        body = ("RUN curl -fsSL https://a.example/i.sh | bash -s -- --version 1.2.3 && "
                "curl -fsSL https://b.example/i.sh | bash\n")
        with pytest.raises(PinValidationError, match=r"b\.example"):
            validate_agent_pin("x", body, unpinnable={})

    def test_two_declarations_cover_two_acquisitions(self):
        body = ("RUN curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
                "RUN mise use -g npm:@openai/codex\n")
        validate_agent_pin("antigravity", body,
                           unpinnable={"AGY_VERSION": "reason one", "CODEX_VERSION": "reason two"})

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

    def test_opencode_passes(self):
        validate_agent_pin("opencode", _body("opencode"), unpinnable={})

    def test_omp_fails_on_an_unpinned_bun_nobody_had_noticed(self):
        """A6's first real find, and the reason the multi-spec defect mattered.

        `Dockerfile.harnessed-omp:27` reads `mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}"
        bun && …`. The `bun` has no version, so it resolves to whatever is current at build time —
        the same class as bd harnessed-2o9. An earlier version of this test asserted omp PASSED,
        because the lint stopped after the first spec; adversarial review found both the lint bug
        and the live defect it was hiding.

        This asserts the CURRENT state. Pinning `bun` changes what the omp image ships, so it is a
        deliberate decision (which version?) rather than a drive-by fix — the same reason A2 and A3
        are deferred. When it is pinned, this test flips to asserting a pass.
        """
        with pytest.raises(PinValidationError, match="bun"):
            validate_agent_pin("omp", _body("omp"), unpinnable={})

    def test_every_agent_is_covered_by_this_file(self):
        """If someone adds a sixth agent, this file must be updated rather than silently not
        covering it — the failure mode A6 exists to prevent is an agent nobody looked at."""
        shipped = {p.name.removeprefix("Dockerfile.harnessed-")
                   for p in AGENT_DOCKERFILES.glob("Dockerfile.harnessed-*")}
        assert shipped == {"base", "antigravity", "claude", "codex", "omp", "opencode"}
