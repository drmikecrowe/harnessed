"""Derive the command line that attaches to a running harness, and where it starts.

Each harness is entered differently — a plain shell, a session-restoring invocation, a
project-scoped one — and each needs a start directory resolved from the project path plus whatever
the agent declared. All of it is derived from the stack and the paths; nothing here spawns anything.
"""
from __future__ import annotations

import typer

from pathlib import Path
from typing import Optional

from . import emit
from . import paths
from .console import _err, _out
from .paths import CONTAINER_HOME

_CONTAINER_HOME_STR = str(CONTAINER_HOME)


# Attach command for each harness inside the container.
_HARNESS_ATTACH_CMD = {
    # `{strict}` is " --strict-mcp-config" by default and empty under --no-strict-mcp-config, which
    # lets claude also read its normal sources (notably the project's own .mcp.json).
    "claude": "claude --mcp-config '{mcp_cfg}'{strict}",
    # No `--profile`: that isolates auth/sessions/settings into a separate store, which would ignore
    # the bind-mounted ~/.omp/agent. We share the host's default omp profile (auth + usage + sessions).
    "omp": "omp",
    "opencode": "opencode",
    "antigravity": "agy",
    "codex": "codex",
}


def _omp_attach_cmd(start_dir: Path) -> str:
    """omp attach command, with the per-folder session dir pinned to the HOST's key.

    omp names a folder's session dir from the cwd *relative to $HOME* (host: `/home/u/Prog/x` under
    `$HOME=/home/u` → `~/.omp/agent/sessions/-Prog-x`). In the pod `$HOME` is /home/harnessed while
    the agent's cwd is the mirrored HOST path (/home/u/…) — outside the pod's home, so omp escapes
    the key (`--home-u-Prog-x--`) and writes to a folder the host never reads. `~/.omp/agent` is
    bind-mounted (see `_omp_agent_mount`), so the store is already shared; only the key diverged, and
    `/resume` in the pod reported "No sessions in current folder". Recompute the key against the HOST
    home and pin it with `--session-dir`, so host and pod resume each other's sessions.

    The dir is fixed at attach time: `cd`-ing elsewhere in the pod does not re-key omp's picker.
    """
    home = Path.home()
    if start_dir == home:
        return _HARNESS_ATTACH_CMD["omp"]  # omp auto-switches out of ~ anyway
    try:
        key = "-" + str(start_dir.relative_to(home)).replace("/", "-")
    except ValueError:
        key = str(start_dir).replace("/", "-")  # outside the host home: omp keeps the full path
    return f"omp --session-dir '{_CONTAINER_HOME_STR}/.omp/agent/sessions/{key}'"


def _opencode_attach_cmd(prof: Path, stack_name: str) -> str:
    """opencode attach command, stack-conditional on a baked persona (bd main-rlw).

    When the stack shipped `instructions:`, `_merge_baked_opencode` wrote a merged opencode.json
    (defining a custom persona agent) into the profile — attach via `opencode --agent <name>` so
    the persona + rules-glob load. Otherwise the fixed `opencode` command (image config, no
    persona). The `<name>` must match `_merge_baked_opencode`'s, so both go through
    `emit.opencode_agent_name`."""
    if (prof / "opencode" / "opencode.json").is_file():
        return f"opencode --agent {emit.opencode_agent_name(stack_name)}"
    return _HARNESS_ATTACH_CMD["opencode"]


def _resolve_start_dir(project_path: Path, agent_start_folder: Optional[str]) -> Path:
    """Resolve the agent's working directory.

    Default: the project root. With --agent-start-folder, the named subfolder (relative to the
    project root, or absolute) — the project root is still mounted in full, so the agent can see the
    whole tree but opens in the chosen subfolder. Must exist and live under the project root (the
    only mounted project tree)."""
    if not agent_start_folder:
        return project_path
    start = Path(agent_start_folder)
    start = start if start.is_absolute() else project_path / start
    start = start.resolve()
    if not start.is_dir():
        _err.print(
            f"[bold red]error:[/bold red] --agent-start-folder not found (or not a directory): {start}"
        )
        raise typer.Exit(1)
    try:
        start.relative_to(project_path)
    except ValueError as err:
        _err.print(
            f"[bold red]error:[/bold red] --agent-start-folder must be inside the project "
            f"({project_path}): {start}"
        )
        raise typer.Exit(1) from err
    return start


def _resolve_mount_path(project_path: Path, mount_folder: Optional[str]) -> Path:
    """Resolve the folder path-mirrored into the container.

    Default: the project itself, UNLESS project_path sits in a bare + linked-worktree checkout
    (e.g. `harnessed/.bare` + `harnessed/main`), in which case the default auto-widens to the
    directory containing the bare repo — so sibling worktrees are visible without typing
    --mount-folder by hand. With --mount-folder, the named folder — which MUST contain the project —
    so any parent dir is exposed while the agent still starts in the project. Mirror of
    `_resolve_start_dir`'s containment check, inverted: there the start dir must be *under* the
    project; here the project must be *under* the mount.
    """
    if not mount_folder:
        auto = paths.bare_worktree_container(project_path)
        if auto is not None:
            _out.print(
                f"[blue][INFO][/blue] {project_path} is a linked worktree of a bare repo — "
                f"auto-widening the mount to {auto} so sibling worktrees are visible "
                "(pass --mount-folder to override)."
            )
            return auto
        return project_path
    mount_path = Path(mount_folder).resolve()
    if not mount_path.is_dir():
        _err.print(
            f"[bold red]error:[/bold red] --mount-folder not found (or not a directory): {mount_path}"
        )
        raise typer.Exit(1)
    try:
        project_path.relative_to(mount_path)
    except ValueError as err:
        _err.print(
            f"[bold red]error:[/bold red] --mount-folder must contain the project "
            f"({project_path}): {mount_path}"
        )
        raise typer.Exit(1) from err
    return mount_path
