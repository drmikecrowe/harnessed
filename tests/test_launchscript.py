"""`launchscript` — the `./claude-host` file a launch leaves behind, and its git exclude entry.

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
    """S1 — a launch writes the script."""

    def test_host_verb_writes_claude_host(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert written == proj / "claude-host"
        assert written.exists(), "expected the launcher script on disk"

    def test_container_verb_writes_claude_container(self, proj):
        written = launchscript.write("container-run", "serena", "claude", proj)
        assert written == proj / "claude-container"

    def test_harness_leads_the_name(self, proj):
        written = launchscript.write("host-run", "serena", "codex", proj)
        assert written == proj / "codex-host", "the harness is part of the filename, not just the verb"

    def test_the_script_is_executable(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert stat.S_IMODE(written.stat().st_mode) == 0o755

    def test_shebang_then_sentinel(self, proj):
        lines = launchscript.write("host-run", "serena", "claude", proj).read_text().splitlines()
        assert lines[0] == "#!/bin/sh"
        assert lines[1] == launchscript.SENTINEL


class TestParityWithCommandFor:
    """S2 — the exec line comes from `command_for`, never from re-quoting here."""

    def test_exec_argv_is_command_for_minus_the_separator(self, proj):
        kwargs = {"group": "librechat", "title": "t", "no_strict_mcp": True}
        written = launchscript.write("host-run", "serena", "claude", proj, **kwargs)
        # The authority, read at test time rather than copied into this file.
        authority = shlex.split(aoe.command_for("host-run", "serena", "claude", proj, **kwargs))
        assert authority[-1] == "--", "guard: command_for is expected to end with the separator"

        exec_line = next(
            ln for ln in written.read_text().splitlines() if ln.startswith("exec ")
        )
        assert exec_line.endswith(' "$@"'), "S4: the script forwards its own argv"
        body = shlex.split(exec_line[len("exec "):-len(' "$@"')])
        assert body == authority[:-1]


class TestProvenanceComment:
    """S3 — the `# as typed:` line."""

    def test_records_the_argv_as_typed(self, proj):
        argv = ["harnessed", "host-run", "claude", "-r", "codebase-memory-mcp", "-r", "gh-issues"]
        written = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        assert "# as typed: harnessed host-run claude -r codebase-memory-mcp -r gh-issues" \
            in written.read_text().splitlines()

    def test_absent_when_no_argv_is_supplied(self, proj):
        written = launchscript.write("host-run", "serena", "claude", proj)
        assert "# as typed:" not in written.read_text()

    @pytest.mark.parametrize("hostile", ["a\nexec touch /tmp/pwned", "a\rb", "a\x00b", "a\x1bb"])
    def test_control_characters_cannot_end_the_comment(self, proj, hostile):
        written = launchscript.write(
            "host-run", "serena", "claude", proj, argv=["harnessed", hostile]
        )
        typed = [ln for ln in written.read_text().splitlines() if ln.startswith("# as typed:")]
        assert len(typed) == 1, "the comment must stay on exactly one line"
        assert all(c not in typed[0] for c in "\r\n\x00\x1b")

    def test_removing_the_comment_changes_nothing_that_runs(self, proj, run_script):
        argv = ["harnessed", "host-run", "claude", "-r", "x"]
        with_comment = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        got_with = run_script(with_comment)
        stripped = "\n".join(
            ln for ln in with_comment.read_text().splitlines() if not ln.startswith("# as typed:")
        ) + "\n"
        with_comment.write_text(stripped, encoding="utf-8")
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
        victim = proj / "claude-host"
        victim.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert victim.read_text() == "#!/bin/sh\necho mine\n", "a foreign file must survive intact"

    def test_refuses_a_tracked_file_even_with_the_sentinel(self, proj):
        _git_init(proj)
        victim = proj / "claude-host"
        victim.write_text(f"#!/bin/sh\n{launchscript.SENTINEL}\nexec true\n", encoding="utf-8")
        subprocess.run(["git", "add", "claude-host"], cwd=proj, check=True, capture_output=True)
        assert launchscript.write("host-run", "serena", "claude", proj) is None
        assert launchscript.SENTINEL in victim.read_text()

    def test_rewrites_its_own_file(self, proj):
        first = launchscript.write("host-run", "serena", "claude", proj)
        second = launchscript.write("host-run", "other-stack", "claude", proj)
        assert second == first
        assert "other-stack" in first.read_text()


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

    def test_appends_the_root_anchored_path(self, proj):
        _git_init(proj)
        launchscript.write("host-run", "serena", "claude", proj)
        assert "/claude-host" in self._exclude(proj).read_text().splitlines()

    def test_a_nested_project_is_anchored_from_the_repo_root(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init(repo)
        nested = repo / "sub" / "dir"
        nested.mkdir(parents=True)
        launchscript.write("host-run", "serena", "claude", nested)
        assert "/sub/dir/claude-host" in self._exclude(repo).read_text().splitlines()

    def test_ten_launches_write_one_line(self, proj):
        _git_init(proj)
        for _ in range(10):
            launchscript.write("host-run", "serena", "claude", proj)
        lines = self._exclude(proj).read_text().splitlines()
        assert lines.count("/claude-host") == 1

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
        assert exclude.read_text().splitlines() == ["*.log", "/claude-host"]

    def test_info_dir_is_created_when_absent(self, proj):
        _git_init(proj)
        info = proj / ".git" / "info"
        for child in info.iterdir():
            child.unlink()
        info.rmdir()
        launchscript.write("host-run", "serena", "claude", proj)
        assert "/claude-host" in self._exclude(proj).read_text().splitlines()

    def test_a_non_git_folder_writes_no_exclude_and_still_writes_the_script(self, proj):
        assert launchscript.write("host-run", "serena", "claude", proj) is not None
        assert not (proj / ".git").exists()

    def test_the_container_script_gets_its_own_line(self, proj):
        _git_init(proj)
        launchscript.write("host-run", "serena", "claude", proj)
        launchscript.write("container-run", "serena", "claude", proj)
        lines = self._exclude(proj).read_text().splitlines()
        assert "/claude-host" in lines and "/claude-container" in lines


class TestProperties:
    """Invariants over inputs nobody thought to enumerate."""

    @given(st.lists(st.text(min_size=1), min_size=1, max_size=8))
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_the_comment_is_always_exactly_one_line(self, tmp_path_factory, argv):
        """Whatever argv holds, the `# as typed:` line cannot become two lines.

        This is the property the sanitizer exists for: one embedded newline turns a display-only
        comment into a second line of shell, and a second line of shell is executed.
        """
        proj = tmp_path_factory.mktemp("p")
        written = launchscript.write("host-run", "serena", "claude", proj, argv=argv)
        assert written is not None
        lines = written.read_text(encoding="utf-8").splitlines()
        assert sum(ln.startswith(_TYPED_PREFIX) for ln in lines) == 1
        assert len(lines) == 4, "shebang, sentinel, comment, exec — never more"
        assert lines[3].startswith("exec ")

    @given(st.integers(min_value=1, max_value=12))
    @settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_repeated_writes_never_grow_the_exclude_file(self, tmp_path_factory, times):
        """N launches leave exactly one exclude line, for every N."""
        proj = tmp_path_factory.mktemp("p")
        _git_init(proj)
        for _ in range(times):
            launchscript.write("host-run", "serena", "claude", proj)
        lines = (proj / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
        assert lines.count("/claude-host") == 1

    @given(st.text(min_size=1).filter(lambda t: "\x00" not in t),
           st.text(min_size=1).filter(lambda t: "\x00" not in t))
    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_any_flag_value_survives_execution_intact(self, tmp_path_factory, run_script,
                                                      group, title):
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
