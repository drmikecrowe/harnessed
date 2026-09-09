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

import pytest
import typer

from harnessed import capability, ctrquery, launcher, launchenv, paths, persist, volumes


class _Recorded:
    """What a mocked `volumes._run` hands back.

    `_volume_exists` reads `.returncode`, so a recorder returning None now raises AttributeError
    inside the code under test. `returncode=1` means "no such volume", which is the state these
    tests are about: a volume this run creates, and therefore chowns.
    """

    def __init__(self, returncode: int = 1) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _recorder(sink, *, with_kwargs: bool = False):
    def _run(cmd, *a, **k):
        sink.append((list(cmd), dict(k)) if with_kwargs else list(cmd))
        return _Recorded()
    return _run
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

    def test_rootful_docker_resolves_to_the_invoking_user(self, monkeypatch):
        """S5, revised by #457. Rootful docker plus `container_user_args` runs the agent AS THE
        INVOKING USER, so the host uid it writes as is `os.getuid()` — the same answer podman's
        `keep-id` gives, reached by a different mechanism.

        This assertion used to read `== CONTAINER_UID`, which was true only while the agent ran as
        the image's uid, and was the fail-open half of #457: it encoded the defect as expected
        behaviour, which is why every mechanical layer reported the bug absent."""
        _pin(monkeypatch, "docker", rootless=False)
        monkeypatch.setattr(paths.os, "getuid", lambda: self._NOT_THE_IMAGE_UID)
        assert paths.pod_host_uid() == self._NOT_THE_IMAGE_UID
        assert paths.pod_host_uid() != paths.CONTAINER_UID

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


class TestTheAgentContainerActuallyGetsTheMapping:
    """The site that DELIVERS the mapping to the agent — `launcher._agent_placement_args`.

    An earlier version of this class asserted against a `mount_args` list the test itself had
    filled with `--userns`. Production never puts one there: every element of `mount_args` comes
    from the `mounts.py` builders, and `rg 'userns' src/harnessed/mounts.py` is EMPTY. So the test
    passed, `_without_userns` had nothing to strip on either branch, and the docker agent was
    created with no user-namespace mapping at all. Found by adversarial review, not by the
    gauntlet: coverage, mutation and 3582 green tests all reported it absent, because a test that
    fabricates its own input measures the fabrication.

    These assert the real function's real output."""

    def test_podman_inherits_the_mapping_from_its_pod(self):
        """podman REJECTS `--userns` on a pod member — `pod create` carries it instead."""
        args = launcher._agent_placement_args("podman", "thepod", "theinst")
        assert args == ["--pod", "thepod"]
        assert not any(a.startswith("--userns") for a in args)

    def test_docker_states_the_mapping_on_the_container_itself(self):
        """No pod means nothing to inherit from, and nothing else on this path sets it."""
        args = launcher._agent_placement_args("docker", "theanchor", "theinst")
        assert "--userns=host" in args, (
            "the docker agent container must carry the mapping itself; there is no pod to "
            f"inherit it from and no mount builder emits it: {args}"
        )
        assert "--hostname" in args

    def test_docker_agent_owns_its_netns_rather_than_joining_one(self):
        """#458. The agent is the anchor on a pod-less runtime, so it joins nothing.

        The old shape emitted `--network=container:{pod}`, naming a container that is never
        created when there is no pod. Docker rejected the `--hostname` + network-mode conflict
        first, so the dangling anchor was never reached — one defect masking another."""
        args = launcher._agent_placement_args("docker", "theanchor", "theinst")
        assert not any(a.startswith("--network") for a in args), (
            f"the agent must OWN the netns, not join one: {args}"
        )
        # ...and owning it is what makes --hostname legal: docker refuses the two together.
        assert "--hostname" in args and "theinst" in " ".join(args)


class TestTheAgentRunsAsTheInvokingUserOnDocker:
    """#457. The two halves that must not be split.

    podman `keep-id` maps the invoking user onto the image's uid, so the agent writes as you.
    Docker maps nothing, so without `--user` it writes as host uid 1000 whoever launched it —
    correct only by coincidence, and wrong on every GitHub runner (uid 1001), which is precisely
    what kept docker out of CI.

    Running as uid N against volumes owned by 1000 is not an improvement on the reverse; it is the
    same defect with different numbers. So `container_user_args` and `container_owner_ids` are
    asserted to agree, and the volume chown is asserted to use the second."""

    def test_docker_runs_the_agent_as_the_invoking_uid_in_group_zero(self, monkeypatch):
        """The uid is the invoker's; the GROUP is 0, and the gid is deliberately ignored.

        Docker creates no mapping, so the agent is an uid this image never made. Group 0 is the one
        group such an uid is guaranteed to hold, and the base image gives $HOME to group 0 to match.
        With the invoker's own gid the agent could not traverse /home/harnessed at all -- measured
        as `cp: cannot stat '/home/harnessed/.claude/'` on a uid-1001 runner."""
        monkeypatch.setattr(paths.os, "getuid", lambda: 1001)
        monkeypatch.setattr(paths.os, "getgid", lambda: 1002)
        assert paths.container_user_args("docker") == ["--user", "1001:0"]

    def test_podman_gets_no_user_flag(self):
        """`keep-id` already did this job; `--user` on top would fight the mapping."""
        assert paths.container_user_args("podman") == []

    def test_the_ids_the_agent_runs_as_and_the_volume_is_chowned_to_are_the_same(self, monkeypatch):
        monkeypatch.setattr(paths.os, "getuid", lambda: 1001)
        monkeypatch.setattr(paths.os, "getgid", lambda: 1002)
        uid, gid = paths.container_owner_ids("docker")
        assert paths.container_user_args("docker") == ["--user", f"{uid}:{gid}"]
        # And the group is 0 on BOTH sides. A volume chowned to the invoker's own gid is unreadable
        # to a process running as gid 0, so "they agree" has to mean the group too, not just the uid.
        assert gid == 0, "the docker group must be 0, not the invoker's gid"

    def test_podman_volumes_stay_on_the_image_uid(self):
        """podman's mapping makes the image uid the right owner; only docker moves."""
        assert paths.container_owner_ids("podman") == (paths.CONTAINER_UID, paths.CONTAINER_GID)

    def test_the_agent_placement_carries_the_user_flag_on_docker(self, monkeypatch):
        monkeypatch.setattr(paths.os, "getuid", lambda: 1001)
        monkeypatch.setattr(paths.os, "getgid", lambda: 1002)
        args = launcher._agent_placement_args("docker", "anchor", "inst")
        assert "--user" in args and "1001:0" in args

    def test_the_volume_chown_uses_the_invoking_ids(self, monkeypatch):
        monkeypatch.setattr(paths.os, "getuid", lambda: 1001)
        monkeypatch.setattr(paths.os, "getgid", lambda: 1002)
        calls: list[list[str]] = []
        monkeypatch.setattr(volumes, "_run", _recorder(calls))
        volumes._chown_volume_for_docker("docker", "thevol", "theimage", "/home/harnessed/.claude")
        # Group 0, matching what the agent runs as -- see the --user test above.
        assert "1001:0" in calls[0], calls[0]


class TestEverythingElseJoinsTheAnchor:
    """`_netns_anchor` — the pod on podman, the agent container on docker."""

    def test_podman_anchors_on_the_pod(self):
        assert launcher._netns_anchor("podman", "thepod", "theinst") == "thepod"

    def test_docker_anchors_on_the_agent_container(self):
        assert launcher._netns_anchor("docker", "thepod", "theinst") == "theinst"

    def test_it_asks_which_runtime_not_which_value_is_truthy(self):
        """The site this replaced read `self.pod or self.inst`, which looks like a fallback for a
        missing pod name. `self.pod` is ALWAYS set, so on docker it always chose the pod — a
        container that does not exist. A non-empty pod name must still yield the instance."""
        assert launcher._netns_anchor("docker", "a-non-empty-pod-name", "theinst") == "theinst"

    def test_the_firewall_runner_joins_the_agent_on_docker(self):
        """End of the chain: the runner must land in the agent's netns or it confines nothing."""
        anchor = launcher._netns_anchor("docker", "thepod", "theinst")
        argv = launcher._firewall_runner_argv("docker", anchor, "img")
        assert "--network=container:theinst" in argv

    def test_the_two_runtimes_do_not_share_a_placement(self):
        """Guard the guard: if these ever returned the same list, one of the two is wrong."""
        assert (launcher._agent_placement_args("podman", "p", "i")
                != launcher._agent_placement_args("docker", "p", "i"))


class TestTheFirewallRunnerSharesTheAgentsMapping:
    """The egress-firewall runner joins the agent's netns to install iptables rules.

    It must sit in the SAME user namespace as the agent, not merely have some mapping: iptables run
    from a different userns than the netns it configures returns EPERM, so a mismatch installs
    nothing and the agent it was meant to confine runs wide open. This emit site was missing from
    the original enumeration entirely."""

    def test_docker_runner_carries_the_same_mapping_as_the_agent(self):
        runner = launcher._firewall_runner_argv("docker", "anchor", "img")
        agent = launcher._agent_placement_args("docker", "anchor", "inst")
        runner_ns = [a for a in runner if a.startswith("--userns")]
        agent_ns = [a for a in agent if a.startswith("--userns")]
        assert runner_ns == agent_ns == ["--userns=host"], (
            f"runner {runner_ns} must match agent {agent_ns} or the rules confine a foreign netns"
        )

    def test_podman_runner_carries_none_because_the_pod_owns_it(self):
        runner = launcher._firewall_runner_argv("podman", "anchor", "img")
        assert not any(a.startswith("--userns") for a in runner)
        assert "--pod" in runner


class TestOneRuntimeDetector:
    """S12 — the deliberate widening (SPEC Decide #5).

    Making the emit sites take `rt` explicitly while the reasoning sites self-detect creates a
    SECOND way to learn the runtime. Two detectors that agree today are two detectors that can
    disagree later, and the disagreement would be invisible: argv built for one runtime, ownership
    checked against the other."""

    def test_the_two_entry_points_agree(self, monkeypatch):
        """The REAL detector on both sides. Left pinned by conftest, both sides would return the
        pinned value and this would assert that a constant equals itself.

        SKIPPED where neither binary exists. Unpinning the detector is the whole point of this
        test, and with no runtime installed the real one returns None, which `ctrquery._runtime`
        turns into `typer.Exit(1)` before the comparison — an ERROR in the hermetic suite, on a
        machine that simply cannot host the agreement this asserts. The runtime-less path is not
        left uncovered: `TestNoRuntimeAtAll` owns it, with the detector faked rather than absent.
        """
        monkeypatch.setattr(paths, "active_runtime", _REAL_ACTIVE_RUNTIME)
        if _REAL_ACTIVE_RUNTIME() is None:
            pytest.skip("no container runtime installed; agreement is unobservable here")
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
        patch_all(monkeypatch, "_run", _recorder(calls))
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
        monkeypatch.setattr(launcher.os, "getuid", lambda: paths.CONTAINER_UID)
        launcher._preflight_runtime("docker")  # no raise

    def test_a_non_1000_user_is_supported_on_docker(self, monkeypatch):
        """#457, resolved. `container_user_args` runs the agent as the invoking user and
        `_chown_volume_for_docker` gives the volumes the same ids, so any uid works.

        This test previously asserted a REFUSAL. That was correct while the agent ran as the
        image's uid — and it would now reject the case `--user` exists to support, including every
        GitHub runner, which is uid 1001. Inverted deliberately, with the behaviour it covers."""
        _pin(monkeypatch, "docker", rootless=False)
        monkeypatch.setattr(launcher.os, "getuid", lambda: paths.CONTAINER_UID + 1)
        launcher._preflight_runtime("docker")  # no raise

    def test_podman_does_not_care_about_the_invoking_uid(self, monkeypatch):
        """keep-id maps whoever you are onto the image uid, so there is nothing to refuse."""
        _pin(monkeypatch, "podman")
        monkeypatch.setattr(launcher.os, "getuid", lambda: paths.CONTAINER_UID + 1)
        launcher._preflight_runtime("podman")  # no raise

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

    def test_a_userns_remapped_daemon_is_rootful_because_we_opt_out_per_container(self, monkeypatch):
        """A daemon started with `--userns-remap` reports `name=userns`, NOT `name=rootless`.

        It is a THIRD state, and classifying it as rootful is only correct because harnessed passes
        `--userns=host` on every container it creates, which opts that container out of the remap.
        The claim and the flag are coupled: if any creation site stops emitting the flag, this
        classification becomes a fail-open — `pod_host_uid` would answer 1000 for a container whose
        host writer is a subuid like 165536. `TestTheAgentContainerActuallyGetsTheMapping` and
        `TestTheFirewallRunnerSharesTheAgentsMapping` are what hold the other half."""
        monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a[0] if a else [], 0, stdout="name=seccomp name=userns name=cgroupns\n", stderr="",
        ))
        assert paths._probe_docker_rootless() is False
        assert paths.DOCKER_USERNS_ARG == "--userns=host", (
            "the rootful classification above is only sound while this flag is what we emit"
        )

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


class TestTheFirewallRunnerArgvIsPinnedElementForElement:
    """`_firewall_runner_argv` builds a container that is handed CAP_NET_ADMIN over the agent's
    network namespace. Every element is security-relevant, and before this class only
    `--network=container:` was asserted.

    Mutation found 19 survivors here once PR #461 review added the function to the selectors:
    `"run"` -> `"XXrunXX"`, `"--cap-add"` -> `"--CAP-ADD"`, `"root"` -> `"ROOT"`, `"-v"` -> `"-V"`.
    Each produces a runtime error or, worse, a runner that starts without the capability and
    silently installs no rules -- the shape of #429, where an effective set of 0 kept the defect
    hidden behind a container that appeared to run fine.
    """

    def _expected_tail(self):
        return [
            "--cap-add", "NET_ADMIN",
            "--user", "root",
            "-v", f"{launcher._catalog_base('egress-firewall.sh')}:/usr/local/sbin/egress-firewall:ro",
            "--entrypoint", "",
            "img",
        ]

    def test_podman_joins_the_pod_and_carries_no_mapping_of_its_own(self):
        """On podman the mapping is a POD property, inherited. Stating it on a member is rejected."""
        argv = launcher._firewall_runner_argv("podman", "thepod", "img")
        assert argv == ["podman", "run", "--rm", "--pod", "thepod", *self._expected_tail()]

    def test_docker_joins_the_agent_netns_and_states_the_mapping(self):
        """No pod exists, so the runner must name the agent container AND repeat its userns. A
        mismatch is not cosmetic: iptables run from a different user namespace than the netns it
        configures returns EPERM, so the rules confine nothing and the agent runs wide open."""
        argv = launcher._firewall_runner_argv("docker", "theinst", "img")
        assert argv == [
            "docker", "run", "--rm",
            "--network=container:theinst", "--userns=host",
            *self._expected_tail(),
        ]

    def test_the_capability_is_granted_and_the_user_is_root(self):
        """Named separately because these two are the reason the container exists. NET_ADMIN in the
        bounding set alone is not enough -- the image's default user is unprivileged and iptables
        carries no file capabilities."""
        argv = launcher._firewall_runner_argv("docker", "i", "img")
        assert argv[argv.index("--cap-add") + 1] == "NET_ADMIN"
        assert argv[argv.index("--user") + 1] == "root"


class TestTheApiEndpointHostsAreParsedNotGuessed:
    """`api_endpoint_egress_hosts` -- the DROP-policy firewall opens only what it is told about, and
    a repointed `ANTHROPIC_BASE_URL` is told to it by nothing else. A host dropped here presents to
    the user as an authentication failure, because the request never arrives to be authenticated."""

    def test_a_normal_url_yields_its_hostname(self):
        assert launchenv.api_endpoint_egress_hosts(
            {"ANTHROPIC_BASE_URL": "https://api.z.ai/v1"}
        ) == ["api.z.ai"]

    def test_a_scheme_less_value_strips_both_the_port_and_the_path(self):
        """The fallback branch, and the one mutation reached: `urlsplit` parses a bare host as a
        PATH, not a netloc, so without this a scheme-less value yields no host and is silently
        dropped -- reinstating the exact defect the function exists to close. Both separators are
        behaviour; mutation turned each of `"/"` and `":"` into whitespace with nothing failing."""
        assert launchenv.api_endpoint_egress_hosts(
            {"ANTHROPIC_BASE_URL": "gateway.internal:8443/v1/messages"}
        ) == ["gateway.internal"]
        # WITHOUT a port, deliberately. With one, the `":"` split alone produces the right answer
        # for every mutation of the `"/"` split, so the port case cannot distinguish them -- it let
        # `split("/")` -> `split(None)` and `-> split("XX/XX")` both survive. A path-only value is
        # the input where the two separators do different work.
        assert launchenv.api_endpoint_egress_hosts(
            {"ANTHROPIC_BASE_URL": "gateway.internal/v1/messages"}
        ) == ["gateway.internal"]

    def test_blank_and_absent_values_contribute_nothing(self):
        assert launchenv.api_endpoint_egress_hosts({}) == []
        assert launchenv.api_endpoint_egress_hosts({"ANTHROPIC_BASE_URL": "   "}) == []

    def test_all_three_variables_are_read_and_duplicates_collapse(self):
        assert launchenv.api_endpoint_egress_hosts({
            "ANTHROPIC_BASE_URL": "https://one.example",
            "ANTHROPIC_BEDROCK_BASE_URL": "https://two.example",
            "ANTHROPIC_VERTEX_BASE_URL": "https://one.example",
        }) == ["one.example", "two.example"]


class TestCapabilityRuntimeDelegates:
    """`capability._runtime` -- six mutants reported "no tests" until PR #461 review put it in the
    selectors. It was the second detector #456 removed, and it is where `CONTAINER_RUNTIME` used
    to be honoured, so a body that drifts back to scanning PATH itself would be invisible."""

    def test_it_returns_what_the_single_detector_returns(self, monkeypatch):
        monkeypatch.setattr(capability.paths, "active_runtime", lambda: "nerdctl")
        assert capability._runtime() == "nerdctl"

    def test_it_raises_rather_than_naming_a_runtime_that_is_not_installed(self, monkeypatch):
        """The body this replaced answered "docker" whenever podman was absent, WITHOUT checking
        docker exists -- so on a box with neither it returned a runtime and exec'd it (#459)."""
        monkeypatch.setattr(capability.paths, "active_runtime", lambda: None)
        with pytest.raises(RuntimeError) as exc:
            capability._runtime()
        assert "podman" in str(exc.value) and "docker" in str(exc.value)


class TestContainerRuntimeOverride:
    """`CONTAINER_RUNTIME` — the FIRST branch of `_detect_runtime`, and, before this class, the
    only part of #456 with no test naming it at all.

    It is the whole mechanism the `live-docker` CI job turns on: a GitHub runner has BOTH binaries
    installed, so PATH order alone always yields podman and a docker job is inexpressible. That
    job's own comment states the failure mode — without the override it "would silently retest the
    podman path while reporting itself as docker coverage", which is a green tick over a runtime
    nobody exercised.

    Mutation is what surfaced the gap (PR #461 review added this function's siblings to the
    selectors): `forced = None` — deleting the env read outright — survived, along with the
    variable's own NAME and both literals in the validation tuple. Ten mutants, no failing test.
    """

    def _detect(self, monkeypatch, *, env: str | None, installed=("podman", "docker")):
        if env is None:
            monkeypatch.delenv("CONTAINER_RUNTIME", raising=False)
        else:
            monkeypatch.setenv("CONTAINER_RUNTIME", env)
        monkeypatch.setattr(
            paths.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
        )
        return paths._detect_runtime()

    def test_it_selects_docker_even_though_podman_is_installed_and_preferred(self, monkeypatch):
        """The load-bearing case. With both binaries present, PATH order yields podman; only the
        override can reach docker, so this is what makes the `live-docker` job mean anything."""
        assert self._detect(monkeypatch, env="docker") == "docker"

    def test_it_selects_podman_when_asked_for_podman(self, monkeypatch):
        """Not redundant with the default: it pins the `"podman"` literal in the validation tuple,
        which is otherwise satisfied by the fall-through and reads as tested when it is not."""
        assert self._detect(monkeypatch, env="podman") == "podman"

    def test_the_variable_name_is_the_behaviour(self, monkeypatch):
        """A misspelled name reads as unset and falls through to podman-first — silently, which is
        the same green-over-nothing this class exists to stop."""
        monkeypatch.setenv("CONTAINER_RUNTIME", "docker")
        monkeypatch.setattr(paths.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert paths._detect_runtime() == "docker", (
            "the override was not read under its documented name"
        )

    def test_an_unset_or_blank_value_falls_through_to_detection(self, monkeypatch):
        """Blank is NOT an error: `CONTAINER_RUNTIME=` is how a caller clears an inherited value,
        and `.strip()` is what makes whitespace mean the same thing."""
        assert self._detect(monkeypatch, env=None) == "podman"
        assert self._detect(monkeypatch, env="") == "podman"
        assert self._detect(monkeypatch, env="   ") == "podman"

    def test_it_refuses_an_unrecognised_value_rather_than_ignoring_it(self, monkeypatch):
        """A typo'd `dcoker` that fell through to podman would run the whole suite against the
        wrong runtime and report a pass — the failure `paths.py` says this branch exists to stop."""
        with pytest.raises(ValueError) as exc:
            self._detect(monkeypatch, env="dcoker")
        # The BAD VALUE must appear: a message that does not name it cannot be acted on, and this
        # is what kills the mutant replacing the whole f-string with `None`. Asserting the value
        # rather than the prose keeps it off the brittle-message path anti-gaming rule 4 warns of.
        assert "dcoker" in str(exc.value)

    def test_a_forced_runtime_that_is_not_installed_is_none_not_a_lie(self, monkeypatch):
        """`shutil.which` still decides. Returning the name of a binary that is absent would hand
        every later call an argv whose first element cannot execute."""
        assert self._detect(monkeypatch, env="docker", installed=("podman",)) is None

    def test_the_override_beats_the_podman_preference_both_ways(self, monkeypatch):
        """Guard the guard: if the override were dropped, BOTH values would answer podman here."""
        assert self._detect(monkeypatch, env="docker") != self._detect(monkeypatch, env="podman")


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
        monkeypatch.setattr(volumes, "_run", _recorder(calls))
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


class TestDockerNamedVolumesAreChowned:
    """PHASE 2 (issue filed separately): docker does not chown a new named volume.

    podman chowns a fresh named volume to match the container's user namespace. Docker only copies
    ownership when the mount point already exists in the image; otherwise the volume is an empty
    dir owned by root:root. The container runs as uid 1000, so the first populate step dies with

        cp: cannot create directory '/home/harnessed/.claude/./skills': Permission denied

    which is exactly where `harnessed build` stopped on docker once #456 was fixed -- observed on a
    real daemon, not hypothesised."""

    def _invocations(self, monkeypatch, rt: str) -> list[tuple[list[str], dict]]:
        """argv AND kwargs. `_calls` drops the kwargs, which left `check=` and `capture_output=`
        unconstrained -- mutation found `check=False` -> `check=True` surviving, i.e. the suite did
        not encode the decision the code's own comment argues for."""
        self._pin_invoker(monkeypatch)
        seen: list[tuple[list[str], dict]] = []
        monkeypatch.setattr(volumes, "_run", _recorder(seen, with_kwargs=True))
        volumes._chown_volume_for_docker(rt, "thevol", "img", "/home/harnessed/.claude")
        return seen

    def test_the_chown_does_not_raise_on_failure(self, monkeypatch):
        """`check=False`, deliberately, and now asserted rather than argued in a comment.

        Raised on PR #461 review as a defect ("use check=True"); dismissed, because `proc._run`
        defaults to `check=True` and `_run_container_installs` uses that default, so a volume left
        root-owned fails at the very next step with stderr surfaced in the user's terms rather than
        as a bare CalledProcessError traceback out of `harnessed build`. A dismissal that lives
        only in prose is not a decision the suite protects -- this is the same claim, executable.
        """
        _, kwargs = self._invocations(monkeypatch, "docker")[0]
        assert kwargs.get("check") is False, kwargs

    def test_the_chown_captures_output_rather_than_printing_it(self, monkeypatch):
        """It is a repair step, not a build step. Streaming a root chown's output into the build log
        would put a `chown: changing ownership` line in front of the user for every volume."""
        _, kwargs = self._invocations(monkeypatch, "docker")[0]
        assert kwargs.get("capture_output") is True, kwargs

    def test_the_whole_argv_is_pinned_not_just_the_parts_that_moved(self, monkeypatch):
        """Element for element. Asserting only the interesting flags left the rest free: mutation
        turned `-v` into `-V` and `--entrypoint` into `--ENTRYPOINT` with nothing failing, and
        either produces a container that does not start."""
        argv, _ = self._invocations(monkeypatch, "docker")[0]
        assert argv == [
            "docker", "run", "--rm", "--userns=host", "--user", "0:0",
            "-v", "thevol:/home/harnessed/.claude", "--entrypoint", "chown", "img",
            "-R", f"{self.OWNER_UID}:{self.OWNER_GID}", "/home/harnessed/.claude",
        ]

    def test_the_volume_is_mounted_where_it_will_actually_live(self, monkeypatch):
        """NOT at a scratch path like /mnt, and this is the ordering the whole helper turns on.

        Docker performs copy-up when the container STARTS, seeding an empty volume from the image's
        copy of the mount point -- and it sets the volume root to that directory's owner, uid 1000.
        A chown done at /mnt is therefore undone the moment the volume is mounted where it belongs.
        The agent at uid 1001 could still create files inside (group 0, mode 2775) but not set
        timestamps ON the directory, since utimes() needs ownership:

            cp: preserving times for '/home/harnessed/.claude/.': Operation not permitted

        Mounting at the real path puts copy-up and the chown in one container, in that order.
        """
        argv, _ = self._invocations(monkeypatch, "docker")[0]
        mount = argv[argv.index("-v") + 1]
        assert mount.endswith("/home/harnessed/.claude"), f"the volume must be mounted where it lives: {argv}"
        assert "/mnt" not in argv, (
            f"a scratch mount path puts the chown before copy-up, which then overwrites it: {argv}"
        )
        assert argv[-1] == "/home/harnessed/.claude", argv

    # 4242:4243 -- a value no developer box and no GitHub runner has. Since #457 the docker owner
    # is the INVOKING uid, so an assertion written against `paths.CONTAINER_UID` is only true where
    # the invoker happens to be uid 1000. It passed on the author's box and went red on the runner
    # (uid 1001) the first time CI saw the #457 commits. That is the same uid-1000 coincidence
    # `conftest._pin_container_runtime` documents, in the branch that exists to remove it.
    OWNER_UID = 4242
    # 0, not a pinned distinctive number: the docker group IS 0 by design (arbitrary-uid contract),
    # so pinning anything else here would assert a behaviour the code deliberately does not have.
    OWNER_GID = 0

    def _pin_invoker(self, monkeypatch):
        monkeypatch.setattr(paths.os, "getuid", lambda: self.OWNER_UID)
        monkeypatch.setattr(paths.os, "getgid", lambda: self.OWNER_GID)

    def _calls(self, monkeypatch, rt: str) -> list[list[str]]:
        self._pin_invoker(monkeypatch)
        calls: list[list[str]] = []
        monkeypatch.setattr(volumes, "_run", _recorder(calls))
        volumes._chown_volume_for_docker(rt, "thevol", "theimage", "/home/harnessed/.claude")
        return calls

    def test_docker_chowns_the_volume_to_the_invoking_ids(self, monkeypatch):
        """Renamed from `..._to_the_image_uid`, because since #457 that is no longer what happens:
        docker gets `--user <invoker>`, so the volume must be owned by the INVOKER. The old name
        described the podman rule, and the old assertion only held where the invoker was uid 1000."""
        calls = self._calls(monkeypatch, "docker")
        assert len(calls) == 1, f"expected exactly one chown container: {calls}"
        cmd = calls[0]
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "--user" in cmd and "0:0" in cmd, "the chown must run as root; uid 1000 cannot"
        assert "thevol:/home/harnessed/.claude" in cmd
        # The chown moved INSIDE an `sh -c` when it became sentinel-gated (PR #461 review): the
        # gate and the chown have to be one container, so the ids and `-R` are now script text
        # rather than argv elements. Same three properties, read where they now live.
        assert "chown" in cmd, f"the chown entrypoint is what does the work: {cmd}"
        assert f"{self.OWNER_UID}:{self.OWNER_GID}" in cmd
        assert "-R" in cmd, "the volume may already hold copied-up content"
        # It must carry the mapping too, or the chown lands in a different namespace than the
        # agent and writes an ownership the agent still cannot use.
        assert "--userns=host" in cmd

    def test_the_chown_writes_nothing_inside_the_volume(self, monkeypatch):
        """THE REGRESSION GUARD, and the reason this class exists in its current shape.

        Docker seeds a named volume from the image's copy of the mount point ONLY WHILE THE VOLUME
        IS EMPTY. An earlier version of this helper gated itself on a sentinel FILE written into
        the volume, to avoid re-walking the shared cache on every launch. That one byte suppressed
        copy-up: ~/.local came up empty instead of carrying the image's pnpm tree, and the launch
        died with `nohup: failed to run command 'hatago': No such file or directory`.

        Measured both ways -- an empty volume mounted at ~/.local yields `bin share state` with
        hatago on PATH; the same volume with a single file written first yields only that file.

        So: this container may CHANGE ownership and must CREATE nothing.
        """
        argv, _ = self._invocations(monkeypatch, "docker")[0]
        joined = " ".join(argv)
        for writer in ("touch", "mkdir", "tee", ">"):
            assert writer not in joined, (
                f"{writer!r} appears in the chown container; anything written into the volume "
                f"stops docker seeding it from the image: {argv}"
            )
        assert argv[argv.index("--entrypoint") + 1] == "chown", argv

    def test_a_volume_that_already_exists_is_not_chowned_again(self, monkeypatch, tmp_path):
        """The cost the PR #461 review objected to. `_ensure_stack_volumes` runs on every build AND
        every FIRST_START launch, and `harnessed-dl-cache` is shared by every stack and never
        pruned (volume-gc's `role == "shared"` branch), so an unconditional `chown -R` walks an
        unbounded tree every time. The gate is EXISTENCE, asked before `volume create` -- state
        kept outside the volume, where it cannot affect copy-up."""
        calls: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            # `volume inspect` succeeding is how "this volume already exists" is expressed.
            return _Recorded(0 if cmd[1:3] == ["volume", "inspect"] else 1)

        monkeypatch.setattr(volumes, "_run", fake_run)
        monkeypatch.setattr(volumes, "_merged_settings_text", lambda *a, **k: None)
        volumes._ensure_config_volume("docker", "s", "claude", tmp_path, "img")

        chowns = [c for c in calls if "chown" in c]
        assert not chowns, f"an existing volume must not be re-chowned: {chowns}"

    def test_a_volume_this_run_created_is_chowned(self, monkeypatch, tmp_path):
        """The other half: a brand-new volume is root-owned until something fixes it, so the gate
        must not turn into 'never chown'."""
        calls: list[list[str]] = []

        def fake_run(cmd, *a, **k):
            calls.append(list(cmd))
            return _Recorded(1)  # inspect fails -> the volume did not exist

        monkeypatch.setattr(volumes, "_run", fake_run)
        monkeypatch.setattr(volumes, "_merged_settings_text", lambda *a, **k: None)
        volumes._ensure_config_volume("docker", "s", "claude", tmp_path, "img")

        chowns = [c for c in calls if "chown" in c]
        assert len(chowns) == 1, f"a new volume must be chowned exactly once: {calls}"

    def test_the_config_volume_is_chowned_when_it_is_created(self, tmp_path, monkeypatch):
        """Through `_ensure_config_volume`, not by calling the helper directly.

        The helper being correct says nothing about it being CALLED, and the call is the half that
        was missing before phase 2. diff-cover flagged this exact line as unexecuted."""
        calls: list[list[str]] = []
        monkeypatch.setattr(volumes, "_run", _recorder(calls))
        monkeypatch.setattr(volumes, "_merged_settings_text", lambda *a, **k: None)

        volumes._ensure_config_volume("docker", "s", "claude", tmp_path, "img", fresh=True)

        chowns = [c for c in calls if any("chown" in part for part in c)]
        assert len(chowns) == 1, f"the config volume was not chowned: {calls}"
        # ...and it must happen AFTER `volume create`: chowning first would create the volume
        # implicitly with default ownership, which is the state being fixed.
        creates = [i for i, c in enumerate(calls) if c[1:3] == ["volume", "create"]]
        assert creates and calls.index(chowns[0]) > creates[0]

    def test_podman_is_left_alone(self, monkeypatch):
        """podman already did this. A second chown would state the rule in two places, and two
        statements of one rule can disagree."""
        assert self._calls(monkeypatch, "podman") == []


class TestTheAgentsOwnApiEndpointIsAllowlisted:
    """The egress firewall defaults to DROP and opens only recipe-declared `egress:` hosts.

    `ANTHROPIC_BASE_URL` comes from the user's `.env.schema`, which no recipe can see — so when a
    user points the agent at a gateway, the one host it cannot work without is the one host not
    allowlisted. `api.anthropic.com` IS baked in, which is why this is invisible on a default setup
    and total on a gateway setup, and why it presents as an auth failure: the request never arrives
    to be authenticated.

    Measured on a real docker container with `ANTHROPIC_BASE_URL=https://api.z.ai`: requests to
    api.z.ai timed out at the DROP policy while api.anthropic.com returned 404."""

    def test_a_repointed_base_url_is_allowlisted(self):
        hosts = launchenv.api_endpoint_egress_hosts({"ANTHROPIC_BASE_URL": "https://api.z.ai"})
        assert hosts == ["api.z.ai"], "the agent cannot reach its own API without this"

    def test_the_port_and_path_are_stripped(self):
        """The firewall script resolves NAMES to IPs; a host:port would not resolve."""
        hosts = launchenv.api_endpoint_egress_hosts(
            {"ANTHROPIC_BASE_URL": "https://gw.internal:8443/v1/messages"},
        )
        assert hosts == ["gw.internal"]

    def test_a_bare_host_with_no_scheme_still_yields_a_host(self):
        """`urlsplit` parses a scheme-less value as a PATH, so hostname is None. Dropping it there
        would silently reinstate the defect for anyone who omits https://."""
        assert launchenv.api_endpoint_egress_hosts({"ANTHROPIC_BASE_URL": "api.z.ai"}) == ["api.z.ai"]

    def test_the_bedrock_and_vertex_forms_count_too(self):
        hosts = launchenv.api_endpoint_egress_hosts({
            "ANTHROPIC_BEDROCK_BASE_URL": "https://bedrock.example",
            "ANTHROPIC_VERTEX_BASE_URL": "https://vertex.example",
        })
        assert sorted(hosts) == ["bedrock.example", "vertex.example"]

    def test_an_unset_or_empty_endpoint_adds_nothing(self):
        """The default setup must stay exactly as it was: api.anthropic.com is already baked in."""
        assert launchenv.api_endpoint_egress_hosts({}) == []
        assert launchenv.api_endpoint_egress_hosts({"ANTHROPIC_BASE_URL": "   "}) == []

    def test_duplicates_collapse(self):
        hosts = launchenv.api_endpoint_egress_hosts({
            "ANTHROPIC_BASE_URL": "https://gw.example/v1",
            "ANTHROPIC_VERTEX_BASE_URL": "https://gw.example/other",
        })
        assert hosts == ["gw.example"]


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
        # `container_user_args`, not a hand-written `--user`: this must run the argument PRODUCTION
        # emits, or it verifies a command nothing sends. The literal `CONTAINER_UID` it used to pass
        # is the pre-#457 rule, and against a bind mount owned by the invoker it is also just wrong
        # off a uid-1000 box -- it failed on the runner (uid 1001) with "Permission denied", which
        # is the very error #456/#457 exist to remove.
        proc = subprocess.run(
            ["docker", "run", "--rm", *paths.userns_args("docker"),
             *paths.container_user_args("docker"),
             "-v", f"{target}:/data:rw", "--entrypoint", "mkdir", self.IMAGE, "-p", "/data/dolt"],
            capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        # The INVOKER owns it. That is the whole point of the docker `--user` mapping.
        assert (target / "dolt").stat().st_uid == os.getuid()
