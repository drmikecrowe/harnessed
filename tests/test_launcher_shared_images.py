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
    """The claude image is an agent image on BOTH build paths, so both owe it its `--build-arg`s.

    Regression: this path built Dockerfile.harnessed-claude from a hardcoded pair list with no
    build args at all. That was invisible until the Dockerfile grew a guard refusing an empty
    CLAUDE_VERSION — then `harnessed build` (no stack) died on the guard while the per-stack path,
    which goes through `_build_agent_image`, stayed green.
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
    assert expected, "the claude agent declares no build_args — this test would assert nothing"
    claude = by_image[launcher._CLAUDE_IMAGE]
    # strict: the flags come in NAME/value pairs. An odd-length list is itself the bug, and a
    # lenient zip would drop the unpaired tail and quietly assert less than it claims to.
    for flag, value in zip(expected[::2], expected[1::2], strict=True):
        assert flag in claude and value in claude, f"missing --build-arg {value}"
    # The base is not an agent image; agent pins must not leak onto it.
    assert "--build-arg" not in by_image[launcher._BASE_IMAGE]
