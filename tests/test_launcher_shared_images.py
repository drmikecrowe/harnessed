"""Shared base/agent images are built at most once per process.

Every derived stack image is FROM the base and FROM its agent image, so `_build_stack` (re)builds
both before the derived one. With N stacks in a single `harnessed build`, that used to re-issue the
same `podman build` N times — cache-backed, but each one still tars up the whole build context.
"""

import pytest

from harnessed import launcher
from support import patch_all


@pytest.fixture
def podman(monkeypatch):
    """Record the `podman build -t <image>` targets, running no real podman."""
    targets: list[str] = []

    def fake_run(cmd, check=True, **kwargs):
        if len(cmd) > 2 and cmd[1] == "build":
            targets.append(cmd[cmd.index("-t") + 1])
        return None

    monkeypatch.setattr(launcher, "_SHARED_IMAGES_BUILT", set())
    patch_all(monkeypatch, "_run", fake_run)
    monkeypatch.setattr(launcher, "_ensure_extra_tools", lambda: None)
    monkeypatch.setattr(launcher, "_corp_proxy_ca_secret_args", lambda: [])
    patch_all(monkeypatch, "_image_exists", lambda rt, image: True)
    return targets


def test_base_image_built_once_per_process(podman):
    launcher._build_base_image("podman")
    launcher._build_base_image("podman")
    launcher._build_base_image("podman")
    assert podman == [launcher._BASE_IMAGE]


def test_agent_image_built_once_per_harness(podman):
    launcher._build_agent_image("podman", "claude")
    launcher._build_agent_image("podman", "claude")
    launcher._build_agent_image("podman", "omp")
    assert podman == ["harnessed-claude:latest", "harnessed-omp:latest"]


def test_build_images_cmd_registers_what_it_built(podman, monkeypatch):
    """`harnessed build` runs _build_images_cmd first; the per-stack rebuild must not repeat it."""
    patch_all(monkeypatch, "_image_exists", lambda rt, image: False)  # take the build branch
    launcher._build_images_cmd("podman")
    assert podman == [launcher._BASE_IMAGE, launcher._CLAUDE_IMAGE]

    launcher._build_base_image("podman")
    launcher._build_agent_image("podman", "claude")
    assert podman == [launcher._BASE_IMAGE, launcher._CLAUDE_IMAGE]


def test_build_images_cmd_passes_the_agent_pins_the_dockerfile_demands(monkeypatch):
    """The claude image is an agent image on BOTH build paths, so both owe it exactly the
    `--build-arg`s its manifest declares — and since the 2026-09-23 concession that is NONE:
    claude tracks the vendor channel (catalog/agents/claude/agent.yaml), and a leaked
    `--build-arg CLAUDE_VERSION=…` would name an ARG the Dockerfile no longer declares.

    Regression history, kept because the boundary is the point: this path once built
    Dockerfile.harnessed-claude from a hardcoded pair list with no build args at all, invisible
    until the then-guard refusing an empty CLAUDE_VERSION made `harnessed build` die while the
    per-stack path stayed green. The pin is gone; the argv boundary assertion stays.
    """
    from harnessed.schema import load_agent

    builds: list[list[str]] = []

    def fake_run(cmd, check=True, **kwargs):
        if len(cmd) > 2 and cmd[1] == "build":
            builds.append(list(cmd))
        return None

    monkeypatch.setattr(launcher, "_SHARED_IMAGES_BUILT", set())
    patch_all(monkeypatch, "_run", fake_run)
    monkeypatch.setattr(launcher, "_ensure_extra_tools", lambda: None)
    monkeypatch.setattr(launcher, "_corp_proxy_ca_secret_args", lambda: [])
    patch_all(monkeypatch, "_image_exists", lambda rt, image: False)

    launcher._build_images_cmd("podman")

    by_image = {cmd[cmd.index("-t") + 1]: cmd for cmd in builds}
    expected = launcher._agent_build_arg_flags(load_agent("claude"))
    claude = by_image[launcher._CLAUDE_IMAGE]
    assert expected == [], "claude concedes its version — no build-arg may reach this path"
    assert "--build-arg" not in claude, "a conceded pin leaked onto the shared build path"
    # The base is not an agent image; agent pins must not leak onto it either.
    assert "--build-arg" not in by_image[launcher._BASE_IMAGE]


@pytest.mark.parametrize("harness", ["codex", "omp"])
def test_build_agent_image_passes_the_declared_pins_to_podman(monkeypatch, harness):
    """The OTHER build path, asserted at the same argv boundary. Raised by CodeRabbit on PR #364.

    The test above covers `_build_images_cmd`; the tests at the top of this file call
    `_build_agent_image` but only record its `-t` target, so nothing asserted that THIS path carries
    the pins. That asymmetry is not hypothetical — it is exactly the shape of the defect the test
    above documents, where one path had the flags and the other silently did not, and the guard in
    the Dockerfile was what eventually exposed it.

    Parametrised over every agent that declares `build_args` (claude dropped 2026-09-23: it
    concedes its version now and is covered by the no-build-arg test below), so a sixth agent
    with a pin is covered the day it lands rather than the day someone remembers.
    """
    from harnessed.schema import load_agent

    builds: list[list[str]] = []

    def fake_run(cmd, check=True, **kwargs):
        if len(cmd) > 2 and cmd[1] == "build":
            builds.append(list(cmd))
        return None

    monkeypatch.setattr(launcher, "_SHARED_IMAGES_BUILT", set())
    patch_all(monkeypatch, "_run", fake_run)
    monkeypatch.setattr(launcher, "_ensure_extra_tools", lambda: None)
    monkeypatch.setattr(launcher, "_corp_proxy_ca_secret_args", lambda: [])
    patch_all(monkeypatch, "_image_exists", lambda rt, image: True)   # base present: build the agent only

    launcher._build_agent_image("podman", harness)

    assert len(builds) == 1, f"expected one build, got {len(builds)}"
    cmd = builds[0]
    agent = load_agent(harness)
    expected = launcher._agent_build_arg_flags(agent)
    assert expected, f"{harness} declares no build_args — this parametrisation would assert nothing"
    for flag, value in zip(expected[::2], expected[1::2], strict=True):
        assert flag in cmd and value in cmd, f"{harness}: missing --build-arg {value}"
    # The VALUE, not just the name: `--build-arg NAME={'value': '1.2.3'}` is the mapping-form
    # mistake `_agent_build_arg_flags` exists to prevent, and it would satisfy a name-only check.
    for name, value in agent.build_args.items():
        assert f"{name}={value}" in cmd, f"{harness}: {name} did not reach podman as NAME=value"


def test_an_unpinnable_agent_contributes_no_build_arg(monkeypatch):
    """antigravity declares `unpinnable:` and no `build_args`, so its build carries no pin flags.

    The complement of the test above: `unpinnable:` is a declared NON-pin, and there is no value to
    pass. If one ever appeared on the command line it would mean the two namespaces had been merged,
    which is the confusion `_parse_agent_build_args` raises on.
    """
    from harnessed.schema import load_agent

    builds: list[list[str]] = []

    def fake_run(cmd, check=True, **kwargs):
        if len(cmd) > 2 and cmd[1] == "build":
            builds.append(list(cmd))
        return None

    monkeypatch.setattr(launcher, "_SHARED_IMAGES_BUILT", set())
    patch_all(monkeypatch, "_run", fake_run)
    monkeypatch.setattr(launcher, "_ensure_extra_tools", lambda: None)
    monkeypatch.setattr(launcher, "_corp_proxy_ca_secret_args", lambda: [])
    patch_all(monkeypatch, "_image_exists", lambda rt, image: True)

    launcher._build_agent_image("podman", "antigravity")

    agent = load_agent("antigravity")
    assert agent.unpinnable, "antigravity declares nothing unpinnable — this test asserts nothing"
    assert not agent.build_args
    assert "--build-arg" not in builds[0]
