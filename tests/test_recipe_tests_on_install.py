"""A recipe's `tests/*.sh` RUN DURING INSTALL, in both modes — #329 / AC-6.

The defect this closes: `discover_recipe_tests` and `run_recipe_tests` were referenced only inside
`capability.py`. Neither install seam mentioned them, so a recipe's tests never ran during an
install at all — they ran only under the `harnessed-tools test` verb, against a headless podman
launch. A recipe could ship a test asserting its own install and nothing would ever execute it.

The contract, in the SPEC's terms:

  * for each recipe -- install, then THAT recipe's tests, then advance. Never install-all-then-
    test-all; `test_a_recipes_test_runs_before_the_next_recipe_installs` is what fails a two-pass
    implementation, and it is the reason that ordering is stated structurally rather than in prose.
  * a failing test FAILS THE INSTALL, with one truncated line saying why -- never a transcript.
  * a test runs in the SAME environment its install ran in, so there is no second env contract to
    drift.

Container execution is asserted at the argv level: the suite runs no podman (the same substitution
`test_toollock_wiring.py` makes, and for the same reason). The host seam gets real execution.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import capability, emit, launcher, paths
from harnessed.schema import load_recipe
from support import patch_all

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """rich styles its output; assert against the words, not the escape codes."""
    return _ANSI.sub("", text)


def _recipe(tmp_path, name="r", *, script_body: str = "true\n", tests: dict[str, str] | None = None,
            others: dict[str, str] | None = None):
    """A loadable recipe dir with an `install.script` and, optionally, a `tests/` dir."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(f"name: {name}\ninstall:\n  script: install.sh\n")
    (d / "install.sh").write_text(script_body)
    for fname, body in (tests or {}).items():
        tdir = d / "tests"
        tdir.mkdir(exist_ok=True)
        (tdir / fname).write_text(body)
    for fname, body in (others or {}).items():
        tdir = d / "tests"
        tdir.mkdir(exist_ok=True)
        (tdir / fname).write_text(body)
    return load_recipe(d, strict=True)


def _host_install(tmp_path, recipes, monkeypatch, home=None):
    """Drive the host seam exactly as `test_install_script.py` does."""
    home = home or tmp_path / "home"
    patch_all(monkeypatch, "load_stack_with_recipes", lambda root, s: (None, list(recipes)))
    launcher._host_run_installs("s", tmp_path, harness="claude", home=home)


# --- Host seam: the tests actually run --------------------------------------------------------


def test_a_passing_recipe_test_runs_and_the_install_completes(tmp_path, monkeypatch):
    """S-1. The whole point: a shipped test is executed, not merely discovered."""
    ran = tmp_path / "the-test-ran"
    r = _recipe(tmp_path, tests={"ok.sh": f"touch {ran}\nexit 0\n"})

    _host_install(tmp_path, [r], monkeypatch)

    assert ran.exists(), "the recipe's test script never executed during install"


def test_a_failing_recipe_test_fails_the_install(tmp_path, monkeypatch, capsys):
    """S-2. A recipe whose test fails did not install correctly, so the install does not succeed."""
    r = _recipe(tmp_path, tests={"bad.sh": "echo 'noise'\necho 'the real reason' >&2\nexit 3\n"})

    with pytest.raises(typer.Exit):
        _host_install(tmp_path, [r], monkeypatch)

    msg = _plain(capsys.readouterr().err)
    assert "r" in msg and "bad.sh" in msg
    assert "exit 3" in msg
    assert "the real reason" in msg


def test_a_recipe_with_no_tests_dir_runs_nothing_extra(tmp_path, monkeypatch):
    """S-3 / N-1. The overwhelmingly common case must cost nothing and behave as it always did.

    Asserts no process runs anything under a `tests/` dir — NOT that no process runs at all: the
    install script itself is a process, and it is not new.
    """
    spawned: list[list[str]] = []
    real = subprocess.run

    def _spy(cmd, *a, **k):
        spawned.append([str(part) for part in cmd] if isinstance(cmd, list) else [str(cmd)])
        return real(cmd, *a, **k)

    r = _recipe(tmp_path)
    monkeypatch.setattr(capability.subprocess, "run", _spy)

    _host_install(tmp_path, [r], monkeypatch)

    from_tests = [c for c in spawned if any("/tests/" in part for part in c)]
    assert from_tests == [], "a recipe with no tests/ dir still ran something from a tests/ dir"


def test_every_script_in_the_tests_dir_runs(tmp_path, monkeypatch):
    """S-4. Discovery is by convention -- every `*.sh`, not a declared list."""
    a, b = tmp_path / "a-ran", tmp_path / "b-ran"
    r = _recipe(tmp_path, tests={"a.sh": f"touch {a}\n", "b.sh": f"touch {b}\n"})

    _host_install(tmp_path, [r], monkeypatch)

    assert a.exists() and b.exists()


def test_only_sh_files_are_treated_as_tests(tmp_path, monkeypatch):
    """S-10. A README beside the scripts is not a test and must not be executed."""
    wrong = tmp_path / "readme-ran"
    r = _recipe(
        tmp_path,
        tests={"real.sh": "exit 0\n"},
        others={"readme.md": f"touch {wrong}\n"},
    )

    _host_install(tmp_path, [r], monkeypatch)

    assert not wrong.exists()


def test_the_test_runs_after_the_install_not_before(tmp_path, monkeypatch):
    """S-5. The test asserts what the install produced, so running it first fails for a bogus
    reason -- the exact confusion that makes people distrust the whole layer."""
    baked = tmp_path / "installed-artifact"
    r = _recipe(
        tmp_path,
        script_body=f"touch {baked}\n",
        tests={"needs-install.sh": f"test -f {baked}\n"},
    )

    _host_install(tmp_path, [r], monkeypatch)  # raises if the test ran first


def test_a_failed_install_never_runs_its_tests(tmp_path, monkeypatch):
    """S-9. One error, naming the real cause. A test failure on top of an install failure is noise
    that sends the reader after the wrong thing."""
    ran = tmp_path / "test-ran"
    r = _recipe(tmp_path, script_body="exit 9\n", tests={"t.sh": f"touch {ran}\n"})

    with pytest.raises(typer.Exit):
        _host_install(tmp_path, [r], monkeypatch)

    assert not ran.exists(), "tests ran for a recipe whose install had already failed"


def test_a_hanging_test_fails_the_install_rather_than_wedging_every_launch(tmp_path, monkeypatch):
    """S-7. Unbounded here would block every future launch of the stack, with no way back."""
    monkeypatch.setattr(capability, "DEFAULT_TEST_TIMEOUT", 1)
    r = _recipe(tmp_path, tests={"hang.sh": "sleep 30\n"})

    with pytest.raises(typer.Exit):
        _host_install(tmp_path, [r], monkeypatch)


def test_the_failure_message_cannot_leak_an_earlier_secret(tmp_path, monkeypatch, capsys):
    """S-8 / T-02-07. One truncated tail line, never the transcript."""
    r = _recipe(
        tmp_path,
        tests={"leaky.sh": "echo 'AKIAIOSFODNN7EXAMPLE tok'\necho 'assertion failed' >&2\nexit 1\n"},
    )

    with pytest.raises(typer.Exit):
        _host_install(tmp_path, [r], monkeypatch)

    msg = _plain(capsys.readouterr().err)
    assert "AKIAIOSFODNN7EXAMPLE" not in msg
    assert "assertion failed" in msg


# --- Host seam: the environment ----------------------------------------------------------------


def test_the_test_sees_the_same_environment_its_install_saw(tmp_path, monkeypatch):
    """S-6. One contract, not two. `emit.install_env` already guarantees identical KEYS across
    modes, so reusing it is what stops a host/container drift being possible at all."""
    dump = tmp_path / "env.txt"
    r = _recipe(tmp_path, tests={"env.sh": f"env > {dump}\nexit 0\n"})
    home = tmp_path / "home"

    _host_install(tmp_path, [r], monkeypatch, home=home)

    seen = dict(
        line.partition("=")[::2] for line in dump.read_text().splitlines() if "=" in line
    )
    assert seen["HARNESS"] == "claude"
    assert seen["HARNESSED_MODE"] == "host"
    assert seen["HARNESSED_CONFIG_DIR"] == str(home)
    assert seen["HARNESSED_RECIPE_DIR"] == str(r.root)
    assert seen["HARNESSED_HOME_SHIM"] == str(paths.host_home_shim(home))
    assert seen["HARNESSED_BIN_DIR"]


def test_a_binary_the_install_landed_is_on_the_tests_path(tmp_path, monkeypatch):
    """S-6. AC-6 is 'invoke the thing installed'. Host installs land executables in the STACK's bin
    dir, which is not on the operator's PATH -- inheriting PATH alone reports it missing and the
    failure reads as a broken recipe rather than a broken harness."""
    r = _recipe(
        tmp_path,
        script_body='mkdir -p "$HARNESSED_BIN_DIR" && '
                    'printf "#!/usr/bin/env bash\\nexit 0\\n" > "$HARNESSED_BIN_DIR/only-here" && '
                    'chmod +x "$HARNESSED_BIN_DIR/only-here"\n',
        tests={"find.sh": "command -v only-here\n"},
    )

    _host_install(tmp_path, [r], monkeypatch)  # raises if the binary is not visible


# --- Host seam: ordering across recipes ---------------------------------------------------------


def test_a_recipes_test_runs_before_the_next_recipe_installs(tmp_path, monkeypatch):
    """S-16. THE scenario that fails a two-pass (install-all-then-test-all) implementation, which
    would otherwise satisfy every single-recipe assertion in this file."""
    order = tmp_path / "order.txt"
    a = _recipe(tmp_path, "a", script_body=f"echo install-a >> {order}\n")
    b = _recipe(
        tmp_path, "b",
        script_body=f"echo install-b >> {order}\n",
        tests={"t.sh": f"echo test-b >> {order}\n"},
    )
    c = _recipe(tmp_path, "c", script_body=f"echo install-c >> {order}\n")

    _host_install(tmp_path, [a, b, c], monkeypatch)

    assert order.read_text().split() == ["install-a", "install-b", "test-b", "install-c"]


def test_a_failing_test_stops_the_remaining_recipes(tmp_path, monkeypatch):
    """S-11. Aborting means aborting -- a later recipe must not install onto a broken stack."""
    later = tmp_path / "second-installed"
    a = _recipe(tmp_path, "a", tests={"bad.sh": "exit 1\n"})
    b = _recipe(tmp_path, "b", script_body=f"touch {later}\n")

    with pytest.raises(typer.Exit):
        _host_install(tmp_path, [a, b], monkeypatch)

    assert not later.exists()


# --- Container seam: argv, because the suite runs no podman -------------------------------------


def _container_argv(tmp_path, recipes, monkeypatch, fail_tests: str | None = None):
    """Capture the podman command lines the container executor would run.

    `_run` is stubbed the way it really behaves under `check=True`: a non-zero exit RAISES
    `CalledProcessError` carrying the captured output, rather than returning a status. Stubbing it
    as a no-op would let a test assert against a contract the real function does not have.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        if fail_tests is not None and cmd[-1].endswith(fail_tests):
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="it failed")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    patch_all(monkeypatch, "_run", _fake_run)
    monkeypatch.setattr(
        launcher.paths, "install_cache_dir", lambda name, key: tmp_path / "cache" / name / key,
    )
    launcher._run_container_installs(
        "podman", "s", "claude", "img", list(recipes), "cfgvol", "toolsvol",
    )
    return calls


def test_the_container_runs_each_test_script_from_the_mounted_recipe(tmp_path, monkeypatch):
    """S-12. The recipe root is already bind-mounted read-only, so the tests are reachable with no
    new mount -- and the test step differs from the install step ONLY in the script path."""
    r = _recipe(tmp_path, tests={"t.sh": "exit 0\n"})

    calls = _container_argv(tmp_path, [r], monkeypatch)

    install = next(c for c in calls if c[-1].endswith("install.sh"))
    test = next(c for c in calls if c[-1].endswith("tests/t.sh"))
    assert test[-1] == f"{emit.CTR_RECIPE_DIR}/r/tests/t.sh"
    assert test[:-1] == install[:-1], "the test step must differ from the install step only in the script"


def test_the_container_test_runs_after_the_container_install(tmp_path, monkeypatch):
    """S-5, container side."""
    r = _recipe(tmp_path, tests={"t.sh": "exit 0\n"})

    joined = [" ".join(c) for c in _container_argv(tmp_path, [r], monkeypatch)]
    installs = [i for i, c in enumerate(joined) if c.endswith("install.sh")]
    tests = [i for i, c in enumerate(joined) if c.endswith("tests/t.sh")]

    assert installs and tests and installs[0] < tests[0]


def test_a_failing_container_test_fails_the_install(tmp_path, monkeypatch):
    """S-13."""
    r = _recipe(tmp_path, tests={"t.sh": "exit 1\n"})

    with pytest.raises(typer.Exit):
        _container_argv(tmp_path, [r], monkeypatch, fail_tests="tests/t.sh")


def test_a_container_recipe_with_no_tests_runs_no_extra_container(tmp_path, monkeypatch):
    """S-14 / N-1, container side."""
    r = _recipe(tmp_path)

    calls = _container_argv(tmp_path, [r], monkeypatch)

    assert not [c for c in calls if "/tests/" in c[-1]]


# --- The one catalog fix in scope ----------------------------------------------------------------


def test_cavemans_shipped_test_passes_under_a_host_install(tmp_path):
    """S-15. caveman read `${CONTAINER_HOME:-/home/harnessed}`, which does not exist host-side, so
    once a failing test aborts the install this script would break every host launch of every stack
    containing caveman. It moves to $HARNESSED_CONFIG_DIR, which `install_env` guarantees in BOTH
    modes. Its assertions are unchanged -- only the variable it reads to find the config dir."""
    script = CATALOG / "recipes" / "caveman" / "tests" / "hook-fires.sh"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(
        '{"hooks": {"SessionStart": [{"hooks": [{"command": "touch .caveman-notified"}]}]}}'
    )

    proc = subprocess.run(
        ["bash", str(script)],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "HARNESSED_CONFIG_DIR": str(config_dir)},
    )

    assert proc.returncode == 0, f"caveman's test fails host-side: {proc.stdout}{proc.stderr}"


def test_caveman_no_longer_depends_on_a_container_only_variable():
    """S-15, the property rather than the instance: CONTAINER_HOME names a container, and a host
    install has none. READING it is what made the script single-mode.

    Checked against CODE, not raw text. This is a USE assertion — "does the script read this
    variable?" — and a variable named in a comment is read by nothing, so a prose mention explaining
    why the dependency was removed must not fail the check. (The same distinction
    `test_install_script.py` draws: a VALUE must be absent from raw text because a comment copy
    drifts; a USE is checked against code.)
    """
    body = (CATALOG / "recipes" / "caveman" / "tests" / "hook-fires.sh").read_text()
    code = "\n".join(
        re.sub(r"\s#.*$", "", line)
        for line in body.splitlines()
        if not line.lstrip().startswith("#")
    )

    assert "CONTAINER_HOME" not in code
    assert "HARNESSED_CONFIG_DIR" in code
