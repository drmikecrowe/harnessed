"""Read-only questions about the container runtime: which runtime, and what exists right now.

Every function here is a PREDICATE or an identifier lookup — it inspects podman/docker and returns
a fact. None of them create, start, stop or remove anything; that orchestration stays in
launcher.py. They live together because several modules need to ask these questions, and a module
that imported them from launcher would invert the dependency the split depends on.
"""
from __future__ import annotations

import shutil
import subprocess

import typer

from .console import _err


def _runtime() -> str:
    """Return 'podman' or 'docker', whichever is on PATH (prefer podman)."""
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            return rt
    _err.print("[bold red]error:[/bold red] neither podman nor docker found on PATH")
    raise typer.Exit(1)


def _image_exists(rt: str, image: str) -> bool:
    return subprocess.run(
        [rt, "image", "inspect", image],
        capture_output=True,
    ).returncode == 0


def _container_running(rt: str, name: str) -> bool:
    result = subprocess.run(
        [rt, "container", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_exists(rt: str, name: str) -> bool:
    """True if a container named `name` exists in any state (running, exited, created)."""
    return subprocess.run(
        [rt, "container", "inspect", name], capture_output=True,
    ).returncode == 0


def _pod_exists(rt: str, pod: str) -> bool:
    """True if a podman pod named `pod` exists in any state (created/running/exited)."""
    return subprocess.run([rt, "pod", "inspect", pod], capture_output=True).returncode == 0


def _stopped_leftover(rt: str, inst: str, pod: str) -> bool:
    """True if a prior (non-ephemeral) session left a stopped instance/pod that would block a fresh
    `pod create` with "name already in use". A *running* instance is re-attached, never torn down
    here — only genuinely stopped leftovers qualify."""
    if _container_running(rt, inst):
        return False
    return _container_exists(rt, inst) or (_rt_uses_pods(rt) and _pod_exists(rt, pod))


def _inspect_id(rt: str, kind: str, ref: str, fmt: str) -> str:
    r = subprocess.run([rt, kind, "inspect", "-f", fmt, ref], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _img_differs(current: str, used: str) -> bool:
    """True iff two image IDs are both known and differ (sha256: prefix normalized).

    Either side empty (image/container gone, inspect failed) → can't tell → not stale.
    """
    norm = lambda s: s.strip().removeprefix("sha256:")
    cur, prev = norm(current), norm(used)
    return bool(cur and prev and cur != prev)


def _container_stale(rt: str, name: str, image: str) -> bool:
    """True if the running container was created from a different image than current `image:latest`
    (i.e. the image was rebuilt since the container started — a re-attach would run the old build)."""
    return _img_differs(_inspect_id(rt, "image", image, "{{.Id}}"),
                        _inspect_id(rt, "container", name, "{{.Image}}"))


def _rt_uses_pods(rt: str) -> bool:
    return rt == "podman"
