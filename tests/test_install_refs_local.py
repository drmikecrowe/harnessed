"""#532 — an `install.refs` entry may name a LOCAL FOLDER, used instead of the pin.

The case: someone developing skills in a repository outside harnessed wants a stack to install from
their working checkout, with no SHA bump per edit. `install.refs.<key>.local` names that folder. On
a host launch it reaches `install.sh` as `HARNESSED_LOCAL_<KEY>`. A container install gets the
folder bind-mounted read-only and the variable names the mount point, since the host path means
nothing there; the script copies from it. The pin stays mandatory.

What harnessed does NOT do is decide how the folder is used. The fetch lives in install.sh, as it
does for the pin, so the script reads `HARNESSED_LOCAL_<KEY>` and chooses (link, copy, build).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer

from harnessed import launcher
from harnessed.emit import install_env
from harnessed.schema import SchemaError, load_recipe
from support import patch_all

_SHA = "b930a7ed041abfea23f116062efc2603eefb130c"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _body(local: str | None) -> str:
    line = f"      local: {local}\n" if local is not None else ""
    return (
        "name: r\n"
        "install:\n"
        "  script: install.sh\n"
        "  refs:\n"
        "    old_coder:\n"
        "      repo: drmikecrowe/spec-evidence-aisdlc\n"
        f"      ref: {_SHA}\n"
        f"{line}"
    )


def _recipe(tmp_path, body: str, *, script: str = "true\n"):
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(body)
    (d / "install.sh").write_text(script)
    return load_recipe(d)


def _env(recipe, mode: str) -> dict[str, str]:
    return install_env(recipe, mode=mode, harness="claude", config_dir="/c", cache_dir="/x",
                       bin_dir="/b", home_shim="/h")


class TestParse:
    def test_an_absolute_local_folder_is_accepted(self, tmp_path):
        r = _recipe(tmp_path, _body("/home/dev/old-coder"))
        assert r.install is not None
        assert r.install.refs["old_coder"].local == "/home/dev/old-coder"

    def test_a_home_relative_folder_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", "/home/dev")
        r = _recipe(tmp_path, _body("~/old-coder"))
        assert r.install is not None
        assert r.install.refs["old_coder"].local == "/home/dev/old-coder"

    def test_a_relative_folder_is_rejected(self, tmp_path):
        """Relative to what? install.sh runs with cwd = the project, a build with cwd = the recipe.
        Either reading is wrong half the time, so neither is allowed."""
        with pytest.raises(SchemaError, match="local"):
            _recipe(tmp_path, _body("old-coder"))

    def test_an_empty_local_is_rejected(self, tmp_path):
        with pytest.raises(SchemaError, match="local"):
            _recipe(tmp_path, _body("''"))

    def test_the_pin_stays_mandatory_beside_a_local_folder(self, tmp_path):
        """The container build still installs from the pin, so a ref with only `local:` would
        leave the container half with nothing to fetch."""
        body = _body("/home/dev/old-coder").replace(f"      ref: {_SHA}\n", "")
        with pytest.raises(SchemaError, match="ref"):
            _recipe(tmp_path, body)

    def test_a_ref_without_local_parses_as_before(self, tmp_path):
        r = _recipe(tmp_path, _body(None))
        assert r.install is not None
        assert r.install.refs["old_coder"].local is None


class TestEnvContract:
    def test_host_mode_hands_the_folder_to_install_sh(self, tmp_path):
        env = _env(_recipe(tmp_path, _body("/home/dev/old-coder")), "host")
        assert env["HARNESSED_LOCAL_OLD_CODER"] == "/home/dev/old-coder"

    def test_container_mode_hands_the_mount_point_not_the_host_path(self, tmp_path):
        """The host path does not exist in the container; the mount point does."""
        env = _env(_recipe(tmp_path, _body("/home/dev/old-coder")), "container")
        assert env["HARNESSED_LOCAL_OLD_CODER"] == "/opt/harnessed/local/r/old_coder"
        assert env["HARNESSED_REF_OLD_CODER"] == _SHA

    def test_container_mode_without_local_yields_an_empty_variable(self, tmp_path):
        """No `local:` keeps the container on the pin, exactly as before."""
        env = _env(_recipe(tmp_path, _body(None)), "container")
        assert env["HARNESSED_LOCAL_OLD_CODER"] == ""

    def test_host_mode_still_passes_the_pin(self, tmp_path):
        """The script can report or fall back on the pin; the local folder does not erase it."""
        env = _env(_recipe(tmp_path, _body("/home/dev/old-coder")), "host")
        assert env["HARNESSED_REF_OLD_CODER"] == _SHA

    def test_a_ref_without_local_yields_an_empty_variable(self, tmp_path):
        """Every ref gets the key, so a script can test `[ -n "$HARNESSED_LOCAL_X" ]` under
        `set -u` without caring whether the recipe declared one."""
        env = _env(_recipe(tmp_path, _body(None)), "host")
        assert env["HARNESSED_LOCAL_OLD_CODER"] == ""

    def test_keys_are_identical_in_both_modes(self, tmp_path):
        r = _recipe(tmp_path, _body("/home/dev/old-coder"))
        assert set(_env(r, "host")) == set(_env(r, "container"))


def test_no_repo_catalog_recipe_declares_a_local_folder():
    """`catalog/` ships inside the wheel, so nothing host-local may live there (CLAUDE.md). A
    `local:` names one developer's folder; it belongs in the user overlay only."""
    catalog = Path(__file__).resolve().parents[1] / "catalog" / "recipes"
    offenders = []
    for manifest in sorted(catalog.glob("*/recipe.yaml")):
        r = load_recipe(manifest.parent)
        refs = r.install.refs if r.install else {}
        offenders += [f"{r.name}.{k}" for k, ref in refs.items() if ref.local is not None]
    assert not offenders, f"host-local `local:` in the repo catalog: {offenders}"


def _host_install(tmp_path, recipe, monkeypatch):
    patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, [recipe]))
    launcher._host_run_installs("s", tmp_path, harness="claude", home=tmp_path / "home")


class TestHostLaunch:
    def test_install_sh_sees_the_folder_on_a_host_launch(self, tmp_path, monkeypatch):
        """AC-1: the script receives the folder as its installation source."""
        local = tmp_path / "old-coder"
        local.mkdir()
        seen = tmp_path / "seen"
        r = _recipe(tmp_path, _body(str(local)),
                    script=f'printf %s "$HARNESSED_LOCAL_OLD_CODER" > {seen}\n')

        _host_install(tmp_path, r, monkeypatch)

        assert seen.read_text() == str(local)

    def test_a_missing_folder_fails_the_launch_naming_the_ref(self, tmp_path, monkeypatch, capsys):
        """A declared folder that is absent is an error, never a silent fall back to the pin: the
        developer would believe they were testing their edits while running the pinned commit."""
        ran = tmp_path / "ran"
        r = _recipe(tmp_path, _body(str(tmp_path / "gone")), script=f"touch {ran}\n")

        with pytest.raises(typer.Exit):
            _host_install(tmp_path, r, monkeypatch)

        err = _ANSI.sub("", capsys.readouterr().err)
        assert "old_coder" in err and str(tmp_path / "gone") in err
        assert not ran.exists(), "install.sh ran although its declared folder is missing"


def _container_argv(tmp_path, recipe, monkeypatch) -> list[str]:
    from harnessed import volumes

    captured: list[list[str]] = []
    monkeypatch.setattr(volumes, "_run", lambda cmd, **kw: captured.append(cmd))
    monkeypatch.setattr(volumes, "_say", lambda *a, **k: None)
    volumes._run_container_installs("podman", "s", "claude", "img", [recipe], "cfg", "tools")
    return captured[-1] if captured else []


class TestContainerInstall:
    def test_the_folder_is_mounted_read_only_where_the_variable_points(self, tmp_path, monkeypatch):
        """The suite runs no podman, so the argv is the claim: the mount and the env agree."""
        local = tmp_path / "old-coder"
        local.mkdir()
        argv = _container_argv(tmp_path, _recipe(tmp_path, _body(str(local))), monkeypatch)

        assert f"{local}:/opt/harnessed/local/r/old_coder:ro" in argv
        assert "HARNESSED_LOCAL_OLD_CODER=/opt/harnessed/local/r/old_coder" in argv

    def test_no_local_mounts_nothing(self, tmp_path, monkeypatch):
        argv = _container_argv(tmp_path, _recipe(tmp_path, _body(None)), monkeypatch)
        assert not any("/opt/harnessed/local/" in a for a in argv)

    def test_a_missing_folder_fails_the_install_naming_the_ref(self, tmp_path, monkeypatch, capsys):
        """Same rule as the host launch: never a silent fall back to the pin."""
        r = _recipe(tmp_path, _body(str(tmp_path / "gone")))

        with pytest.raises(typer.Exit):
            _container_argv(tmp_path, r, monkeypatch)

        err = _ANSI.sub("", capsys.readouterr().err)
        assert "old_coder" in err and str(tmp_path / "gone") in err


class TestContainerFingerprint:
    """A container install COPIES, so an edit in the folder must move the fingerprint or the next
    launch reports the stack unchanged and skips the reinstall."""

    def test_no_local_adds_nothing(self, tmp_path):
        from harnessed.volumes import _local_refs_digest

        assert _local_refs_digest([_recipe(tmp_path, _body(None))]) == ""

    def test_an_edit_in_the_folder_moves_the_digest(self, tmp_path):
        import os

        from harnessed.volumes import _local_refs_digest

        local = tmp_path / "old-coder"
        (local / "skills").mkdir(parents=True)
        f = local / "skills" / "SKILL.md"
        f.write_text("one")
        r = _recipe(tmp_path, _body(str(local)))
        before = _local_refs_digest([r])

        f.write_text("two!")
        os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 1_000_000_000))

        assert before and _local_refs_digest([r]) != before

    def test_git_internals_do_not_move_it(self, tmp_path):
        """A fetch or a `git status` touches .git without changing what installs."""
        from harnessed.volumes import _local_refs_digest

        local = tmp_path / "old-coder"
        (local / ".git").mkdir(parents=True)
        (local / "a.md").write_text("a")
        r = _recipe(tmp_path, _body(str(local)))
        before = _local_refs_digest([r])

        (local / ".git" / "index").write_text("changed")

        assert _local_refs_digest([r]) == before
