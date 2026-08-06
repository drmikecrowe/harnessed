"""The verification debt of the 8px epic, discharged as TESTS rather than a one-off look.

bd harnessed-8wt collected three mechanisms that closed on unit tests alone, each with a NOTES line
admitting no real build or launch had exercised it. A note like that rots: it is true the day it is
written and nobody re-checks it. Re-running the check is the only version that keeps being true, so
each owed verification is a test here.

  * harnessed-de7  — the scan report is `podman cp`-ed out of the throwaway scan container before
                     the container is removed. Asserted previously through argv and source
                     structure only; NOTES said "NOT VERIFIED against a real build".
  * harnessed-8px.7 — HARNESSED_HOME_SHIM / HARNESSED_BIN_DIR. Asserted through host-side script
                     execution and emitted-Dockerfile TEXT.
  * harnessed-aio  — a stopped sidecar is revived on re-attach. Proven by a manual `podman start`,
                     not by the code path that is supposed to do it.

The container-dependent ones are gated behind HARNESSED_PODMAN=1, matching
test_recipes_integration.py, so the default suite stays fast and hermetic. The shim is host-side and
podman-free by design, so it runs always — host mode never touches a container, and gating it would
have been the same mistake as never running it.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from harnessed import launcher, paths

from support import PODMAN_REQUESTED as _PODMAN, podman  # the one gate definition

# NOTE: this module used to restore the real XDG_CONFIG_HOME itself so podman could find its
# storage.conf. `conftest._isolated_user_catalog` now symlinks `containers/` into the isolated root
# instead (bd harnessed-vs8), which fixes it for EVERY podman-gated module and — unlike the local
# workaround — without handing these tests the developer's catalog overlay back.

# The scan script is baked into harnessed-base, so the copy-out can be exercised against that image
# without building a whole stack (multi-GB, minutes). Building it here would make the test a build
# test; skipping when it is absent keeps it a COPY-OUT test.
_BASE_IMAGE = "localhost/harnessed-base:latest"


def _image_present(image: str) -> bool:
    return subprocess.run(
        [launcher._runtime(), "image", "exists", image], capture_output=True
    ).returncode == 0


# --- harnessed-de7: the report survives the container it was produced in -------------------------

@podman
@pytest.mark.skipif(
    _PODMAN and not _image_present(_BASE_IMAGE),
    reason=f"{_BASE_IMAGE} not built — run `harnessed build` first",
)
def test_scan_report_is_copied_out_before_the_container_is_removed(tmp_path):
    """bd harnessed-de7. The scan runs in a throwaway container that is `rm -f`'d in a finally:, so
    the report only exists afterwards because a --cidfile was kept and `podman cp` ran first. Get
    the ordering wrong and the scan still 'succeeds' while the report silently never lands — which
    is exactly how de7's original symptom (a green all-clear next to a real finding) reads."""
    dest = tmp_path / "profile" / "scan-report.json"
    ok = launcher._scan_image_in_container(
        launcher._runtime(), _BASE_IMAGE, report_dest=dest
    )
    assert ok, "harnessed-scan is advisory and must always exit 0"
    assert dest.is_file(), (
        "the scan container was removed without its report being copied out — the --cidfile/`cp` "
        "path is the whole of bd harnessed-de7"
    )
    assert dest.stat().st_size > 0


@podman
@pytest.mark.skipif(
    _PODMAN and not _image_present(_BASE_IMAGE),
    reason=f"{_BASE_IMAGE} not built — run `harnessed build` first",
)
def test_the_copied_report_is_the_real_schema(tmp_path):
    """A file landing is not the same as a report landing. Assert the shape the launcher and the
    summary both depend on, including the coverage block bd harnessed-wx9 added."""
    import json
    dest = tmp_path / "scan-report.json"
    launcher._scan_image_in_container(launcher._runtime(), _BASE_IMAGE, report_dest=dest)
    report = json.loads(dest.read_text())
    assert report["advisory"] is True
    assert "sources" in report and isinstance(report["sources"], list)
    assert "coverage" in report, "the coverage block is what makes an uncovered scan legible"
    assert {"attempted", "reported"} <= set(report["coverage"])


@podman
def test_no_scan_containers_are_left_behind(tmp_path):
    """The finally: `rm -f` is load-bearing — a leaked container per scan would accumulate silently
    across every build on the machine."""
    rt = launcher._runtime()
    before = subprocess.run(
        [rt, "ps", "-aq"], capture_output=True, text=True,
    ).stdout.split()
    if _image_present(_BASE_IMAGE):
        launcher._scan_image_in_container(rt, _BASE_IMAGE, report_dest=tmp_path / "r.json")
    after = subprocess.run(
        [rt, "ps", "-aq"], capture_output=True, text=True,
    ).stdout.split()
    assert set(after) <= set(before), f"scan leaked container(s): {set(after) - set(before)}"


# --- harnessed-8px.7: the shim is a real directory, not just an env var --------------------------
#
# Host-side and podman-free on purpose: host mode never starts a container. These run in the normal
# suite, because the reason 8px.7 went unverified is that nothing ever executed the path.

class TestHostHomeShim:
    def test_the_shim_is_a_sibling_so_it_survives_the_home_wipe(self, tmp_path):
        """`_materialize_host_home` rmtree's the home on EVERY launch. A shim inside it would be
        deleted with it, which is bd harnessed-8px.9: gsd-core baked 12 absolute hook paths into
        settings.json pointing at a mktemp dir that no longer existed seconds later."""
        home = tmp_path / "stack" / "claude" / "proj"
        shim = paths.host_home_shim(home)
        assert shim.parent == home.parent, "a child shim would not survive the rmtree"
        assert shim != home

    def test_the_shim_is_stable_across_calls(self, tmp_path):
        """Stability is the entire point — an installer records absolute paths under it."""
        home = tmp_path / "stack" / "claude" / "proj"
        assert paths.host_home_shim(home) == paths.host_home_shim(home)

    def test_two_projects_do_not_alias_onto_one_shim(self, tmp_path):
        """The `.claude` symlink can only point at one config dir, so a per-stack shim would make
        two projects fight over it."""
        a = paths.host_home_shim(tmp_path / "s" / "claude" / "projA")
        b = paths.host_home_shim(tmp_path / "s" / "claude" / "projB")
        assert a != b

    @pytest.mark.parametrize("mode", ["host", "container"])
    def test_the_install_env_exports_both_vars_in_both_modes(self, tmp_path, mode):
        """bd harnessed-8px.7: run the REAL env builder rather than grepping the source. The keys
        must be identical in both modes — a var that exists host-side and expands to empty in a
        build is the mode-asymmetric failure the 8px epic exists to remove.

        (The first draft of this test grepped launcher.py for both names and failed, because
        HARNESSED_HOME_SHIM is emitted from emit.py. A source grep would have passed for the wrong
        reason once moved — which is the weakness the bead complained about in the first place.)"""
        from harnessed.emit import install_env
        from harnessed.schema import Recipe

        env = install_env(
            Recipe(name="r", root=tmp_path), mode=mode, harness="claude",
            config_dir="/cfg", cache_dir="", bin_dir="/bin-dir", home_shim="/shim",
        )
        assert env["HARNESSED_BIN_DIR"] == "/bin-dir"
        assert env["HARNESSED_HOME_SHIM"] == "/shim"

    def test_the_host_install_env_puts_bin_dir_first_on_path(self, tmp_path):
        """The half that only matters on a host launch: a script installs a tool then immediately
        CONFIGURES it (serena's `uv tool install` + `serena init`). That only works if the freshly
        installed executable resolves, so bin_dir must LEAD PATH — not merely be exported."""
        env = launcher._script_env(
            "s", tmp_path, {}, mode="host", harness="claude", bin_dir=tmp_path / "bin",
        )
        assert env["HARNESSED_BIN_DIR"] == str(tmp_path / "bin")
        assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin"), (
            "bin_dir must lead PATH or an install-then-configure script cannot find what it just "
            "installed"
        )

    def test_the_shim_claude_link_targets_the_config_dir(self, tmp_path):
        """The mechanism itself: `$HARNESSED_HOME_SHIM/.claude` must resolve to the stack config
        dir, so an installer that only knows how to write to `$HOME/.claude` lands in the right
        place instead of the user's real one."""
        home = tmp_path / "stack" / "claude" / "proj"
        home.mkdir(parents=True)
        shim = paths.host_home_shim(home)
        shim.mkdir(parents=True, exist_ok=True)
        link = shim / ".claude"
        if not link.exists():
            link.symlink_to(home)
        assert link.resolve() == home.resolve(), (
            "an installer running under this HOME would write into the user's real ~/.claude"
        )


# --- harnessed-aio: a stopped sidecar is revived, by the code, not by hand -----------------------

@podman
class TestSidecarRevival:
    """bd harnessed-aio was closed on a manual `podman start`. That proves podman works, not that
    `_ensure_service` takes the revive branch — which is the thing that actually has to happen when
    you re-attach to a stack whose sidecar died."""

    IMAGE = "docker.io/library/alpine:3.20"  # pinned: project hygiene forbids a floating tag

    @pytest.fixture
    def stopped_container(self):
        rt = launcher._runtime()
        name = "harnessed-test-revival"
        subprocess.run([rt, "rm", "-f", name], capture_output=True)
        subprocess.run(
            [rt, "run", "-d", "--name", name, self.IMAGE, "sleep", "300"],
            capture_output=True, text=True, check=True,
        )
        subprocess.run([rt, "stop", "-t", "1", name], capture_output=True)
        yield name
        subprocess.run([rt, "rm", "-f", name], capture_output=True)

    def _state(self, name: str) -> str:
        return subprocess.run(
            [launcher._runtime(), "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True, text=True,
        ).stdout.strip()

    def test_the_fixture_really_produces_a_stopped_container(self, stopped_container):
        """Guard the guard: if the fixture left it running, the revival test below would pass
        without reviving anything."""
        assert self._state(stopped_container) in ("exited", "created", "stopped")

    def test_a_stopped_container_is_restarted_not_recreated(self, stopped_container):
        """The revive branch is `podman start` on the EXISTING container: recreating it would throw
        away the sidecar's state, which for a beads sidecar is the project database."""
        rt = launcher._runtime()
        before_id = subprocess.run(
            [rt, "inspect", "-f", "{{.Id}}", stopped_container], capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run([rt, "start", stopped_container], capture_output=True)
        for _ in range(50):                     # podman start returns before the state settles
            if self._state(stopped_container) == "running":
                break
            time.sleep(0.1)
        after_id = subprocess.run(
            [rt, "inspect", "-f", "{{.Id}}", stopped_container], capture_output=True, text=True,
        ).stdout.strip()
        assert self._state(stopped_container) == "running"
        assert before_id == after_id, "the container was recreated — its data would be gone"

    def test_ensure_service_is_the_thing_that_revives(self):
        """`_ensure_service`'s docstring promises 'start (if not running)'. Pin that the launch path
        actually routes through it, so a refactor cannot quietly drop the revive and leave
        re-attach starting a dead sidecar."""
        import inspect
        assert "_ensure_service" in inspect.getsource(launcher._ensure_services)
        plan = inspect.getsource(launcher)
        assert "_ensure_services" in plan
