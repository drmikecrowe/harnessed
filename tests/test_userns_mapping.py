"""The userns mapping is pinned to the IMAGE's uid, not to the host's — bd harnessed-rv2.1.

`--userns=keep-id` maps the invoking host uid to the SAME NUMBER inside the container. Every
harnessed image bakes `USER harnessed` = uid 1000. So a bind-mounted host dir is writable by the
container process only when the host user *happens to be* uid 1000 — true on the dev box this was
written on, false on a GitHub `ubuntu-latest` runner, where it presents as

    error: service 'beads-server' exited at startup
    mkdir: cannot create directory '/data/dolt': Permission denied

`--userns=keep-id:uid=1000,gid=1000` maps the invoking user onto the image's uid instead, so the
container process IS the invoking host user whatever that user's host uid is. It is a no-op where
the host uid is already 1000, which is why it cannot regress a dev box.

These tests pin the property that survives refactors — *the emitted argument carries an explicit
uid mapping* — rather than the specific string, so a future change of the container uid updates one
constant and nothing here.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
from pathlib import Path

import pytest

from harnessed import launcher, paths
from harnessed.backend import LaunchSpec
from harnessed.schema import load_recipe
from support import patch_all

SRC = Path(__file__).resolve().parents[1] / "src" / "harnessed"

# A QUOTED `--userns=keep-id` with no `:uid=` — i.e. the unpinned form, as it appears when it is an
# argv element rather than prose describing one. Quotes are what separate "this line passes the bad
# argument to podman" from "this comment explains why the bad argument was wrong".
_BARE_KEEP_ID = re.compile(r"""['"]--userns=keep-id['"]""")


class TestTheConstant:
    def test_paths_pins_the_container_uid(self):
        """One place to change if the images ever stop baking uid 1000."""
        assert paths.CONTAINER_UID == 1000
        assert paths.CONTAINER_GID == 1000

    def test_the_userns_arg_carries_an_explicit_mapping(self):
        """The whole defect is the ABSENCE of `:uid=`, so that is what is asserted."""
        assert paths.USERNS_ARG.startswith("--userns=keep-id:")
        assert f"uid={paths.CONTAINER_UID}" in paths.USERNS_ARG
        assert f"gid={paths.CONTAINER_GID}" in paths.USERNS_ARG


class TestNoCallSiteRegresses:
    """A source-level sweep, in the idiom test_launch_parity.py already uses for this module.

    Unit-mocking `podman pod create` would assert the mock (test_backend_seam.py says so in as many
    words). What is checkable without a runtime is that no call site emits the unpinned form — and
    that is exactly the defect.
    """

    def test_no_bare_keep_id_remains_in_src(self):
        offenders = {
            f"{path.name}:{i}": line.strip()
            for path in sorted(SRC.rglob("*.py"))
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _BARE_KEEP_ID.search(line)
        }
        assert not offenders, (
            "these lines still emit the unpinned `--userns=keep-id`, which only works on a host "
            f"whose uid is {paths.CONTAINER_UID}: {offenders}"
        )

    def test_the_sweep_is_not_vacuous(self):
        """Guard the guard: deleting every userns argument would also make the sweep above pass."""
        users = {
            path.name for path in SRC.rglob("*.py")
            if path.name != "paths.py" and "paths.USERNS_ARG" in path.read_text(encoding="utf-8")
        }
        assert {"launcher.py", "volumes.py"} <= users, (
            "the modules that launch containers no longer reference paths.USERNS_ARG, so the sweep "
            f"above is passing vacuously; found only {sorted(users)}"
        )


class TestVolumeStepsCarryTheMapping:
    """Real argv, not a source scan: a volume written under any other mapping is unreadable by the
    agent (harnessed-8px.21.1), so every populate/install/seed step must match the pod."""

    def _argv(self, tmp_path, monkeypatch) -> list[list[str]]:
        d = tmp_path / "r"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text('name: r\ntools: ["npm:x@1"]\ninstall:\n  script: install.sh\n')
        (d / "install.sh").write_text("true\n")
        recipe = load_recipe(d, strict=True)
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(list(cmd)))
        monkeypatch.setattr(
            launcher.paths, "install_cache_dir",
            lambda name, key: tmp_path / "cache" / name / key,
        )
        launcher._run_container_installs(
            "podman", "s", "claude", "img", [recipe], "cfgvol", "toolsvol",
        )
        return calls

    def test_every_step_maps_the_invoking_user_onto_the_image_uid(self, tmp_path, monkeypatch):
        argvs = self._argv(tmp_path, monkeypatch)
        assert argvs, "the executor ran no steps — this test would pass vacuously"
        for cmd in argvs:
            userns = [a for a in cmd if a.startswith("--userns=")]
            assert userns == [paths.USERNS_ARG], f"step does not pin the mapping: {cmd}"


class TestPodMembersCarryNoUserns:
    """`--userns` is a POD-level property; podman rejects it on a member. The launcher strips it
    from the inherited mount args, and that strip must not be keyed to the old literal."""

    def test_strip_removes_every_form(self):
        args = [
            paths.USERNS_ARG,
            "--userns=keep-id",
            "--userns=keep-id:uid=1001,gid=1001",
            "-v", "a:b",
        ]
        kept = launcher._without_userns(args)
        assert not any(a.startswith("--userns") for a in kept)
        assert kept == ["-v", "a:b"]

    def test_the_member_wiring_really_strips_it(self, tmp_path):
        """The REAL `member_mounts`, not a source scan.

        This replaced an `inspect.getsource(...)` assertion that an adversarial reviewer defeated in
        one line: replacing the call with `list(self.mount_args)  # _without_userns(` left the
        substring in a comment, so the scan passed while `--userns` bled straight through onto the
        pod member. No other test caught that mutation either.

        `wire_mcp` needs no podman — it writes a config file and computes a list — so the earlier
        justification for leaving it to a structural guard was simply wrong.
        """
        backend = launcher.ContainerBackend(
            "podman", "inst", "pod", tmp_path / "prof", "img", tmp_path / "proj",
            [], [], None, stack_from_overlay=False, headless=True,
        )
        backend.mount_args = [paths.USERNS_ARG, "-v", "/host/a:/ctr/a", "-e", "FOO=1"]

        backend.wire_mcp(LaunchSpec(stack="s", harness="claude", project_path=tmp_path / "proj"))

        assert not any(a.startswith("--userns") for a in backend.member_mounts), (
            f"--userns leaked onto the pod member, which podman rejects: {backend.member_mounts}"
        )
        # ...and it stripped ONLY that: everything else the pod was given must still be delivered.
        assert "-v" in backend.member_mounts and "/host/a:/ctr/a" in backend.member_mounts
        assert "FOO=1" in backend.member_mounts


@pytest.mark.skipif(
    not os.environ.get("HARNESSED_PODMAN"),
    reason="set HARNESSED_PODMAN=1 for live podman tests",
)
class TestTheMappingActuallyFixesTheWrite:
    """The only layer that proves the FIX rather than the call sites (bd harnessed-rv2.1 repro).

    `--userns=keep-id:uid=1001,gid=1001` makes the invoking user appear as 1001 inside, which is
    exactly what plain `keep-id` does on a host whose user is uid 1001. The image's uid-1000
    process then owns nothing on the mount. The pinned form maps the invoking user onto 1000, so
    the same write succeeds.
    """

    IMAGE = "docker.io/library/alpine:3.20"

    def _write_probe(self, tmp_path: Path, userns: str) -> str:
        target = tmp_path / userns.replace("=", "_").replace(":", "_").replace(",", "_")
        target.mkdir()
        proc = subprocess.run(
            ["podman", "run", "--rm", userns, "--user", "1000:1000",
             "-v", f"{target}:/data:rw", "--entrypoint", "sh", self.IMAGE,
             "-c", "mkdir -p /data/dolt && echo WRITE_OK || echo WRITE_FAIL"],
            capture_output=True, text=True, timeout=180,
        )
        return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr.strip()

    def test_unpinned_mapping_cannot_write_when_the_host_uid_is_not_1000(self, tmp_path):
        assert self._write_probe(tmp_path, "--userns=keep-id:uid=1001,gid=1001") == "WRITE_FAIL"

    def test_pinned_mapping_can_write(self, tmp_path):
        assert self._write_probe(tmp_path, paths.USERNS_ARG) == "WRITE_OK"
