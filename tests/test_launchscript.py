"""`launchscript` — the `./claude-serena-host` file a launch leaves behind, and its git exclude entry.

Replaces `lastrun`/`--last`. That record was correct and invisible: nothing printed it, so "what did
I launch here" meant trawling shell history. The replacement is a readable, runnable file in the
project folder.

The behaviours pinned here are the ones that make writing an executable into somebody's repo safe:
it cannot be escaped by a hostile flag value, it cannot clobber a file we did not write, it cannot
kill a launch by failing, and it cannot grow the shared `info/exclude` without bound.
"""

import os
import shlex
import stat
import subprocess
import threading
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harnessed import aoe, launchscript

# A stub `harnessed` that writes its argv, one element per line, to $ARGV_OUT. The scripts under
# test are EXECUTED against this rather than parsed — a quoting bug that a regex would read straight
# past shows up here as a different number of argv elements.
_TYPED_PREFIX = "# as typed: "

# NUL-delimited, deliberately: execve cannot carry a NUL inside an argument, so it is the one
# separator no argv element can contain. A newline separator made a value that IS a newline
# indistinguishable from the delimiter, and that ambiguity reads as a code failure.
_STUB = """#!/bin/sh
: > "$ARGV_OUT"
for a in "$@"; do printf '%s\\0' "$a" >> "$ARGV_OUT"; done
"""


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def run_script(tmp_path):
    """Execute a written launcher script and return the argv the stub `harnessed` received."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "harnessed"
    stub.write_text(_STUB, encoding="utf-8")
    stub.chmod(0o755)
    argv_out = tmp_path / "argv.txt"

    def _run(script: Path, *extra: str) -> list[str]:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "ARGV_OUT": str(argv_out),
        }
        result = subprocess.run(
            [str(script), *extra], env=env, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"script failed: {result.stderr}"
        # Read as BYTES and split on NUL: no text-mode newline translation can touch the values,
        # which is the defect `_read_as_the_shell_does` exists for, reappearing in the harness that
        # checks for it.
        raw = argv_out.read_bytes()
        return [part.decode("utf-8") for part in raw.split(b"\x00")[:-1]]

    return _run


# Each payload tries to run `touch <canary>` by escaping the quoting around a flag VALUE. The canary
# is per-test, so a payload that fires is caught here rather than in a shared location.
_PAYLOADS = [
    "x'; touch {canary} #",
    '"; touch {canary}; "',
    "$(touch {canary})",
    "`touch {canary}`",
    "a b\tc",
    "'",
]


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)


class TestWriting:
    """S1 to S5 — a launch writes the script, and the name carries the stack."""

    def test_host_verb_writes_the_host_suffix(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        assert written == proj / "claude-serena-host"
        assert written.exists(), "expected the launcher script on disk"

    def test_container_verb_writes_the_container_suffix(self, proj):
        written = launchscript.write("container-run", "serena", "claude", proj)
        assert written == proj / "claude-serena-container"

    def test_harness_leads_the_name(self, proj):
        written = launchscript.write("host-run", "serena", "codex", proj)
        assert written == proj / "codex-serena-host", \
            "the harness leads the filename, then the stack, then the backend"

    def test_a_derived_stack_name_with_dots_survives(self, proj):
        """S4 — a dynamic stack name joins on `.` and may carry a digest suffix."""
        written = launchscript.write(
            "container-run", "default.serena.openbrain-a1b2c3d4", "claude", proj
        )
        assert written == proj / "claude-default.serena.openbrain-a1b2c3d4-container"

    def test_an_authored_stack_name_with_an_underscore_survives(self, proj):
        """S5 — `gsd-core_repowise` is a real authored stack name."""
        written = launchscript.write("host-run", "gsd-core_repowise", "claude", proj)
        assert written == proj / "claude-gsd-core_repowise-host"

    def test_the_script_is_executable(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        assert stat.S_IMODE(written.stat().st_mode) == 0o755

    def test_shebang_then_sentinel(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        lines = launchscript._read_as_the_shell_does(written).split("\n")
        assert lines[0] == "#!/bin/sh"
        assert lines[1] == launchscript.SENTINEL


class TestTwoStacksDoNotCollide:
    """S6 — the whole point of the rename.

    Before this change one project plus one harness plus one backend yielded ONE file, so a
    second stack silently overwrote the first and the aoe row replayed the newcomer under the
    old label.
    """

    def test_each_stack_gets_its_own_file(self, proj):
        first = launchscript.write("container-run", "alpha", "claude", proj)
        second = launchscript.write("container-run", "beta", "claude", proj)
        assert first != second, "two stacks must not share one launcher script"
        assert first is not None and second is not None
        assert first.exists() and second.exists(), "the first file must survive the second write"

    def test_each_file_launches_its_own_stack(self, proj):
        launchscript.write("container-run", "alpha", "claude", proj)
        launchscript.write("container-run", "beta", "claude", proj)
        alpha = launchscript._read_as_the_shell_does(proj / "claude-alpha-container")
        beta = launchscript._read_as_the_shell_does(proj / "claude-beta-container")
        assert "--stack alpha" in alpha and "--stack beta" not in alpha
        assert "--stack beta" in beta and "--stack alpha" not in beta


class TestTheExcludeSurfaceGrowsPerStack:
    """S28 — the one place the rename leaks outside aoe.

    `info/exclude` used to gain one line per harness and backend. It now gains one per STACK as
    well, in a file every worktree of the checkout shares. That is a deliberate consequence rather
    than an accident, and it is asserted so nobody "tidies" it later without meeting this note.
    """

    def _exclude(self, proj: Path) -> Path:
        return proj / ".git" / "info" / "exclude"

    def test_two_stacks_get_two_lines(self, proj):
        _git_init(proj)
        launchscript.write("container-run", "alpha", "claude", proj)
        launchscript.write("container-run", "beta", "claude", proj)
        lines = launchscript._read_as_the_shell_does(self._exclude(proj)).split("\n")
        assert "/claude-alpha-container" in lines
        assert "/claude-beta-container" in lines

    def test_relaunching_one_stack_still_adds_nothing(self, proj):
        _git_init(proj)
        for _ in range(4):
            launchscript.write("container-run", "alpha", "claude", proj)
        lines = launchscript._read_as_the_shell_does(self._exclude(proj)).split("\n")
        assert lines.count("/claude-alpha-container") == 1, "idempotence must survive the rename"


def test_no_harness_name_contains_a_name_separator():
    """The unstated invariant BOTH parsers rest on, made explicit.

    `parse_script_name` reads the harness from before the FIRST `-`, and `parse_legacy_script_name`
    reads the backend from after the LAST one. Each is correct only while no harness name contains a
    `-` itself. Add a harness called `claude-code` and both parsers start misreading every name that
    mentions it, silently: attribution would hand `harnessed rm` the wrong stack.

    Found by mutation. Swapping `rpartition` for `partition` in the legacy parser survives, and it
    survives BECAUSE of this invariant — with a dashed harness name the two would disagree. The
    mutant is equivalent today; this is the assumption that makes it so, so it is pinned here rather
    than described in a comment.

    `.` is included for the same reason one step removed: a derived stack name joins on `.`, so a
    harness carrying one would make the human-readable split ambiguous even where the parse is not.
    """
    for harness in launchscript.HARNESS_CONFIG_DIR:
        assert "-" not in harness, (
            f"harness {harness!r} contains '-', which breaks both launcher-name parsers. "
            "Either rename it or give the name grammar an explicit separator."
        )
        assert "." not in harness, f"harness {harness!r} contains '.', reserved by derived names"


class TestTheNameGrammar:
    """S10 to S14 — `parse_script_name` is the single reader of the name `script_name` builds."""

    def test_a_three_part_name_parses(self, proj):
        assert launchscript.parse_script_name("claude-serena-container") == (
            "claude", "serena", "container",
        )

    def test_a_stack_name_containing_dashes_is_recovered_whole(self, proj):
        """The reason the parse reads from BOTH ends rather than splitting on `-`."""
        assert launchscript.parse_script_name("claude-gsd-core_repowise-host") == (
            "claude", "gsd-core_repowise", "host",
        )

    def test_a_stack_name_containing_the_backend_word_is_not_confused(self, proj):
        assert launchscript.parse_script_name("claude-host-container") == (
            "claude", "host", "container",
        )

    def test_the_legacy_two_part_name_is_not_a_match(self, proj):
        """S11 — it names no stack, so nothing can attribute it to one."""
        assert launchscript.parse_script_name("claude-container") is None
        assert launchscript.parse_script_name("claude-host") is None

    def test_an_empty_stack_field_is_not_a_match(self, proj):
        """S14 — `claude--container` has the shape but names nothing."""
        assert launchscript.parse_script_name("claude--container") is None

    def test_an_unknown_harness_is_not_a_match(self, proj):
        """S12 — the narrowness that keeps a user's own script out."""
        assert launchscript.parse_script_name("notaharness-serena-container") is None

    def test_an_unknown_backend_is_not_a_match(self, proj):
        """S13 — `host` and `container` are the whole set."""
        assert launchscript.parse_script_name("claude-serena-attach") is None

    def test_the_legacy_parser_accepts_only_the_retired_shape(self, proj):
        """D1(a) — repair recognises what attribution must not."""
        assert launchscript.parse_legacy_script_name("claude-host") == ("claude", "host")
        assert launchscript.parse_legacy_script_name("notaharness-host") is None
        assert launchscript.parse_legacy_script_name("claude-attach") is None


# P1 and P2 — module level, matching the note above about hypothesis and class fixtures.
#
# The stack alphabet spans what a RESOLVED name can hold: an authored name is a directory name
# (alphanumerics, `-`, `_`, `.`), and a derived one is `[a-z0-9-]` components joined on `.` with an
# optional `-<hex>` digest. Names that would be rejected upstream are still generated on purpose:
# the round trip is a property of the STRING, and it must not depend on the name being sensible.
_STACK_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-._"


@given(
    harness=st.sampled_from(sorted(launchscript.HARNESS_CONFIG_DIR)),
    verb=st.sampled_from(sorted(launchscript._VERB_SUFFIX)),
    stack=st.text(alphabet=_STACK_CHARS, min_size=1),
)
@settings(max_examples=300, deadline=None)
def test_the_name_round_trips_for_any_stack(harness, verb, stack):
    """P1 — whatever the stack, the parse recovers all three fields exactly.

    This is the property the whole rename rests on. A stack name may contain `-` and `.`, so a
    parse that split on the separator would recover the wrong fields for `gsd-core_repowise` and
    for every derived name. Reading the harness from the front and the backend from the back is
    what makes the middle unambiguous, however many separators it holds.
    """
    name = launchscript.script_name(verb, stack, harness)
    assert launchscript.parse_script_name(name) == (
        harness, stack, launchscript._VERB_SUFFIX[verb],
    )


@given(
    harness=st.sampled_from(sorted(launchscript.HARNESS_CONFIG_DIR)),
    verb=st.sampled_from(sorted(launchscript._VERB_SUFFIX)),
    stack=st.text(alphabet=_STACK_CHARS, min_size=1),
)
@settings(max_examples=200, deadline=None)
def test_every_name_we_write_is_recognised_as_a_row(harness, verb, stack):
    """P2 — aoe must accept every name a launch can actually produce.

    Stated as a property rather than as examples because the failure it guards is asymmetric: a
    name we write but do not recognise makes `harnessed rm` skip a row it should remove, silently.
    """
    name = launchscript.script_name(verb, stack, harness)
    assert aoe._is_launcher_script([f"/p/{name}", "--"]) is True


@given(stack=st.text(min_size=1).filter(lambda s: "\x00" not in s))
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_a_stack_name_never_escapes_the_project(tmp_path_factory, stack):
    """P3 — containment, by the contract that ALREADY exists. No guard was added.

    The stack name reaches a filesystem path for the first time in this change, so containment
    needs stating. It does not need enforcing, and this asserts why:

      * `script_name` always prefixes `{harness}-`, so the result can never be absolute and the
        join can never be replaced;
      * a separator still targets something INSIDE the project folder;
      * a missing parent lands on `write`'s existing blanket `except OSError`, which returns None.

    If this ever fails, the answer is a guard and a spec revision, not a weaker property.
    """
    proj = tmp_path_factory.mktemp("p")
    written = launchscript.write("host-run", stack, "claude", proj)
    if written is not None:
        assert proj.resolve() in written.resolve().parents or written.parent == proj, \
            "a written launcher must live inside the project folder"


class TestParityWithCommandFor:
    """S2 — the exec line comes from `command_for`, never from re-quoting here."""

    @pytest.mark.parametrize("title", [
        "t",
        "before\rafter",      # the value that broke every reader of this file
        "nel\x85sep",         # splitlines() breaks here; /bin/sh does not
        "vt\x0bff\x0c",       # ditto
    ])
    def test_exec_argv_is_command_for_minus_the_separator(self, proj, title):
        kwargs = {"group": "librechat", "title": title, "no_strict_mcp": True}
        written = launchscript.write("host-run", "serena", "claude", proj, **kwargs)
        assert written is not None
        # The authority, read at test time rather than copied into this file.
        authority = shlex.split(aoe.command_for("host-run", "serena", "claude", proj, **kwargs))
        assert authority[-1] == "--", "guard: command_for is expected to end with the separator"

        # `_read_as_the_shell_does` + `split("\n")`, never `read_text().splitlines()`. This test
        # reads a shell script, so it has to use the shell's line grammar like every other reader —
        # with Python's, a flag value carrying \r or \x85 splits the exec line here and the
        # assertion fails on formatting instead of on the parity it guards.
        content = launchscript._read_as_the_shell_does(written)
        exec_line = next(ln for ln in content.split("\n") if ln.startswith("exec "))
        assert exec_line.endswith(' "$@"'), "S4: the script forwards its own argv"
        body = shlex.split(exec_line[len("exec "):-len(' "$@"')])
        assert body == authority[:-1]


class TestProvenanceComment:
    """S3 — the `# as typed:` line."""

    def test_records_the_argv_as_typed(self, proj):
        argv = ["harnessed", "host-run", "claude", "-r", "codebase-memory-mcp", "-r", "gh-issues"]
        written = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        assert written is not None
        assert "# as typed: harnessed host-run claude -r codebase-memory-mcp -r gh-issues" \
            in launchscript._read_as_the_shell_does(written).split("\n")

    def test_absent_when_no_argv_is_supplied(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        assert "# as typed:" not in written.read_text()

    @pytest.mark.parametrize("hostile", ["a\nexec touch /tmp/pwned", "a\rb", "a\x00b", "a\x1bb"])
    def test_control_characters_cannot_end_the_comment(self, proj, hostile):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", hostile]
        )
        assert written is not None
        typed = [ln for ln in launchscript._read_as_the_shell_does(written).split("\n")
                 if ln.startswith("# as typed:")]
        assert len(typed) == 1, "the comment must stay on exactly one line"
        assert all(c not in typed[0] for c in "\r\n\x00\x1b")

    def test_removing_the_comment_changes_nothing_that_runs(self, proj, run_script):
        argv = ["harnessed", "host-run", "claude", "-r", "x"]
        with_comment = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        assert with_comment is not None
        got_with = run_script(with_comment)
        # Same reason as the parity test: rebuilding the file through Python's line grammar would
        # rewrite any \r in the exec line as \n, so the assertion would be about a script this test
        # damaged rather than about the comment.
        content = launchscript._read_as_the_shell_does(with_comment)
        stripped = "\n".join(
            ln for ln in content.split("\n") if not ln.startswith("# as typed:")
        )
        with_comment.open("w", encoding="utf-8", newline="").write(stripped)
        assert run_script(with_comment) == got_with


class TestPassthrough:
    """S4 — the decision the whole design turns on: where the `--` lives."""

    def test_a_human_flag_reaches_harnessed(self, proj, run_script):
        script = launchscript.write("container-run", "serena", "claude", proj)
        argv = run_script(script, "--fresh")
        assert argv[-1] == "--fresh", "--fresh must reach harnessed, not the agent"
        assert "--" not in argv, "a bare separator here would send --fresh past harnessed's parser"

    def test_aoe_resume_flags_still_sail_past_harnessed(self, proj, run_script):
        script = launchscript.write("container-run", "serena", "claude", proj)
        # What an aoe row appends when it restarts a stopped session: the row's command is
        # `<script> --`, so the separator arrives as an argument to the script.
        argv = run_script(script, "--", "--resume", "abc123")
        assert argv[-3:] == ["--", "--resume", "abc123"]
        assert argv.index("--") == len(argv) - 3, "only ONE separator, and the agent's flags follow it"

    def test_no_extra_arguments_is_a_plain_launch(self, proj, run_script):
        script = launchscript.write("host-run", "serena", "claude", proj)
        argv = run_script(script)
        assert argv[0] == "host-run" and "--" not in argv


class TestHostileInput:
    """S5 — nothing a user can type may escape the generated script."""

    @pytest.mark.parametrize("template", _PAYLOADS)
    def test_a_hostile_title_survives_as_one_argv_element(self, proj, run_script, template, tmp_path):
        canary = tmp_path / "pwned"
        hostile = template.format(canary=canary)
        script = launchscript.write("host-run", "serena", "claude", proj, title=hostile)
        argv = run_script(script)
        assert hostile in argv, "the title must arrive byte-identical, as ONE element"
        assert not canary.exists(), "the payload executed — the value escaped its quoting"

    @pytest.mark.parametrize("template", _PAYLOADS)
    def test_a_hostile_group_survives_as_one_argv_element(self, proj, run_script, template, tmp_path):
        canary = tmp_path / "pwned"
        hostile = template.format(canary=canary)
        script = launchscript.write("host-run", "serena", "claude", proj, group=hostile)
        assert hostile in run_script(script)
        assert not canary.exists(), "the payload executed — the value escaped its quoting"

    def test_a_path_with_a_space_and_a_quote_survives(self, tmp_path, run_script):
        proj = tmp_path / "we ird's proj"
        proj.mkdir()
        script = launchscript.write("host-run", "serena", "claude", proj)
        assert str(proj.resolve()) in run_script(script)


class TestClobberRefusal:
    """S6 — never overwrite a file harnessed did not write."""

    def test_refuses_a_file_without_the_sentinel(self, proj):
        victim = proj / "claude-serena-host"
        victim.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert victim.read_text() == "#!/bin/sh\necho mine\n", "a foreign file must survive intact"

    def test_refuses_a_tracked_file_even_with_the_sentinel(self, proj):
        _git_init(proj)
        victim = proj / "claude-serena-host"
        victim.write_text(f"#!/bin/sh\n{launchscript.SENTINEL}\nexec true\n", encoding="utf-8")
        subprocess.run(["git", "add", "claude-serena-host"], cwd=proj, check=True, capture_output=True)
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert launchscript.SENTINEL in victim.read_text()

    def test_rewrites_its_own_file(self, proj):
        """A file carrying our sentinel is rewritten in place, never refused.

        This used to prove it by writing two DIFFERENT stacks and asserting one file came back
        twice. That mechanism died with the rename: two stacks are now two files, which is
        `TestTwoStacksDoNotCollide`'s job. The property being checked here was never about two
        stacks — it is that our own file is ours to overwrite — so the same stack twice states it
        directly, and a changed flag proves the second write actually landed.
        """
        first = launchscript.write("host-run", "serena", "claude", proj)
        second = launchscript.write("host-run", "serena", "claude", proj, no_strict_mcp=True)
        assert first is not None and second == first
        assert "--no-strict-mcp-config" in first.read_text(), \
            "the second write must have replaced the first file's contents"


class TestNeverFatal:
    """S7 — a write failure loses the shortcut, never the launch."""

    def test_a_read_only_folder_returns_none_instead_of_raising(self, proj):
        proj.chmod(0o500)
        try:
            assert launchscript.write("host-run", "serena", "claude", proj) is None
        finally:
            proj.chmod(0o700)

    def test_an_oserror_is_swallowed(self, proj, monkeypatch):
        def boom(*_a, **_k):
            raise OSError("disk on fire")

        monkeypatch.setattr(Path, "write_text", boom)
        assert launchscript.write("host-run", "serena", "claude", proj) is None


class TestExcludeEntry:
    """S8 — one line in the git common dir's info/exclude, written once."""

    def _exclude(self, repo: Path) -> Path:
        return repo / ".git" / "info" / "exclude"

    def _lines(self, exclude: Path) -> list[str]:
        """Git's line grammar, not Python's — the same rule the production readers follow.

        `read_text().splitlines()` would split a pattern on any of the eight characters Python
        treats as line breaks and git does not, so a project path carrying one would make these
        assertions pass or fail for a reason that has nothing to do with the behaviour."""
        return launchscript._read_as_the_shell_does(exclude).split("\n")

    def test_appends_the_root_anchored_path(self, proj):
        _git_init(proj)
        launchscript.write("host-run", "serena", "claude", proj)
        assert "/claude-serena-host" in self._lines(self._exclude(proj))

    def test_a_nested_project_is_anchored_from_the_repo_root(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        nested = repo / "sub" / "dir"
        nested.mkdir(parents=True)
        launchscript.write("host-run", "serena", "claude", nested)
        assert "/sub/dir/claude-serena-host" in self._lines(self._exclude(repo))

    def test_ten_launches_write_one_line(self, proj):
        _git_init(proj)
        for _ in range(10):
            launchscript.write("host-run", "serena", "claude", proj)
        assert self._lines(self._exclude(proj)).count("/claude-serena-host") == 1

    def test_existing_content_is_preserved(self, proj):
        _git_init(proj)
        exclude = self._exclude(proj)
        original = exclude.read_text()
        launchscript.write("host-run", "serena", "claude", proj)
        assert exclude.read_text().startswith(original)

    def test_a_file_without_a_trailing_newline_does_not_glue(self, proj):
        _git_init(proj)
        exclude = self._exclude(proj)
        exclude.write_text("*.log", encoding="utf-8")
        launchscript.write("host-run", "serena", "claude", proj)
        assert self._lines(exclude) == ["*.log", "/claude-serena-host", ""]

    def test_info_dir_is_created_when_absent(self, proj):
        _git_init(proj)
        info = proj / ".git" / "info"
        for child in info.iterdir():
            child.unlink()
        info.rmdir()
        launchscript.write("host-run", "serena", "claude", proj)
        assert "/claude-serena-host" in self._lines(self._exclude(proj))

    def test_a_non_git_folder_writes_no_exclude_and_still_writes_the_script(self, proj):
        assert launchscript.write("host-run", "serena", "claude", proj) is not None
        assert not (proj / ".git").exists()

    def test_the_container_script_gets_its_own_line(self, proj):
        _git_init(proj)
        launchscript.write("host-run", "serena", "claude", proj)
        launchscript.write("container-run", "serena", "claude", proj)
        lines = self._lines(self._exclude(proj))
        assert "/claude-serena-host" in lines and "/claude-serena-container" in lines


# Property tests are MODULE-LEVEL functions, not methods. pytest builds a fresh class instance
# per test, and hypothesis rejects a @given target reached through more than one of them
# (HealthCheck.differing_executors) — which surfaced only under mutmut, where the suite is
# re-entered many times in one process. Suppressing that check hides a real reproducibility
# problem; dropping the class removes it.

@given(st.lists(st.text(min_size=1), min_size=1, max_size=8))
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_the_comment_is_always_exactly_one_line(tmp_path_factory, argv):
    """Whatever argv holds, the `# as typed:` line cannot become two lines.

    This is the property the sanitizer exists for: one embedded newline turns a display-only
    comment into a second line of shell, and a second line of shell is executed.
    """
    proj = tmp_path_factory.mktemp("p")
    written = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
    assert written is not None
    # The guarded read, not `read_text().splitlines()` — this property draws ARBITRARY argv, so it
    # is the last place that should disagree with the shell about where a line ends.
    lines = launchscript._read_as_the_shell_does(written).split("\n")
    assert sum(ln.startswith(_TYPED_PREFIX) for ln in lines) == 1
    # 5, not 4: `split("\n")` keeps the trailing empty element that `splitlines()` drops. The file
    # ends with a newline, as a shell script should.
    assert len(lines) == 5, "shebang, sentinel, comment, exec, trailing empty — never more"
    assert lines[3].startswith("exec ") and lines[4] == ""

@given(st.integers(min_value=1, max_value=12))
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_repeated_writes_never_grow_the_exclude_file(tmp_path_factory, times):
    """N launches leave exactly one exclude line, for every N."""
    proj = tmp_path_factory.mktemp("p")
    _git_init(proj)
    for _ in range(times):
        launchscript.write("host-run", "serena", "claude", proj)
    lines = launchscript._read_as_the_shell_does(proj / ".git" / "info" / "exclude").split("\n")
    assert lines.count("/claude-serena-host") == 1

@given(st.text(min_size=1).filter(lambda t: "\x00" not in t),
       st.text(min_size=1).filter(lambda t: "\x00" not in t))
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_any_flag_value_survives_execution_intact(tmp_path_factory, run_script, group, title):
    """Whatever the flag values, the EXECUTED script hands them over byte-identical.

    Asserted by running the script rather than by reading it. A value may legitimately contain a
    newline — single quotes span lines in sh — so the exec statement is not always one physical
    line, and any text-scanning check would be asserting a property of the formatting rather
    than of the launch. NUL is excluded because execve cannot carry it in an argument at all.
    """
    proj = tmp_path_factory.mktemp("p")
    written = launchscript.write(
        "host-run", "serena", "claude", proj, group=group, title=title
    )
    assert written is not None
    argv = run_script(written)
    assert group in argv and title in argv


class TestCarriageReturnRegression:
    """A `\\r` in a flag value: the file is fine, the READER was not.

    Python's default text read is universal-newline mode, so a lone `\\r` inside a quoted value came
    back as `\\n` and split the exec line at a point `/bin/sh` never splits. Every reader of a
    generated script has to opt out of that (`_read_as_the_shell_does`). Found by
    `TestProperties::test_the_exec_line_always_reparses_to_the_same_argv`; pinned here by name so it
    does not depend on hypothesis drawing the same value again.
    """

    HOSTILE = "before\rafter"

    def test_the_exec_line_is_one_line_when_read_as_the_shell_reads(self, proj):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, title=self.HOSTILE
        )
        assert written is not None
        content = launchscript._read_as_the_shell_does(written)
        assert sum(ln.startswith("exec ") for ln in content.split("\n")) == 1
        assert len(content.split("\n")) == 4, "shebang, sentinel, exec, trailing empty"

    def test_the_default_python_read_would_have_split_it(self, proj):
        # The negative control for the fix: proves the guarded read is doing something, rather than
        # asserting a property that held anyway.
        written = launchscript.write(
            "host-run", "serena", "claude", proj, title=self.HOSTILE
        )
        assert written is not None
        naive = written.read_text(encoding="utf-8")
        assert len(naive.split("\n")) > 4, "if this stops holding, the regression is unfalsifiable"

    def test_the_shell_still_receives_it_as_one_argument(self, proj, run_script):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, title=self.HOSTILE
        )
        assert written is not None
        assert self.HOSTILE in run_script(written), "the value must survive execution intact"


class TestFailureBranches:
    """The error paths. Each one degrades to "no script, launch proceeds" — never to an exception.

    These are the branches that only fire when the environment misbehaves, so they are the ones a
    test suite silently leaves unexecuted and a refactor silently breaks.
    """

    @pytest.mark.parametrize("exc", [
        FileNotFoundError("git"),
        subprocess.TimeoutExpired("git", 5),
        OSError("fork failed"),
    ])
    def test_git_that_does_not_complete_reads_as_no_answer(self, proj, monkeypatch, exc):
        """`_git` returns None rather than propagating — every caller treats None as "not a repo".

        Exercised against `_git` directly. Routing it through `write` on a non-git folder proved
        nothing: `_ensure_excluded` returns before `_git` is ever called, so the assertion held
        whatever `_git` did. Changed-line coverage is what surfaced that.
        """
        def raise_it(*_a, **_k):
            raise exc

        monkeypatch.setattr(launchscript.subprocess, "run", raise_it)
        assert launchscript._git(proj, "rev-parse", "--show-toplevel") is None

    def test_a_launch_in_a_git_repo_survives_git_failing(self, proj, monkeypatch):
        _git_init(proj)
        monkeypatch.setattr(launchscript, "_git", lambda *_a, **_k: None)
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None and written.exists(), "the script is written regardless"
        assert "/claude-serena-host" not in (proj / ".git" / "info" / "exclude").read_text()

    def test_an_unreadable_existing_script_is_refused(self, proj, monkeypatch):
        (proj / "claude-serena-host").write_text("x", encoding="utf-8")

        def boom(*_a, **_k):
            raise OSError("unreadable")

        monkeypatch.setattr(launchscript, "_read_as_the_shell_does", boom)
        assert launchscript.write("host-run", "serena", "claude", proj) is None

    def test_a_failed_toplevel_lookup_writes_no_exclude_line(self, proj, monkeypatch):
        _git_init(proj)
        real = launchscript._git

        def fail_toplevel(path, *args):
            if "--show-toplevel" in args:
                return subprocess.CompletedProcess(["git"], 128, "", "boom")
            return real(path, *args)

        monkeypatch.setattr(launchscript, "_git", fail_toplevel)
        assert launchscript.write("host-run", "serena", "claude", proj) is not None
        assert "/claude-serena-host" not in (proj / ".git" / "info" / "exclude").read_text()

    def test_an_empty_toplevel_writes_no_exclude_line(self, proj, monkeypatch):
        _git_init(proj)
        real = launchscript._git

        def empty_toplevel(path, *args):
            if "--show-toplevel" in args:
                return subprocess.CompletedProcess(["git"], 0, "/\n", "")
            return real(path, *args)

        monkeypatch.setattr(launchscript, "_git", empty_toplevel)
        assert launchscript.write("host-run", "serena", "claude", proj) is not None
        assert "/claude-serena-host" not in (proj / ".git" / "info" / "exclude").read_text()

    def test_a_script_outside_the_toplevel_writes_no_exclude_line(self, proj, monkeypatch, tmp_path):
        # `relative_to` cannot express it, so there is no anchored pattern to write. Fails CLOSED:
        # a wrong pattern in a file every worktree shares is worse than no pattern.
        _git_init(proj)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        real = launchscript._git

        def other_toplevel(path, *args):
            if "--show-toplevel" in args:
                return subprocess.CompletedProcess(["git"], 0, f"{elsewhere}\n", "")
            return real(path, *args)

        monkeypatch.setattr(launchscript, "_git", other_toplevel)
        assert launchscript.write("host-run", "serena", "claude", proj) is not None
        assert "/claude-serena-host" not in (proj / ".git" / "info" / "exclude").read_text()

    def test_an_unwritable_exclude_file_is_survivable(self, proj):
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.chmod(0o400)
        try:
            # The script is written BEFORE the exclude entry is attempted, so the launch keeps its
            # shortcut even when the entry cannot be added.
            written = launchscript.write("host-run", "serena", "claude", proj)
            assert written is not None and written.exists()
            assert "/claude-serena-host" not in exclude.read_text(encoding="utf-8")
        finally:
            exclude.chmod(0o600)


class TestMutationGaps:
    """Assertions that mutation testing proved were missing.

    Every test here corresponds to a mutant that SURVIVED the first run: the line was executed and
    the suite passed anyway. Coverage cannot see this class of hole, which is the whole reason the
    mutation layer exists.
    """

    def test_a_tab_survives_into_the_provenance_comment(self, proj):
        # `_sanitize` keeps `\t` explicitly. Nothing asserted it, so deleting the clause was free.
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", "a\tb"]
        )
        assert written is not None
        typed = next(
            ln for ln in launchscript._read_as_the_shell_does(written).split("\n")
            if ln.startswith(_TYPED_PREFIX)
        )
        assert "\t" in typed

    def test_strict_mcp_is_the_default(self, proj):
        # `no_strict_mcp` defaulting to True instead of False changed the agent's MCP surface and
        # no test noticed.
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        assert "--no-strict-mcp-config" not in written.read_text(encoding="utf-8")

    def test_no_strict_mcp_reaches_the_script_when_asked_for(self, proj, run_script):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, no_strict_mcp=True
        )
        assert written is not None
        assert "--no-strict-mcp-config" in run_script(written)

    def test_an_untracked_sentinel_file_in_a_real_repo_is_rewritten(self, proj):
        # The tracked-file refusal has to be able to say NO as well as YES. Without
        # `--error-unmatch`, `git ls-files` exits 0 for an untracked path too, so every existing
        # file read as tracked — and every rewrite silently stopped happening.
        _git_init(proj)
        first = launchscript.write("host-run", "serena", "claude", proj)
        assert first is not None
        second = launchscript.write("host-run", "other-stack", "claude", proj)
        assert second is not None, "an untracked file we wrote must still be rewritable"
        assert "other-stack" in second.read_text(encoding="utf-8")

    def test_the_sentinel_is_only_honoured_on_line_two(self, proj):
        # Widening the window to three lines would accept a file whose second line is somebody
        # else's, which is not the format we write.
        victim = proj / "claude-serena-host"
        victim.write_text(
            f"#!/bin/sh\necho not ours\n{launchscript.SENTINEL}\n", encoding="utf-8"
        )
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert "echo not ours" in victim.read_text(encoding="utf-8")

    def test_the_read_limit_is_honoured(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None
        assert len(launchscript._read_as_the_shell_does(written, 5)) == 5
        assert len(launchscript._read_as_the_shell_does(written)) > 5

    def test_undecodable_bytes_do_not_raise(self, proj):
        # `errors="replace"` is the reason. A script somebody else wrote can hold any bytes, and
        # the sentinel check must reach a verdict rather than a UnicodeDecodeError.
        victim = proj / "claude-serena-host"
        victim.write_bytes(b"#!/bin/sh\n\xff\xfe not utf-8\n")
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert victim.read_bytes().startswith(b"#!/bin/sh\n\xff\xfe")

    def test_a_fresh_exclude_file_has_no_leading_blank_line(self, proj):
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.unlink()
        launchscript.write("host-run", "serena", "claude", proj)
        assert exclude.read_text(encoding="utf-8") == "/claude-serena-host\n"

    def test_appending_inserts_no_blank_line(self, proj):
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.write_text("*.log\n", encoding="utf-8")
        launchscript.write("host-run", "serena", "claude", proj)
        assert exclude.read_text(encoding="utf-8") == "*.log\n/claude-serena-host\n"

    def test_a_project_path_with_a_space_still_deduplicates(self, tmp_path):
        # The membership check splits on newlines. Splitting on WHITESPACE instead broke a pattern
        # containing a space into fragments, found nothing, and appended a fresh line every launch.
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        nested = repo / "a dir"
        nested.mkdir()
        for _ in range(3):
            launchscript.write("host-run", "serena", "claude", nested)
        lines = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").split("\n")
        assert lines.count("/a dir/claude-serena-host") == 1


class TestProvenanceCommentIsBounded:
    """The one place user argv reaches a file. argv is bounded only by ARG_MAX, so the line is not.

    Display-only and never executed, so this is not a security bound — it is a bound on how much
    harnessed will write into somebody's repository without being asked.
    """

    def test_a_huge_argv_is_capped_and_marked(self, proj):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", "x" * 50_000]
        )
        assert written is not None
        typed = next(
            ln for ln in launchscript._read_as_the_shell_does(written).split("\n")
            if ln.startswith(_TYPED_PREFIX)
        )
        assert len(typed) <= len(_TYPED_PREFIX) + launchscript._TYPED_LIMIT
        assert typed.endswith("(truncated)"), "a cut line must say it was cut"

    def test_a_comment_exactly_at_the_limit_is_not_truncated(self, proj):
        # The boundary. At exactly the cap there is nothing to cut, so cutting would both lose a
        # character and add a "(truncated)" marker that is not true.
        pad = launchscript._TYPED_LIMIT - len("harnessed ")
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", "x" * pad]
        )
        assert written is not None
        typed = next(
            ln for ln in launchscript._read_as_the_shell_does(written).split("\n")
            if ln.startswith(_TYPED_PREFIX)
        )
        assert len(typed) == len(_TYPED_PREFIX) + launchscript._TYPED_LIMIT
        assert "(truncated)" not in typed

    def test_an_ordinary_argv_is_untouched(self, proj):
        argv = ["harnessed", "host-run", "claude", "-r", "codebase-memory-mcp", "-r", "gh-issues"]
        written = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        assert written is not None
        assert "(truncated)" not in written.read_text(encoding="utf-8")

    def test_truncation_never_touches_what_runs(self, proj, run_script):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", "x" * 50_000]
        )
        assert written is not None
        assert run_script(written)[0] == "host-run", "the exec line is unaffected by the cap"


class TestTheSentinelReadIsBounded:
    """`write` inspects two lines of an existing file, so it must not read all of it.

    `except OSError` does not catch `MemoryError`, so an unbounded read here would let a large file
    in the way break the module's "every failure path returns None" contract and take the launch
    down with it. `aoe._replays_stack` bounded the same call; this site did not.
    """

    def test_a_file_larger_than_the_limit_is_not_read_whole(self, proj, monkeypatch):
        victim = proj / "claude-serena-host"
        victim.write_text("#!/bin/sh\n" + launchscript.SENTINEL + "\n" + "x" * 200_000, "utf-8")

        reads: list[object] = []
        real = launchscript._read_as_the_shell_does

        def spy(path, limit=None):
            reads.append(limit)
            return real(path, limit)

        monkeypatch.setattr(launchscript, "_read_as_the_shell_does", spy)
        launchscript.write("host-run", "serena", "claude", proj)
        assert reads == [launchscript._SENTINEL_READ_LIMIT], "the sentinel check must pass a limit"

    def test_a_giant_first_line_is_refused_rather_than_read(self, proj):
        # Truncation means the sentinel is not among the first two lines read, so the file is
        # treated as somebody else's and left alone — the safe direction.
        victim = proj / "claude-serena-host"
        original = "#" * (launchscript._SENTINEL_READ_LIMIT + 10) + "\n" + launchscript.SENTINEL + "\n"
        victim.write_text(original, encoding="utf-8")
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert victim.read_text(encoding="utf-8") == original

    def test_an_ordinary_file_we_wrote_is_still_rewritten(self, proj):
        # The bound must not break the normal case it sits in front of.
        first = launchscript.write("host-run", "serena", "claude", proj)
        assert first is not None
        second = launchscript.write("host-run", "other-stack", "claude", proj)
        assert second is not None and "other-stack" in second.read_text(encoding="utf-8")


class TestTheExcludeReadIsBounded:
    """`_ensure_excluded` reads `info/exclude` to check membership, so that read must be bounded too.

    Fifth instance of the same class: `MemoryError` is not an `OSError`, so an unbounded read here
    escapes both this function's guard and `write`'s, and the "never raises" contract is
    unconditional. The script read was bounded one round earlier and this one was missed.
    """

    def test_an_oversized_exclude_file_is_left_alone(self, proj):
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        original = "#" * (launchscript._EXCLUDE_READ_LIMIT + 1) + "\n"
        exclude.write_text(original, encoding="utf-8")
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written is not None and written.exists(), "the launch keeps its script"
        assert exclude.read_text(encoding="utf-8") == original, "the file must not be appended to"

    def test_skipping_beats_appending_blind(self, proj):
        # The reason the oversized case SKIPS rather than appends: membership cannot be checked, so
        # appending would add one line per launch to a file every worktree shares.
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.write_text("#" * (launchscript._EXCLUDE_READ_LIMIT + 1) + "\n", encoding="utf-8")
        for _ in range(3):
            launchscript.write("host-run", "serena", "claude", proj)
        assert exclude.read_text(encoding="utf-8").count("/claude-serena-host") == 0

    def test_a_file_just_under_the_cap_still_gets_its_entry(self, proj):
        # The bound must not break the case it sits in front of.
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.write_text("#" * (launchscript._EXCLUDE_READ_LIMIT - 100) + "\n", encoding="utf-8")
        launchscript.write("host-run", "serena", "claude", proj)
        assert "/claude-serena-host" in launchscript._read_as_the_shell_does(exclude).split("\n")

    def test_a_fifo_in_place_of_the_exclude_file_does_not_block(self, proj):
        # A FIFO passes `exists()`. Reading one blocks until a writer appears — which would hang the
        # launch, not merely lose the entry.
        _git_init(proj)
        exclude = proj / ".git" / "info" / "exclude"
        exclude.unlink()
        os.mkfifo(exclude)
        try:
            written = launchscript.write("host-run", "serena", "claude", proj)
            assert written is not None and written.exists()
        finally:
            exclude.unlink()

    def test_the_exclude_read_passes_a_limit(self, proj, monkeypatch):
        # Asserting the OUTCOME is not enough here: an unbounded read of an oversized file produces
        # the same verdict, so the "left alone" test above passes either way. The bound itself is
        # the property — it is what stops a `MemoryError` from escaping `except OSError`.
        _git_init(proj)
        limits: list[object] = []
        real = launchscript._read_as_the_shell_does

        def spy(path, limit=None):
            limits.append(limit)
            return real(path, limit)

        monkeypatch.setattr(launchscript, "_read_as_the_shell_does", spy)
        launchscript.write("host-run", "serena", "claude", proj)
        assert launchscript._EXCLUDE_READ_LIMIT + 1 in limits, "the exclude read must be bounded"
        assert None not in limits, "no read of a file we did not write may be unbounded"


class TestTheTargetPathIsCheckedForWhatItIs:
    """A FIFO named `claude-serena-host` in a project must not hang the launch.

    `exists()` is true for a FIFO, and opening one BLOCKS until a writer appears — so the sentinel
    check hung forever, and `except OSError` cannot catch a hang. Found by adversarial review round
    3; the seventh instance of this class and the fourth time the guard landed at one call site and
    not at its neighbour, this time seventy lines away in the same file.

    A TRAP WORTH RECORDING: the first attempt to reproduce this reported a clean `None` return,
    because `TimeoutError` subclasses `OSError` — a SIGALRM raised inside `write` was swallowed by
    `write`'s own handler. Timing is the honest instrument, which is why these tests bound the call
    with a real deadline rather than catching an exception.
    """

    def _write_within(self, proj: Path, seconds: float = 10.0):
        """Run `write` in a worker thread; fail the test if it has not returned in time.

        A thread, not a signal: signals only fire on the main thread and — as above — a
        signal-raised `TimeoutError` is indistinguishable from an ordinary `OSError` here.
        """
        result: list = []

        def run():
            result.append(launchscript.write("host-run", "serena", "claude", proj))

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(seconds)
        assert not worker.is_alive(), "write() blocked — a non-regular file hung the launch"
        return result[0]

    def test_a_fifo_at_the_target_does_not_hang_the_launch(self, proj):
        os.mkfifo(proj / "claude-serena-host")
        try:
            assert self._write_within(proj) is None
            assert (proj / "claude-serena-host").is_fifo(), "the FIFO must be left exactly as it was"
        finally:
            (proj / "claude-serena-host").unlink()

    def test_a_directory_at_the_target_is_refused(self, proj):
        (proj / "claude-serena-host").mkdir()
        assert self._write_within(proj) is None
        assert (proj / "claude-serena-host").is_dir()

    def test_a_regular_file_still_takes_the_normal_path(self, proj):
        # The guard must not break the case it sits in front of.
        first = launchscript.write("host-run", "serena", "claude", proj)
        assert first is not None and first.is_file()
        assert self._write_within(proj) is not None, "our own file is still rewritable"
