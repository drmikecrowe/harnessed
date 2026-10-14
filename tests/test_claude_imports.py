"""GH-600 — copy `~/.claude/CLAUDE.md` @-imports into a stack's rules, because ACP sessions drop them.

A headless ACP session loads CLAUDE.md files but expands none of their `@`-imports, and it loads no
symlinked rule. It does load a regular file in the stack's `rules/`, subdirectories included
(SPEC decisions, fact 10). So harnessed keeps a real copy of each imported file in a directory it
owns, `rules/harnessed-imports/`, when the user agrees, and rewrites it on every launch.

Scenario ids are the SPEC's (`spec-evidence/2026-10-14-GH-600/SPEC.md`).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from harnessed import claude_imports, launcher, paths
from support import patch_all

runner = CliRunner()

_PROMPT = (
    "Your ~/.claude/CLAUDE.md uses @import syntax that ACP sessions do not expand. "
    "Copy the imported files into this stack's rules? [y/n/i]"
)


class _Stop(Exception):
    """Raised by a stub to end a command at the step under test."""


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A temporary HOME, XDG_STATE_HOME and XDG_DATA_HOME, and helpers over them."""
    for var, sub in (("HOME", "home"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(var, str(tmp_path / sub))
    home = tmp_path / "home"
    (home / ".claude").mkdir()
    gortex = home / ".local" / "share" / "gortex" / "instructions"
    gortex.mkdir(parents=True)
    target = gortex / "active.md"
    target.write_text("# Gortex\n\nMARKER-a1\n")

    def claude_md(text: str) -> None:
        (home / ".claude" / "CLAUDE.md").write_text(text)

    return SimpleNamespace(home=home, target=target, claude_md=claude_md, tmp=tmp_path)


@pytest.fixture
def asked(monkeypatch):
    """A terminal that can prompt, answering from a queue; records every prompt text it showed."""
    shown: list[str] = []
    answers: list[str] = []

    def prompt(text, **_k):
        shown.append(text)
        if not answers:
            raise AssertionError(f"unexpected prompt: {text}")
        return answers.pop(0)

    monkeypatch.setattr(claude_imports, "_can_prompt", lambda: True)
    monkeypatch.setattr(claude_imports, "in_acp_mode", lambda: False)
    monkeypatch.setattr(claude_imports.typer, "prompt", prompt)
    return SimpleNamespace(shown=shown, answers=answers)


def _hash8(p: Path) -> str:
    return hashlib.sha256(str(p).encode()).hexdigest()[:8]


def _answer_file(stack: str) -> Path:
    return paths.xdg_state_home() / "harnessed" / "claude-imports" / stack


def _copies(stack: str) -> Path:
    return paths.xdg_data_home() / "harnessed" / "claude-imports" / stack


def _refreshed(stack: str) -> Path:
    d = claude_imports.refresh(stack)
    assert d is not None and d == _copies(stack)
    return d


# --------------------------------------------------------------------------------------------- S1
class TestS1WhoAsks:
    def test_s1_1_ask_shows_the_story_prompt_and_stores_the_answer(self, env, asked):
        env.claude_md("# me\n@~/.local/share/gortex/instructions/active.md\n")
        asked.answers.append("y")
        claude_imports.ask("s")
        assert asked.shown == [_PROMPT]
        assert _answer_file("s").read_text() == "y"

    def test_s1_1_an_answer_outside_y_n_i_is_asked_again(self, env, asked):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        asked.answers.extend(["maybe", "I"])
        claude_imports.ask("s")
        assert asked.shown == [_PROMPT, _PROMPT]
        assert _answer_file("s").read_text() == "i"

    @pytest.mark.parametrize("where", ["project", "parent"])
    def test_s1_2_an_import_outside_the_user_claude_md_is_never_asked_about(self, env, asked, where):
        proj = env.tmp / "proj"
        (proj / "sub").mkdir(parents=True)
        claude = proj / "CLAUDE.md" if where == "parent" else proj / "sub" / "CLAUDE.md"
        claude.write_text("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.ask("s")
        assert asked.shown == []
        assert not _answer_file("s").exists()

    @pytest.mark.parametrize("text", [None, "# just prose\nno imports here\n"])
    def test_s1_3_no_import_means_no_question_and_no_answer(self, env, asked, text):
        if text is not None:
            env.claude_md(text)
        claude_imports.ask("s")
        assert asked.shown == []
        assert not _answer_file("s").exists()

    @pytest.mark.parametrize("line", [
        "mail me at a@b.com", "see `@foo` for more", "  text @/abs/path.md", "a@b.com", "`@foo`",
    ])
    def test_s1_4_a_mid_line_at_sign_is_not_an_import(self, env, asked, line):
        env.claude_md(f"{line}\n")
        claude_imports.ask("s")
        assert asked.shown == []

    def test_s1_5_no_terminal_means_no_question(self, env, monkeypatch):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        monkeypatch.setattr(claude_imports, "_can_prompt", lambda: False)
        monkeypatch.setattr(claude_imports.typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
        claude_imports.ask("s")
        assert not _answer_file("s").exists()

    def test_s1_5_acp_mode_means_no_question_even_with_a_tty(self, env, monkeypatch):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        monkeypatch.setattr(claude_imports, "_can_prompt", lambda: True)
        monkeypatch.setattr(claude_imports, "in_acp_mode", lambda: True)
        monkeypatch.setattr(claude_imports.typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
        claude_imports.ask("s")
        assert not _answer_file("s").exists()

    def test_s1_5_the_exec_verbs_cannot_prompt(self, env, monkeypatch):
        """`host-exec` / `container-exec` set exec mode, and `_can_prompt` is the shared gate."""
        from harnessed import console

        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True, raising=False)
        console.set_exec_mode(True)
        try:
            monkeypatch.setattr(claude_imports.typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
            claude_imports.ask("s")
        finally:
            console.set_exec_mode(False)
        assert not _answer_file("s").exists()


class TestS1TheFourCommandsAsk:
    """Each terminal command calls the one ask, with its stack, for the claude harness."""

    @pytest.fixture
    def calls(self, monkeypatch):
        seen: list = []

        def _ask(stack, *, reask=False):
            seen.append((stack, reask))
            raise _Stop

        monkeypatch.setattr(launcher.claude_imports, "ask", _ask)
        return seen

    @pytest.fixture
    def build_stubs(self, monkeypatch):
        monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_ensure_local_catalog_links", lambda: None)
        monkeypatch.setattr(launcher, "_ensure_docs_wiki_clone", lambda: None)
        monkeypatch.setattr(launcher, "_write_global_launchers", lambda *a, **k: True)
        monkeypatch.setattr(launcher, "_offer_acp_adapter", lambda: None)
        patch_all(monkeypatch, "_runtime", lambda: "podman")

    def test_s1_1_build(self, calls, build_stubs):
        result = runner.invoke(launcher.app, ["build", "s", "claude"])
        assert isinstance(result.exception, _Stop), result.output
        assert calls == [("s", False)]

    def test_s6_2_build_reask_imports_passes_reask(self, calls, build_stubs):
        result = runner.invoke(launcher.app, ["build", "s", "claude", "--reask-imports"])
        assert isinstance(result.exception, _Stop), result.output
        assert calls == [("s", True)]

    def test_s1_1_build_for_another_harness_does_not_ask(self, calls, build_stubs):
        result = runner.invoke(launcher.app, ["build", "s", "omp"])
        assert result.exit_code == 0, result.output
        assert calls == []

    def test_s1_1_install(self, calls, monkeypatch, tmp_path):
        stack_dir = tmp_path / "stacks" / "s"
        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.yaml").write_text("name: s\nrecipes: []\nservices: []\n")
        monkeypatch.setattr(paths, "find_in_catalog", lambda kind, name: stack_dir)
        monkeypatch.setattr(launcher.launchscript, "write_globals", lambda *a, **k: [])
        monkeypatch.setattr(paths, "user_bin_dir", lambda: tmp_path / "bin")
        result = runner.invoke(launcher.app, ["install", "s", "claude"])
        assert isinstance(result.exception, _Stop), result.output
        assert calls == [("s", False)]

    def test_s1_1_host_run(self, calls, monkeypatch):
        monkeypatch.setattr(launcher, "_resolve_stack", lambda *a, **k: ("s", None))
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: pytest.fail("launched before asking"))
        result = runner.invoke(launcher.app, ["host-run", "claude", "--stack", "s"])
        assert isinstance(result.exception, _Stop), result.output
        assert calls == [("s", False)]

    def test_s1_5_host_exec_never_reaches_the_question(self, env, monkeypatch):
        """Adversary round 1: `_launch_host` sets exec mode, so `host_run` must not ask before it.
        A real terminal is on stdin here, and nobody is at it."""
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        from harnessed import console

        # CliRunner swaps sys.stdin, so stand in for a terminal: only exec mode can say no.
        monkeypatch.setattr(claude_imports, "_can_prompt", lambda: not console.in_exec_mode())
        monkeypatch.setattr(claude_imports.typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
        monkeypatch.setattr(launcher, "_resolve_stack", lambda *a, **k: ("s", None))
        launched: list = []
        monkeypatch.setattr(launcher, "_launch_host", lambda *a, **k: launched.append(k["exec_mode"]))
        result = runner.invoke(launcher.app, ["host-exec", "claude", "--stack", "s"])
        assert result.exit_code == 0, result.output
        assert launched == [True]
        assert not _answer_file("s").exists()

    def test_s1_1_container_run(self, calls, monkeypatch):
        monkeypatch.setattr(launcher, "_resolve_stack", lambda *a, **k: ("s", None))
        result = runner.invoke(launcher.app, ["container-run", "claude", "--stack", "s"])
        assert isinstance(result.exception, _Stop), result.output
        assert calls == [("s", False)]


# --------------------------------------------------------------------------------------------- S2
class TestS2CopiesAndTheMount:
    def test_s2_1_y_writes_a_regular_file_with_the_target_bytes(self, env):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        rules = env.tmp / "cfg" / "rules"
        claude_imports.sync_owned_dir("s", rules)
        copy = rules / "harnessed-imports" / f"active-{_hash8(env.target)}.md"
        assert copy.is_file() and not copy.is_symlink()
        assert copy.read_bytes() == env.target.read_bytes()

    def test_s2_2_the_mount_is_composed_after_the_config_volume(self, env, monkeypatch):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        seen = {}

        def _capture(*_a, **_k):
            seen["mounts"] = list(b.mount_args)
            raise _Stop

        cfg = ["-v", "cfg:/home/harnessed/.claude"]
        monkeypatch.setattr(launcher, "_build_mount_args", lambda *a, **k: list(cfg))
        monkeypatch.setattr(launcher, "_claude_config_seed_mount", _capture)
        b = _container_backend(env.tmp)
        with pytest.raises(_Stop):
            b.materialize_config(_spec("s", "claude", env.tmp))
        assert seen["mounts"] == [
            *cfg, "-v", f"{_copies('s')}:/home/harnessed/.claude/rules/harnessed-imports:ro",
        ]

    @pytest.mark.parametrize("answer", [None, "n", "i"])
    def test_s2_2_no_mount_without_a_yes(self, env, monkeypatch, answer):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        if answer:
            claude_imports.write_answer("s", answer)
        seen = {}

        def _capture(*_a, **_k):
            seen["mounts"] = list(b.mount_args)
            raise _Stop

        monkeypatch.setattr(launcher, "_build_mount_args", lambda *a, **k: ["-v", "cfg:/x"])
        monkeypatch.setattr(launcher, "_claude_config_seed_mount", _capture)
        b = _container_backend(env.tmp)
        with pytest.raises(_Stop):
            b.materialize_config(_spec("s", "claude", env.tmp))
        assert seen["mounts"] == ["-v", "cfg:/x"]

    def test_s2_2_another_harness_gets_no_mount(self, env, monkeypatch):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        seen = {}

        def _capture(*_a, **_k):
            seen["mounts"] = list(b.mount_args)
            raise _Stop

        monkeypatch.setattr(launcher, "_build_mount_args", lambda *a, **k: ["-v", "cfg:/x"])
        monkeypatch.setattr(launcher, "_claude_config_seed_mount", _capture)
        b = _container_backend(env.tmp)
        with pytest.raises(_Stop):
            b.materialize_config(_spec("s", "omp", env.tmp))
        assert seen["mounts"] == ["-v", "cfg:/x"]

    def test_s2_5_no_answer_creates_no_owned_dir(self, env):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        rules = env.tmp / "cfg" / "rules"
        claude_imports.sync_owned_dir("s", rules)
        assert not (rules / "harnessed-imports").exists()


def _container_backend(tmp: Path):
    b = launcher.ContainerBackend(
        "podman", "inst-d", "pod-d", tmp, "img", tmp, [], [],
        SimpleNamespace(isolated_auth=False), stack_from_overlay=False, headless=True,
    )
    b.config_volume, b.tools_volume = "cfg", "tools"
    return b


def _spec(stack: str, harness: str, project: Path):
    from harnessed.backend import LaunchSpec

    return LaunchSpec(stack=stack, harness=harness, project_path=project)


# --------------------------------------------------------------------------------------------- S3
class TestS3Refresh:
    def test_s3_3_a_refresh_keeps_the_copies_dir_itself(self, env):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        d = _refreshed("s")
        inode = d.stat().st_ino
        env.target.write_text("MARKER-new\n")
        assert claude_imports.refresh("s") == d
        assert d.stat().st_ino == inode
        assert (d / f"active-{_hash8(env.target)}.md").read_text() == "MARKER-new\n"

    def test_s3_4_container_materialize_refreshes_and_prunes_first(self, env, monkeypatch):
        other = env.home / "other.md"
        other.write_text("OTHER\n")
        env.claude_md(f"@~/.local/share/gortex/instructions/active.md\n@{other}\n")
        claude_imports.write_answer("s", "y")
        env.target.write_text("MARKER-old\n")
        claude_imports.refresh("s")
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        env.target.write_text("MARKER-new\n")
        seen = {}

        def _capture(*_a, **_k):
            seen["files"] = {p.name: p.read_text() for p in _copies("s").iterdir()}
            raise _Stop

        monkeypatch.setattr(launcher, "_build_mount_args", lambda *a, **k: [])
        monkeypatch.setattr(launcher, "_claude_config_seed_mount", _capture)
        b = _container_backend(env.tmp)
        with pytest.raises(_Stop):
            b.materialize_config(_spec("s", "claude", env.tmp))
        assert seen["files"] == {f"active-{_hash8(env.target)}.md": "MARKER-new\n"}


# --------------------------------------------------------------------------------------------- S4
_WARN = (
    "warning: ~/.claude/CLAUDE.md has @-imports this ACP session will not load. "
    "Run: harnessed build s claude --reask-imports"
)


class TestS4AcpWarning:
    @pytest.mark.parametrize("answer", [None, "n"])
    def test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only(self, env, capsys, answer):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        if answer:
            claude_imports.write_answer("s", answer)
        claude_imports.acp_warning("s")
        out, err = capsys.readouterr()
        assert out == ""
        assert err.strip() == _WARN

    @pytest.mark.parametrize("answer", ["y", "i"])
    def test_s4_3_y_or_i_is_silent(self, env, capsys, answer):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", answer)
        claude_imports.acp_warning("s")
        assert capsys.readouterr() == ("", "")

    @pytest.mark.parametrize("answer", [None, "n", "y", "i"])
    def test_s4_4_no_import_is_silent(self, env, capsys, answer):
        env.claude_md("# no imports\n")
        if answer:
            claude_imports.write_answer("s", answer)
        claude_imports.acp_warning("s")
        assert capsys.readouterr() == ("", "")


class TestS4HostAcpProcess:
    """The real `host-acp` verb, in its own process, so stdout and stderr are the real streams."""

    def test_s4_1_host_acp_warns_on_stderr_and_stdout_stays_json_rpc(self, tmp_path, monkeypatch):
        from test_host_acp import _Host, _pin, _rpc, _stdout_messages

        host = _Host(tmp_path, monkeypatch)
        host.build("claude")
        home = Path(host.env["HOME"])
        (home / ".claude").mkdir()
        (home / ".claude" / "CLAUDE.md").write_text(f"@{tmp_path / 'target.md'}\n")
        (tmp_path / "target.md").write_text("MARKER\n")
        proc = host.run("claude", path_prefix=host.adapter(_pin()),
                        msgs=[_rpc(1, "initialize", {"protocolVersion": 1})])
        assert proc.returncode == 0, proc.stderr.decode()
        assert "harnessed build acpspike claude --reask-imports" in proc.stderr.decode()
        assert b"reask-imports" not in proc.stdout
        _stdout_messages(proc)
        assert not (paths.host_home("acpspike", "claude") / "rules" / "harnessed-imports").exists()

    def test_s2_1_host_acp_with_yes_lands_the_copy_in_the_config_dir(self, tmp_path, monkeypatch):
        from test_host_acp import _Host, _pin, _rpc

        host = _Host(tmp_path, monkeypatch)
        host.build("claude")
        home = Path(host.env["HOME"])
        (home / ".claude").mkdir()
        target = tmp_path / "target.md"
        target.write_text("MARKER-a1\n")
        (home / ".claude" / "CLAUDE.md").write_text(f"@{target}\n")
        claude_imports.write_answer("acpspike", "y")
        proc = host.run("claude", path_prefix=host.adapter(_pin()),
                        msgs=[_rpc(1, "initialize", {"protocolVersion": 1})])
        assert proc.returncode == 0, proc.stderr.decode()
        assert b"reask-imports" not in proc.stderr
        owned = paths.host_home("acpspike", "claude") / "rules" / "harnessed-imports"
        assert {p.name: p.read_text() for p in owned.iterdir()} == {
            f"target-{_hash8(target)}.md": "MARKER-a1\n",
        }


# --------------------------------------------------------------------------------------------- S5
class TestS5StoredPerStack:
    @pytest.mark.parametrize("answer", ["y", "n", "i"])
    def test_s5_1_the_answer_is_stored_and_not_asked_again(self, env, asked, answer):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        asked.answers.append(answer)
        claude_imports.ask("s")
        assert _answer_file("s").read_text() == answer
        claude_imports.ask("s")
        assert asked.shown == [_PROMPT]

    def test_s5_2_another_stack_still_asks(self, env, asked):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        asked.answers.append("n")
        claude_imports.ask("t")
        assert asked.shown == [_PROMPT]
        assert _answer_file("t").read_text() == "n"
        assert _answer_file("s").read_text() == "y"

    @pytest.mark.parametrize("answer", ["n", "i"])
    def test_s5_3_n_or_i_copies_nothing(self, env, answer):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", answer)
        rules = env.tmp / "cfg" / "rules"
        claude_imports.sync_owned_dir("s", rules)
        assert claude_imports.refresh("s") is None
        assert not (rules / "harnessed-imports").exists()
        assert not _copies("s").exists() or not any(_copies("s").iterdir())

    @pytest.mark.parametrize("junk", ["", "yes", "Y\n", "x"])
    def test_s5_4_a_junk_answer_file_counts_as_no_answer(self, env, asked, junk):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        _answer_file("s").parent.mkdir(parents=True)
        _answer_file("s").write_text(junk)
        assert claude_imports.read_answer("s") is None
        asked.answers.append("y")
        claude_imports.ask("s")
        assert asked.shown == [_PROMPT]


# --------------------------------------------------------------------------------------------- S6
class TestS6DeletesOnlyItsOwn:
    def _yes_with_copy(self, env) -> Path:
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        rules = env.tmp / "cfg" / "rules"
        rules.mkdir(parents=True)
        (rules / "mine.md").write_text("MINE\n")
        claude_imports.sync_owned_dir("s", rules)
        assert any((rules / "harnessed-imports").iterdir())
        return rules

    def test_s6_1_a_removed_import_loses_its_copy(self, env):
        rules = self._yes_with_copy(env)
        env.claude_md("# the import line is gone\n")
        claude_imports.sync_owned_dir("s", rules)
        assert not list(_copies("s").iterdir())
        owned = rules / "harnessed-imports"
        assert not owned.exists() or not list(owned.iterdir())
        assert (rules / "mine.md").read_text() == "MINE\n"  # S6.4

    @pytest.mark.parametrize("answer", ["n", "i"])
    def test_s6_2_reask_answered_n_or_i_removes_the_copies(self, env, asked, answer):
        rules = self._yes_with_copy(env)
        asked.answers.append(answer)
        claude_imports.ask("s", reask=True)
        assert asked.shown == [_PROMPT]
        assert _answer_file("s").read_text() == answer
        claude_imports.sync_owned_dir("s", rules)
        assert not list(_copies("s").iterdir())
        owned = rules / "harnessed-imports"
        assert not owned.exists() or not list(owned.iterdir())
        assert (rules / "mine.md").read_text() == "MINE\n"  # S6.4

    def test_s6_3_reask_answered_y_deletes_nothing(self, env, asked):
        rules = self._yes_with_copy(env)
        before = sorted(p.name for p in (rules / "harnessed-imports").iterdir())
        asked.answers.append("y")
        claude_imports.ask("s", reask=True)
        claude_imports.sync_owned_dir("s", rules)
        assert sorted(p.name for p in (rules / "harnessed-imports").iterdir()) == before

    def test_s6_4_a_user_rule_beside_the_owned_dir_survives_every_sync(self, env):
        rules = self._yes_with_copy(env)
        (rules / "sub").mkdir()
        (rules / "sub" / "also-mine.md").write_text("ALSO\n")
        for text in ("# gone\n", "@~/.local/share/gortex/instructions/active.md\n"):
            env.claude_md(text)
            claude_imports.sync_owned_dir("s", rules)
        assert (rules / "mine.md").read_text() == "MINE\n"
        assert (rules / "sub" / "also-mine.md").read_text() == "ALSO\n"

    def test_s6_5_reask_with_no_terminal_clears_and_warns(self, env, monkeypatch, capsys):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        monkeypatch.setattr(claude_imports, "_can_prompt", lambda: False)
        claude_imports.ask("s", reask=True)
        out, err = capsys.readouterr()
        assert not _answer_file("s").exists()
        assert out == ""
        assert err.strip() == (
            "warning: --reask-imports needs a terminal; the stored answer for s is cleared. "
            "Run: harnessed build s claude --reask-imports"
        )

    def test_s6_5_build_reask_with_no_terminal_exits_0(self, env, monkeypatch):
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        monkeypatch.setattr(claude_imports, "_can_prompt", lambda: False)
        monkeypatch.setattr(launcher, "_build_stack", lambda *a, **k: None)
        monkeypatch.setattr(launcher, "_ensure_local_catalog_links", lambda: None)
        monkeypatch.setattr(launcher, "_ensure_docs_wiki_clone", lambda: None)
        monkeypatch.setattr(launcher, "_write_global_launchers", lambda *a, **k: True)
        monkeypatch.setattr(launcher, "_offer_acp_adapter", lambda: None)
        patch_all(monkeypatch, "_runtime", lambda: "podman")
        result = runner.invoke(launcher.app, ["build", "s", "claude", "--reask-imports"])
        assert result.exit_code == 0, result.output
        assert not _answer_file("s").exists()


# --------------------------------------------------------------------------------------------- S7
class TestS7MissingAndNested:
    def test_s7_1_a_missing_target_warns_and_the_rest_is_copied(self, env, capsys):
        missing = env.home / "nope" / "gone.md"
        env.claude_md(f"@{missing}\n@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        d = _refreshed("s")
        err = capsys.readouterr().err
        assert err.strip() == f"warning: @-import target not found, skipped: {missing}"
        assert [p.name for p in d.iterdir()] == [f"active-{_hash8(env.target)}.md"]

    def test_s7_1_a_sync_whose_only_target_is_missing_does_not_raise(self, env):
        env.claude_md(f"@{env.home / 'gone.md'}\n")
        claude_imports.write_answer("s", "y")
        rules = env.tmp / "cfg" / "rules"
        claude_imports.sync_owned_dir("s", rules)  # must not raise
        assert not any((rules / "harnessed-imports").iterdir())

    def test_s7_2_a_nested_import_is_copied_as_text_and_not_followed(self, env):
        inner = env.home / "inner.md"
        inner.write_text("INNER\n")
        env.target.write_text(f"OUTER\n@{inner}\n")
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        d = _refreshed("s")
        assert {p.name: p.read_text() for p in d.iterdir()} == {
            f"active-{_hash8(env.target)}.md": f"OUTER\n@{inner}\n",
        }

    def test_s7_3_same_name_different_dirs_get_distinct_copies_and_duplicates_one(self, env):
        a = env.home / "a" / "notes.md"
        b = env.home / "b" / "notes.md"
        for p, body in ((a, "A\n"), (b, "B\n")):
            p.parent.mkdir()
            p.write_text(body)
        env.claude_md(f"@{a}\n@{b}\n@{a}\n@~/a/notes.md\n")
        claude_imports.write_answer("s", "y")
        d = _refreshed("s")
        assert {p.name: p.read_text() for p in d.iterdir()} == {
            f"notes-{_hash8(a)}.md": "A\n",
            f"notes-{_hash8(b)}.md": "B\n",
        }

    def test_must_not_an_unwritable_copies_dir_warns_and_does_not_raise(self, env, capsys):
        """Adversary round 1: a launch never fails because of an import, writes included."""
        env.claude_md("@~/.local/share/gortex/instructions/active.md\n")
        claude_imports.write_answer("s", "y")
        _copies("s").parent.mkdir(parents=True)
        _copies("s").write_text("a file where the dir belongs")
        rules = env.tmp / "cfg" / "rules"
        claude_imports.sync_owned_dir("s", rules)
        assert claude_imports.mount_args("s", "/ctr") == []
        assert not (rules / "harnessed-imports").exists()
        err = capsys.readouterr().err
        assert "warning: could not update the @-import copies for s" in err

    @pytest.mark.parametrize("answer", [None, "n", "i"])
    def test_s7_4_without_a_yes_no_target_is_read_and_nothing_warns(self, env, capsys, answer):
        env.claude_md(f"@{env.home / 'gone.md'}\n")
        if answer:
            claude_imports.write_answer("s", answer)
        assert claude_imports.refresh("s") is None
        assert "not found" not in capsys.readouterr().err


class TestImportGrammar:
    """Decide 2 A: a line whose stripped text is `@<path>`; `~/` and relative resolve as Claude does."""

    def test_relative_paths_resolve_against_the_user_claude_dir(self, env):
        got = claude_imports.find_imports("@rules/x.md\n  @~/y.md  \n@/abs/z.md\n")
        assert got == [env.home / ".claude" / "rules" / "x.md", env.home / "y.md", Path("/abs/z.md")]

    def test_a_bare_at_sign_is_not_an_import(self, env):
        assert claude_imports.find_imports("@\n@ \n") == []

    def test_the_import_file_is_never_written(self, env, asked):
        text = "@~/.local/share/gortex/instructions/active.md\n"
        env.claude_md(text)
        before = env.target.read_bytes()
        asked.answers.append("y")
        claude_imports.ask("s")
        claude_imports.sync_owned_dir("s", env.tmp / "cfg" / "rules")
        assert (env.home / ".claude" / "CLAUDE.md").read_text() == text
        assert env.target.read_bytes() == before
