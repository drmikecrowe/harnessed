"""The merged lockfile reaches BOTH install paths — Phase 2 step 2.

#341 landed the merge and wired it nowhere. This asserts it arrives where mise will read it, in
each mode, and that it is removed again when a stack no longer has one.

The container assertions read the argv rather than running podman: the suite builds no images, so
the strongest available claim is "the command we construct puts the lockfile in the config dir mise
reads". That claim is worth making precisely, because the two ways to get it wrong — wrong filename,
wrong directory — both fail SILENTLY, with mise installing unverified and exiting 0.
"""


import pytest

from harnessed.toollock import stack_lock_body, write_stack_lock

_LOCK = '''# @generated

[[tools.pulumi]]
version = "3.255.0"
backend = "pulumi"

[tools.pulumi."platforms.linux-x64"]
checksum = "sha256:abc"
url = "https://example/pulumi"
'''


class _Recipe:
    """The subset of a Recipe the install paths read — `tools` drives the specs, `install` is
    absent so no per-recipe install step runs and the argv under test stays the tools layer."""

    def __init__(self, name, root):
        self.name = name
        self.root = root
        self.tools = ["pulumi@3.255.0"]
        self.install = None


def _recipe(tmp_path, name="r", lock: str | None = _LOCK):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    if lock is not None:
        (root / "mise.lock").write_text(lock)
    return _Recipe(name, root)


class TestStackBody:
    def test_a_stack_with_no_lockfiles_produces_nothing(self, tmp_path):
        assert stack_lock_body([_recipe(tmp_path, "a", lock=None)]) == ""

    def test_only_the_recipes_that_ship_one_contribute(self, tmp_path):
        body = stack_lock_body([_recipe(tmp_path, "a"), _recipe(tmp_path, "b", lock=None)])
        assert "pulumi" in body


class TestWritingIntoTheConfigDir:
    def test_the_file_is_named_mise_lock(self, tmp_path):
        """NOT `config.lock`. mise ignores that spelling and installs unverified, exit 0 — the
        measured fact this whole feature turns on."""
        written = write_stack_lock(tmp_path / "cfg", _LOCK)
        assert written is not None and written.name == "mise.lock"
        assert written.read_text() == _LOCK

    def test_it_creates_the_config_dir_when_absent(self, tmp_path):
        assert write_stack_lock(tmp_path / "nope" / "cfg", _LOCK) is not None

    def test_an_empty_body_REMOVES_a_stale_lockfile(self, tmp_path):
        """The half that is easy to omit and unsafe to skip.

        A stack's tool set changes with its recipe list. A lockfile left from a previous launch
        would keep asserting checksums for a recipe this stack no longer has — verifying a tool set
        that is gone, and failing installs for reasons nobody can trace to a recipe still present.
        """
        cfg = tmp_path / "cfg"
        write_stack_lock(cfg, _LOCK)
        assert (cfg / "mise.lock").exists()
        assert write_stack_lock(cfg, "") is None
        assert not (cfg / "mise.lock").exists()

    def test_removing_when_none_exists_is_not_an_error(self, tmp_path):
        assert write_stack_lock(tmp_path, "") is None


class TestTheContainerCommand:
    """Reads the argv `_run_container_installs` builds. The suite runs no podman, so this is the
    strongest honest claim available: the command we construct writes the lockfile where mise
    reads it."""

    def _argv(self, monkeypatch, tmp_path, recipes):
        from harnessed import volumes

        captured: list[list[str]] = []
        monkeypatch.setattr(volumes, "_run", lambda cmd, **kw: captured.append(cmd))
        monkeypatch.setattr(volumes, "_say", lambda *a, **k: None)
        volumes._run_container_installs(
            "podman", "stack", "claude", "img", recipes, "cfgvol", "toolvol",
        )
        return captured[-1] if captured else []

    def test_the_lockfile_is_written_before_mise_install(self, monkeypatch, tmp_path):
        argv = self._argv(monkeypatch, tmp_path, [_recipe(tmp_path)])
        script = argv[-1]
        assert "mise.lock" in script
        assert script.index("mise.lock") < script.index("mise install")

    def test_it_lands_in_the_config_dir_mise_is_told_to_use(self, monkeypatch, tmp_path):
        argv = self._argv(monkeypatch, tmp_path, [_recipe(tmp_path)])
        assert any(a.startswith("MISE_CONFIG_DIR=") for a in argv), (
            "the config dir must be explicit — guessing mise's default risks writing the lockfile "
            "somewhere mise never reads, which fails silently"
        )
        assert '"$MISE_CONFIG_DIR/mise.lock"' in argv[-1]

    def test_the_body_travels_by_ENV_not_interpolated_into_the_shell(self, monkeypatch, tmp_path):
        """A multi-line TOML body spliced into an `sh -c` string is hand-quoting whose failure mode
        is arbitrary-code-shaped. `printf %s` on an env var quotes nothing."""
        argv = self._argv(monkeypatch, tmp_path, [_recipe(tmp_path)])
        assert any(a.startswith("HARNESSED_TOOL_LOCK=") for a in argv)
        assert "checksum" not in argv[-1], "the TOML body must not be inside the shell command"

    def test_a_stack_with_no_lockfiles_adds_no_lock_machinery(self, monkeypatch, tmp_path):
        argv = self._argv(monkeypatch, tmp_path, [_recipe(tmp_path, lock=None)])
        assert not any(a.startswith("HARNESSED_TOOL_LOCK=") for a in argv)
        assert "mise.lock" not in argv[-1]
        assert "mise install" in argv[-1], "the install itself must be unchanged"


_CONFLICT_A = _LOCK
_CONFLICT_B = _LOCK.replace("sha256:abc", "sha256:def")


class TestARecipeConflictIsReportedNotRaised:
    """Two recipes locking one spec differently is an AUTHORING mistake, not a crash.

    Raised in review of PR #342, and confirmed before fixing: `provision_tools` has no try/except
    and nothing above it catches `ToolLockError`, so the conflict reached the user as a Python
    traceback while every other failure in these paths prints one line and exits 1.

    The conflict is the one thing this whole mechanism exists to surface. Surfacing it as a
    stacktrace buries the message that names the two recipes.
    """

    def test_the_container_path_reports_and_exits(self, monkeypatch, tmp_path):
        import typer
        from harnessed import volumes

        monkeypatch.setattr(volumes, "_run", lambda *a, **k: None)
        monkeypatch.setattr(volumes, "_say", lambda *a, **k: None)
        errors: list[str] = []
        monkeypatch.setattr(volumes._err, "print", lambda m, *a, **k: errors.append(str(m)))
        recipes = [_recipe(tmp_path, "a", _CONFLICT_A), _recipe(tmp_path, "b", _CONFLICT_B)]
        with pytest.raises(typer.Exit) as exc_info:
            volumes._run_container_installs("podman", "s", "claude", "img", recipes, "c", "t")
        # `typer.Exit` alone is not enough: `typer.Exit(0)` is a SUCCESS exit, so the bare form
        # would pass if a conflict ended the launch cleanly — the exact inverse of the contract.
        assert exc_info.value.exit_code == 1
        assert any("a" in e and "b" in e for e in errors), "the message must name both recipes"

    def test_the_host_path_reports_and_exits(self, monkeypatch, tmp_path):
        import typer
        from harnessed import hostrun

        class _Ok:
            returncode = 0

        monkeypatch.setattr(hostrun.shutil, "which", lambda _n: "/usr/bin/mise")
        monkeypatch.setattr(hostrun.subprocess, "run", lambda *a, **k: _Ok())
        # The real signature is (tools_root, bin_dir, uv_tool_dir); a 1-tuple stub was enough
        # while only [0] was read, and `_stack_tool_path_prefix` now reads [1] too (#449).
        monkeypatch.setattr(
            hostrun, "_stack_tools_dirs",
            lambda _s: (tmp_path / "tools", tmp_path / "tools" / "bin",
                        tmp_path / "tools" / "uv-tools"),
        )
        monkeypatch.setattr(hostrun, "_apply_host_mise_env",
                            lambda env, _s: env.__setitem__(
                                "MISE_CONFIG_DIR", str(tmp_path / "tools" / "mise" / "config")))
        errors: list[str] = []
        monkeypatch.setattr(hostrun._err, "print", lambda m, *a, **k: errors.append(str(m)))
        recipes = [_recipe(tmp_path, "a", _CONFLICT_A), _recipe(tmp_path, "b", _CONFLICT_B)]
        with pytest.raises(typer.Exit) as exc_info:
            hostrun._host_install_tools("stack", recipes)
        assert exc_info.value.exit_code == 1, "a conflict must be a FAILING exit, not Exit(0)"
        assert any("a" in e and "b" in e for e in errors)


class TestTheHostPath:
    """The host half, exercised through the real function rather than only its helper.

    Container and host must agree on WHERE the lockfile goes, or one mode verifies and the other
    silently does not — and "silently" is the whole hazard, since mise ignores a misplaced lockfile
    and exits 0.
    """

    def _run_host(self, monkeypatch, tmp_path, recipes):
        from harnessed import hostrun

        calls: list[list[str]] = []

        class _Ok:
            # `stdout`/`stderr` are for the `mise bin-paths` call `_host_install_tools` ends with
            # (#449); the `mise use -g`/`mise install` calls read neither.
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(hostrun.shutil, "which", lambda _n: "/usr/bin/mise")
        monkeypatch.setattr(hostrun.subprocess, "run",
                            lambda cmd, **kw: (calls.append(cmd), _Ok())[1])
        # The real signature is (tools_root, bin_dir, uv_tool_dir); a 1-tuple stub was enough
        # while only [0] was read, and `_stack_tool_path_prefix` now reads [1] too (#449).
        monkeypatch.setattr(
            hostrun, "_stack_tools_dirs",
            lambda _s: (tmp_path / "tools", tmp_path / "tools" / "bin",
                        tmp_path / "tools" / "uv-tools"),
        )
        monkeypatch.setattr(hostrun, "_apply_host_mise_env",
                            lambda env, _s: env.__setitem__(
                                "MISE_CONFIG_DIR", str(tmp_path / "tools" / "mise" / "config")))
        hostrun._host_install_tools("stack", recipes)
        return calls

    def test_the_lockfile_is_written_where_mise_will_read_it(self, monkeypatch, tmp_path):
        self._run_host(monkeypatch, tmp_path, [_recipe(tmp_path)])
        assert (tmp_path / "tools" / "mise" / "config" / "mise.lock").read_text() != ""

    def test_a_stack_with_no_lockfiles_leaves_none_behind(self, monkeypatch, tmp_path):
        self._run_host(monkeypatch, tmp_path, [_recipe(tmp_path, lock=None)])
        assert not (tmp_path / "tools" / "mise" / "config" / "mise.lock").exists()

    def test_the_install_still_runs(self, monkeypatch, tmp_path):
        calls = self._run_host(monkeypatch, tmp_path, [_recipe(tmp_path)])
        assert ["mise", "install"] in calls


@pytest.mark.parametrize("has_lock", [True, False])
def test_the_helper_both_paths_share_agrees_on_the_filename(tmp_path, has_lock):
    """Host and container must agree on WHERE, or one mode verifies and the other does not.

    Asserted through the same helper both call sites use, against a config dir standing in for the
    stack's redirected `MISE_CONFIG_DIR`.
    """
    cfg = tmp_path / "mise" / "config"
    body = stack_lock_body([_recipe(tmp_path, "r", lock=_LOCK if has_lock else None)])
    written = write_stack_lock(cfg, body)
    assert (written == cfg / "mise.lock") if has_lock else (written is None)
