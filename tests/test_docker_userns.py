"""The `--userns` argument follows the container RUNTIME, not a hard-coded podman constant — #456.

`paths.USERNS_ARG` is podman's `--userns=keep-id:uid=1000,gid=1000`. Docker has no `keep-id` mode
and rejects it outright:

    docker: --userns: invalid USER mode
    ... returned non-zero exit status 125

which is where `harnessed` dies on a docker host, inside `provision_tools`, before a stack can
build. Three distinct sites assume podman, and only the first of them is loud:

  1. the seven call sites that EMIT `paths.USERNS_ARG`            -> exit 125
  2. `paths.pod_host_uid()`, which DERIVES the pod's host uid by PARSING that podman-only
     constant                                                     -> `guard_ownership` fails OPEN
  3. `launcher._without_userns`, which STRIPS the flag from the harness container unconditionally
     because a podman POD rejects it on a member -- docker has no pod, so there is nothing to
     inherit the mapping from and the strip is simply a loss                (silent)

These tests assert the PROPERTY the spec promises — *the argument, and the uid derived from it,
match the runtime in force* — rather than the spelling of any one string, so a future change of
the container uid or of docker's preferred flag updates one constant and nothing here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import typer

from harnessed import ctrquery, launcher, paths, persist, volumes
from harnessed.backend import LaunchSpec
from harnessed.hosthome import _HOST_STACK_FINGERPRINT
from harnessed.schema import load_recipe
from support import patch_all

# Captured at IMPORT, which happens at collection — before any fixture runs. `conftest` pins
# `paths.active_runtime` to podman for the whole suite (see `_pin_container_runtime`), so this is
# the only remaining handle on the real detector, and the two tests that must OBSERVE detection
# rather than assume it need it.
_REAL_ACTIVE_RUNTIME = paths.active_runtime
_REAL_DOCKER_IS_ROOTLESS = paths.docker_is_rootless

DOCKER = pytest.mark.skipif(
    not os.environ.get("HARNESSED_DOCKER"),
    reason="set HARNESSED_DOCKER=1 for live docker tests",
)


@pytest.fixture(autouse=True)
def _clear_runtime_caches():
    """Both detectors are process-cached. A cache that survives between tests would let the FIRST
    test in a module decide what every later one measures — the ambient-state trap this whole
    change exists to remove.

    Cleared through the captured originals, not through `paths.<name>`: `conftest`'s autouse
    `_pin_container_runtime` runs BEFORE this module-level one and has already replaced
    `paths.active_runtime` with a plain lambda, which has no `cache_clear` — reaching for the
    attribute here turns all 19 tests in this module into setup ERRORs.

    Setup only, deliberately. `monkeypatch`'s teardown is not ordered against this fixture's, so a
    post-yield clear can land while the attribute is still a test's lambda."""
    _REAL_ACTIVE_RUNTIME.cache_clear()
    _REAL_DOCKER_IS_ROOTLESS.cache_clear()


def _pin(monkeypatch, runtime: str, *, rootless: bool | None = False) -> None:
    """Pin the ambient runtime, so a test measures the branch it names rather than the binary that
    happens to be installed on the machine running the suite."""
    monkeypatch.setattr(paths, "active_runtime", lambda: runtime)
    monkeypatch.setattr(paths, "docker_is_rootless", lambda: rootless)


class TestTheEmittedArgument:
    """S1, S2, S3 — what goes on the command line, per runtime."""

    def test_podman_keeps_the_pinned_mapping(self):
        """S1. Byte-identical to what `main` emits today: this is the no-regression anchor."""
        assert paths.userns_args("podman") == ["--userns=keep-id:uid=1000,gid=1000"]
        assert paths.userns_args("podman") == [paths.USERNS_ARG]

    def test_docker_gets_host_and_never_keep_id(self):
        """S2. `host` rather than an omitted flag: it opts the container out of a daemon
        configured with `userns-remap`, where the default would map the image's uid 1000 into a
        subuid range and break every bind-mount write."""
        assert paths.userns_args("docker") == ["--userns=host"]
        assert not any("keep-id" in a for a in paths.userns_args("docker"))

    def test_an_unknown_runtime_is_refused_rather_than_guessed(self):
        """S3. Fail closed. Guessing `host` for an unrecognized runtime is how a wrong mapping
        reaches a real bind mount with nothing on the host saying why."""
        with pytest.raises(ValueError, match="nerdctl"):
            paths.userns_args("nerdctl")


class TestTheDerivedHostUid:
    """S4-S8 — the number `persist.guard_ownership` compares ownership against.

    Wrong here is worse than wrong in the emitted argument, because it is SILENT: the guard exists
    precisely to turn a mapping mistake into a named pre-launch error, and a guard that derives the
    wrong uid waves the bad launch through instead (bd harnessed-rv2.1, six red CI runs)."""

    # The invoking uid is ambient, and on a box where it happens to be 1000 the podman answer
    # (os.getuid()) and the rootful-docker answer (CONTAINER_UID) are THE SAME NUMBER. Both tests
    # below then pass no matter which branch runs, which is how a green suite ends up asserting
    # nothing. Pinning getuid to a number that is not 1000 makes the two answers distinguishable
    # by construction, so each test can only pass via its own branch — the degree of freedom is
    # removed rather than written down.
    _NOT_THE_IMAGE_UID = 4242

    def test_podman_resolves_to_the_invoking_user(self, monkeypatch):
        """S4 — unchanged behaviour, pinned so it stops depending on the machine's uid."""
        _pin(monkeypatch, "podman")
        monkeypatch.setattr(paths.os, "getuid", lambda: self._NOT_THE_IMAGE_UID)
        assert paths.pod_host_uid() == self._NOT_THE_IMAGE_UID
        assert paths.pod_host_uid() != paths.CONTAINER_UID  # the branches are distinguishable

    def test_rootful_docker_resolves_to_the_image_uid(self, monkeypatch):
        """S5. Rootful docker performs no id mapping, so the container's uid 1000 IS host uid 1000.
        DERIVED from that fact, not assumed — see SPEC Decide #4 and N3."""
        _pin(monkeypatch, "docker", rootless=False)
        monkeypatch.setattr(paths.os, "getuid", lambda: self._NOT_THE_IMAGE_UID)
        assert paths.pod_host_uid() == paths.CONTAINER_UID
        assert paths.pod_host_uid() != self._NOT_THE_IMAGE_UID

    def test_rootless_docker_is_unresolvable(self, monkeypatch):
        """S6. The image's uid is drawn from the host's subuid range and no argument says where."""
        _pin(monkeypatch, "docker", rootless=True)
        assert paths.pod_host_uid() is None

    def test_an_unreadable_daemon_is_unresolvable_not_assumed_rootful(self, monkeypatch):
        """S7. `docker info` failing is the case where guessing is most tempting and most wrong."""
        _pin(monkeypatch, "docker", rootless=None)
        assert paths.pod_host_uid() is None

    def test_rootless_docker_makes_the_ownership_guard_raise(self, monkeypatch, tmp_path):
        """S6 continued — the uid answer only matters through the guard it feeds.

        Asserting the message CONTENT, not merely that something raised. The SPEC promises this
        message "names the cause and a remediation", and a promise about a message that no test
        reads is a claim the gauntlet reports as verified while nothing checks it. Mutation found
        this: 32 mutants inside this message survived, because the only assertion was one
        substring."""
        _pin(monkeypatch, "docker", rootless=True)
        with pytest.raises(persist.PersistOwnershipError) as ei:
            persist.guard_ownership(tmp_path)
        msg = str(ei.value)
        assert str(tmp_path) in msg, "the message must name the path it refused"
        assert "rootless" in msg.lower(), "the message must name the CAUSE"
        assert str(paths.CONTAINER_UID) in msg, "the message must name the uid that is unmappable"
        assert "subuid" in msg.lower(), "the message must say WHY that uid cannot be resolved"
        # The remediation, which is the half a user can act on.
        assert "rootful" in msg.lower() and "podman" in msg.lower()

    def test_an_unreadable_daemon_names_the_probe_that_failed(self, monkeypatch, tmp_path):
        """S7 continued. "Could not tell" and "is rootless" are different situations with different
        fixes, so they must not share one message."""
        _pin(monkeypatch, "docker", rootless=None)
        with pytest.raises(persist.PersistOwnershipError) as ei:
            persist.guard_ownership(tmp_path)
        msg = str(ei.value)
        assert "docker info" in msg, "the message must name the probe that could not be read"
        assert "rootful" in msg.lower() and "rootless" in msg.lower()

    def test_the_rootless_probe_runs_at_most_once_per_process(self, monkeypatch):
        """S8. `guard_ownership` is called once per persist entry; an uncached probe would shell
        out to `docker info` once per entry on every launch."""
        monkeypatch.setattr(paths, "active_runtime", lambda: "docker")
        calls: list[list[str]] = []

        def _fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="name=seccomp\n", stderr="")

        monkeypatch.setattr(paths.subprocess, "run", _fake_run)
        for _ in range(3):
            paths.pod_host_uid()
        assert len(calls) == 1, f"docker info ran {len(calls)} times, expected 1: {calls}"


class TestThePodMemberStrip:
    """S9, S10 — `--userns` is a POD-level property, which is a PODMAN statement, not a universal
    one. Docker has no pod, so the harness container is where the mapping has to land."""

    def _backend(self, rt: str, tmp_path: Path) -> launcher.ContainerBackend:
        backend = launcher.ContainerBackend(
            rt, "inst", "pod", tmp_path / "prof", "img", tmp_path / "proj",
            [], [], None, stack_from_overlay=False, headless=True,
        )
        backend.mount_args = [*paths.userns_args(rt), "-v", "/host/a:/ctr/a", "-e", "FOO=1"]
        return backend

    def test_podman_strips_it_from_the_member(self, tmp_path):
        """S9 — unchanged: podman rejects `--userns` on a pod member outright."""
        backend = self._backend("podman", tmp_path)
        backend.wire_mcp(LaunchSpec(stack="s", harness="claude", project_path=tmp_path / "proj"))
        assert not any(a.startswith("--userns") for a in backend.member_mounts)
        assert "-v" in backend.member_mounts and "/host/a:/ctr/a" in backend.member_mounts
        assert "FOO=1" in backend.member_mounts

    def test_docker_keeps_it_because_there_is_no_pod_to_inherit_from(self, tmp_path):
        """S10. Stripping here is a pure loss: nothing else on the docker path sets the mapping."""
        backend = self._backend("docker", tmp_path)
        backend.wire_mcp(LaunchSpec(stack="s", harness="claude", project_path=tmp_path / "proj"))
        assert "--userns=host" in backend.member_mounts
        assert "-v" in backend.member_mounts and "/host/a:/ctr/a" in backend.member_mounts
        assert "FOO=1" in backend.member_mounts


class TestOneRuntimeDetector:
    """S12 — the deliberate widening (SPEC Decide #5).

    Making the emit sites take `rt` explicitly while the reasoning sites self-detect creates a
    SECOND way to learn the runtime. Two detectors that agree today are two detectors that can
    disagree later, and the disagreement would be invisible: argv built for one runtime, ownership
    checked against the other."""

    def test_the_two_entry_points_agree(self, monkeypatch):
        """The REAL detector on both sides. Left pinned by conftest, both sides would return the
        pinned value and this would assert that a constant equals itself."""
        monkeypatch.setattr(paths, "active_runtime", _REAL_ACTIVE_RUNTIME)
        assert ctrquery._runtime() == _REAL_ACTIVE_RUNTIME()

    def test_ctrquery_delegates_rather_than_scanning_again(self, monkeypatch):
        """Assert the DELEGATION, not the call count: if ctrquery kept its own `shutil.which`
        sweep, pinning the one in paths would not move its answer."""
        monkeypatch.setattr(paths, "active_runtime", lambda: "nerdctl")
        assert ctrquery._runtime() == "nerdctl"


class TestEveryInstallStepMatchesItsRuntime:
    """S13 — real argv out of the real executor. A volume written under a mapping that differs from
    the one the agent runs under is unreadable by the agent (bd harnessed-8px.21.1)."""

    def _argv(self, rt: str, tmp_path, monkeypatch) -> list[list[str]]:
        d = tmp_path / "r"
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe.yaml").write_text('name: r\ntools: ["npm:x@1"]\ninstall:\n  script: install.sh\n')
        (d / "install.sh").write_text("true\n")
        load_recipe(d, strict=True)
        calls: list[list[str]] = []
        patch_all(monkeypatch, "_run", lambda cmd, *a, **k: calls.append(list(cmd)))
        monkeypatch.setattr(
            launcher.paths, "install_cache_dir",
            lambda name, key: tmp_path / "cache" / name / key,
        )
        launcher._run_container_installs(
            rt, "s", "claude", "img", [load_recipe(d, strict=True)], "cfgvol", "toolsvol",
        )
        return calls

    @pytest.mark.parametrize("rt", ["podman", "docker"])
    def test_every_step_carries_exactly_its_runtimes_mapping(self, rt, tmp_path, monkeypatch):
        argvs = self._argv(rt, tmp_path, monkeypatch)
        assert argvs, "the executor ran no steps — this test would pass vacuously"
        want = paths.userns_args(rt)
        for cmd in argvs:
            got = [a for a in cmd if a.startswith("--userns")]
            assert got == want, f"step does not match the {rt} mapping: {cmd}"


class TestRootlessDockerIsRefusedBeforeAnythingIsCreated:
    """S16. The ownership guard alone is not a refusal: it fires only where it is CONSULTED, and a
    launch that touches no persist dir never reaches it. That launch would proceed straight into
    the subuid breakage that picking `--userns=host` was supposed to avoid."""

    def test_rootless_docker_stops_the_run(self, monkeypatch, capsys):
        """Message content asserted for the same reason as the guard's: S16 promises it "names
        rootless and says what the user can do about it", and 15 mutants inside this message
        survived while the only assertion was one substring."""
        _pin(monkeypatch, "docker", rootless=True)
        with pytest.raises(typer.Exit) as ei:
            launcher._preflight_runtime("docker")
        # The CODE, not just the type. `typer.Exit(None)` and `typer.Exit(0)` both raise Exit and
        # both mean SUCCESS -- a refusal that exits 0 is a refusal the shell, CI and every caller
        # reads as "fine". Two surviving mutants sat exactly here.
        assert ei.value.exit_code == 1
        captured = capsys.readouterr()  # consumes; one call only
        msg = (captured.out + captured.err).lower()
        assert "rootless" in msg, "must name the cause"
        assert str(paths.CONTAINER_UID) in msg, "must name the uid that cannot be mapped"
        assert "subuid" in msg, "must say why that uid is unpredictable"
        assert "rootful" in msg and "podman" in msg, "must name both remediations"

    def test_an_unreadable_daemon_also_stops_the_run(self, monkeypatch, capsys):
        _pin(monkeypatch, "docker", rootless=None)
        with pytest.raises(typer.Exit) as ei:
            launcher._preflight_runtime("docker")
        assert ei.value.exit_code == 1
        captured = capsys.readouterr()
        msg = (captured.out + captured.err).lower()
        assert "docker info" in msg, "must name the probe that could not be read, not blame rootless"

    def test_rootful_docker_passes_the_preflight(self, monkeypatch):
        _pin(monkeypatch, "docker", rootless=False)
        launcher._preflight_runtime("docker")  # no raise

    def test_podman_passes_the_preflight(self, monkeypatch):
        _pin(monkeypatch, "podman")
        launcher._preflight_runtime("podman")  # no raise


class TestTheRootlessProbeItself:
    """The probe's OWN failure paths, driven through `subprocess`.

    `TestTheDerivedHostUid` patches `docker_is_rootless` wholesale, so it proves what
    `pod_host_uid` does with an answer and NOTHING about how that answer is reached. Both sides of
    that seam need driving: `diff-cover` reported these four lines unexecuted, and the missing
    half is the half where "refuse rather than guess" is actually implemented.
    """

    def test_the_probe_asks_docker_the_right_question(self, monkeypatch):
        """Assert the ARGV and the kwargs, not just what we do with the answer.

        Mocking `subprocess.run` and checking only the return value leaves the call itself
        unconstrained, and mutation showed what hides there: `"docker"`->`"DOCKER"`,
        `"info"`->`"INFO"`, `"--format"`->`"--FORMAT"` all survive (and all fail on a
        case-sensitive filesystem), and so does lowercasing the Go template — which returns EMPTY,
        so `name=rootless` is never found and every rootless daemon reads as ROOTFUL. That last one
        is the exact fail-open this function exists to prevent, and no assertion here saw it.
        """
        seen: dict[str, object] = {}

        def _capture(cmd, **kwargs):
            seen["cmd"] = list(cmd)
            seen.update(kwargs)
            return subprocess.CompletedProcess(cmd, 0, stdout="name=seccomp\n", stderr="")

        monkeypatch.setattr(paths.subprocess, "run", _capture)
        paths._probe_docker_rootless()

        assert seen["cmd"] == [
            "docker", "info", "--format", "{{range .SecurityOptions}}{{.}} {{end}}",
        ], "the probe must ask docker for SecurityOptions, spelled exactly as docker spells it"
        # stdout must be captured as TEXT, or the membership test below explodes on None/bytes.
        assert seen["capture_output"] is True
        assert seen["text"] is True
        # Unbounded, this blocks a launch forever on a wedged daemon.
        assert seen["timeout"] == paths._DOCKER_INFO_TIMEOUT

    def test_a_rootless_daemon_is_detected(self, monkeypatch):
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a[0] if a else [], 0, stdout="name=seccomp name=rootless name=cgroupns\n", stderr="",
        ))
        assert paths._probe_docker_rootless() is True

    def test_a_rootful_daemon_is_detected(self, monkeypatch):
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a[0] if a else [], 0, stdout="name=seccomp name=cgroupns\n", stderr="",
        ))
        assert paths._probe_docker_rootless() is False

    def test_a_daemon_that_cannot_be_reached_is_undetermined(self, monkeypatch):
        """`docker info` exits nonzero — daemon down, or the socket refuses this user. NOT False:
        answering "rootful" here would be a guess, and the guess is the fail-open direction."""
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a[0] if a else [], 1, stdout="", stderr="Cannot connect to the Docker daemon",
        ))
        assert paths._probe_docker_rootless() is None

    @pytest.mark.parametrize("boom", [
        FileNotFoundError("docker"),                       # vanished between PATH check and here
        PermissionError("/var/run/docker.sock"),           # socket not readable by this user
        subprocess.TimeoutExpired(["docker", "info"], 30),  # daemon wedged
    ])
    def test_a_probe_that_raises_is_undetermined(self, monkeypatch, boom):
        """Every one of these is a live failure mode, and none may become an exception escaping
        into a launch: the caller's contract is three-valued, and this is the third value."""
        def _raise(*_a, **_k):
            raise boom
        monkeypatch.setattr(paths.subprocess, "run", _raise)
        assert paths._probe_docker_rootless() is None


class TestNoRuntimeAtAll:
    """`active_runtime` is the one place that can answer "neither"; `ctrquery._runtime` is the one
    place that turns that into something a user can read."""

    def test_active_runtime_is_none_when_neither_binary_exists(self, monkeypatch):
        monkeypatch.setattr(paths.shutil, "which", lambda _name: None)
        assert paths._detect_runtime() is None

    @pytest.mark.parametrize("installed, expected", [
        ({"podman"}, "podman"),
        ({"docker"}, "docker"),
        ({"podman", "docker"}, "podman"),  # PREFERENCE, not accident of iteration
    ])
    def test_it_looks_for_the_right_binaries_and_prefers_podman(
        self, monkeypatch, installed, expected,
    ):
        """The binary NAMES and their ORDER are both behaviour.

        Testing only the neither-installed case left the two string literals unconstrained:
        `"podman"`->`"PODMAN"` survived, and on a case-sensitive filesystem that detector finds
        nothing and every launch reports "neither podman nor docker found". The podman-first
        ordering is a real preference (pods, pasta, keep-id), not an implementation detail.
        """
        monkeypatch.setattr(
            paths.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None,
        )
        assert paths._detect_runtime() == expected

    def test_ctrquery_exits_with_a_readable_error(self, monkeypatch, capsys):
        monkeypatch.setattr(paths, "active_runtime", lambda: None)
        with pytest.raises(typer.Exit) as ei:
            ctrquery._runtime()
        assert ei.value.exit_code == 1, "a runtime-less box must FAIL, not exit 0 with a warning"
        out = capsys.readouterr()
        assert "neither podman nor docker" in (out.out + out.err)


class TestTheBuildPathRefusesToo:
    """S16 reaches `container_run`; `_build_stack` is the OTHER entry point, and a refusal that
    covers only one of them leaves `harnessed build` walking into the same breakage."""

    def test_build_refuses_rootless_docker_before_touching_the_catalog(self, monkeypatch):
        _pin(monkeypatch, "docker", rootless=True)
        looked_up: list[str] = []
        monkeypatch.setattr(
            launcher.paths, "find_in_catalog",
            lambda kind, name: looked_up.append(name),  # type: ignore[func-returns-value]
        )
        with pytest.raises(typer.Exit) as ei:
            launcher._build_stack("docker", "s", "claude")
        assert ei.value.exit_code == 1
        assert not looked_up, "the preflight must refuse BEFORE any stack resolution happens"


class TestTheFingerprintStepMatchesItsRuntime:
    """`_ensure_stack_volumes` writes the stack fingerprint in its own container, after the
    installs. It is the last write into the config volume, so a mapping that differs there leaves
    a file the agent cannot read — the same class as bd harnessed-8px.21.1, one step later."""

    @pytest.mark.parametrize("rt", ["podman", "docker"])
    def test_the_fingerprint_write_carries_the_mapping(self, rt, tmp_path, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(volumes, "_run", lambda cmd, *a, **k: calls.append(list(cmd)))
        monkeypatch.setattr(volumes, "_ensure_config_volume", lambda *a, **k: "cfgvol")
        monkeypatch.setattr(volumes, "_run_container_installs", lambda *a, **k: None)
        monkeypatch.setattr(volumes, "_container_stack_fingerprint", lambda *a, **k: "fp")
        # A fingerprint that does NOT match forces the install+stamp path; matching would return
        # early and this test would assert over an empty list.
        monkeypatch.setattr(volumes, "_volume_read", lambda *a, **k: "stale")

        volumes._ensure_stack_volumes(rt, "s", "claude", tmp_path, "img", [])

        # `_run` also builds the two `volume create` calls, which carry no mapping and should not.
        # Select the stamping container by the file it writes, so the assertion cannot drift onto
        # some other step that happens to say `run`.
        stamps = [c for c in calls if any(_HOST_STACK_FINGERPRINT in a for a in c)]
        assert stamps, "no fingerprint step ran — this test would pass vacuously"
        want = paths.userns_args(rt)
        for cmd in stamps:
            assert [a for a in cmd if a.startswith("--userns")] == want, cmd
        # ...and the volume-create calls must stay clean: `--userns` is meaningless there.
        for cmd in calls:
            if "volume" in cmd:
                assert not [a for a in cmd if a.startswith("--userns")], cmd


@DOCKER
class TestAgainstARealDockerDaemon:
    """S14, S15 — the only layer that proves the FIX rather than the call sites.

    Everything above asserts which strings are emitted. These two assert what docker DOES with
    them, which is the question the unit tests structurally cannot ask."""

    IMAGE = "alpine:3.20"

    def test_the_456_repro_still_fails_the_old_way(self, tmp_path):
        """S14. Guard the guard: if this ever stops failing, docker grew a `keep-id` mode and the
        premise of this whole change moved."""
        proc = subprocess.run(
            ["docker", "run", "--rm", paths.USERNS_ARG, "--entrypoint", "true", self.IMAGE],
            capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 125, f"expected docker to reject keep-id, got {proc.returncode}"
        assert "invalid USER mode" in proc.stderr

    def test_the_chosen_argument_lets_the_container_write_the_bind_mount(self, tmp_path):
        """S15. The write that #456 was standing in front of."""
        target = tmp_path / "data"
        target.mkdir()
        proc = subprocess.run(
            ["docker", "run", "--rm", *paths.userns_args("docker"),
             "--user", f"{paths.CONTAINER_UID}:{paths.CONTAINER_GID}",
             "-v", f"{target}:/data:rw", "--entrypoint", "mkdir", self.IMAGE, "-p", "/data/dolt"],
            capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        assert (target / "dolt").stat().st_uid == paths.CONTAINER_UID
