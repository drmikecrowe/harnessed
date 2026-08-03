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
