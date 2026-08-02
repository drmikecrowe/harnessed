"""harnessed — Python launcher (Wave 1 migration).

Replaces the bash launcher (harnessed + lib/*.sh) with a Typer CLI that:
- reads config via schema.py (single parser — no sed-on-YAML)
- resolves paths via paths.py (single source of truth — fixes B6)
- writes profiles to $XDG_DATA_HOME/harnessed/profiles/ (fixes B5)
- dispatches harness commands from HARNESS_CONFIG_DIR (fixes C7)
- drives podman via subprocess / os.execvp (preserves TTY attach)
"""

from __future__ import annotations

import json
import fcntl
import hashlib
import os
import re
import shlex
import shutil
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path
from typing import Callable, Optional, TypeVar

import typer
from rich.console import Console
from rich.markup import escape
from ruamel.yaml import YAML

from . import __version__
from . import aoe
from . import dynstack
from . import emit
from . import paths
from . import persist
from . import staleness
from .paths import CONTAINER_HOME, instance_name, is_built, profile_dir, project_relpath
from .persist_gc import _fmt_size
from .assemble import assemble, compute_recipe_hash, _merge_servers, _resolve_service_servers
from .synclinks import CollisionError
from .schema import (
    HARNESS_CONFIG_DIR,
    Recipe,
    SchemaError,
    ServiceDef,
    Stack,
    load_agent,
    load_service,
    load_stack,
    load_stack_with_recipes,
    resolve_recipe_env,
)

app = typer.Typer(
    name="harnessed",
    help="Launch composable harness stacks (claude/omp/opencode/antigravity/codex + hatago MCP hub).",
    add_completion=False,
)

# Warnings printed during a launch are hidden the moment os.execvp hands the terminal over: Claude
# Code's fullscreen renderer draws on the ALTERNATE screen buffer, so everything harnessed printed
# is out of view for the whole session. Count warnings here rather than at the ~7 call sites, which
# use three different markers ("[WARNING]", "warning:", "WARNING") and whose exact output several
# tests assert on — this leaves every message byte-identical. _acknowledge_warnings() reads the
# counter just before the handoff.
_WARN_MARKER = re.compile(r"\bWARNING\b|\bwarning:", re.IGNORECASE)


class _WarnCountingConsole(Console):
    """A Console that remembers how many warnings it has printed."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.warnings = 0

    def print(self, *args, **kwargs) -> None:  # type: ignore[override]
        if args and isinstance(args[0], str) and _WARN_MARKER.search(args[0]):
            self.warnings += 1
        super().print(*args, **kwargs)


_out = _WarnCountingConsole()
_err = _WarnCountingConsole(stderr=True)

# --- shared image names (base; agent images come from catalog/agents/<h>/agent.yaml) ---
# hatago is no longer a separate image — it is baked into harnessed-base and runs in-container
# (hatago-consolidation), so there is no _HATAGO_IMAGE.
_BASE_IMAGE = "harnessed-base:latest"
_CLAUDE_IMAGE = "harnessed-claude:latest"
_CONTAINER_HOME_STR = str(CONTAINER_HOME)
# Where the emitted profile is mounted `:ro` while composing the agent-config volume
# (`_ensure_config_volume`). Scratch for that one throwaway container; never seen by the agent.
_CTR_PROFILE_DIR = "/tmp/harnessed-profile"

# Attach command for each harness inside the container.
_HARNESS_ATTACH_CMD = {
    "claude": "claude --mcp-config '{mcp_cfg}' --strict-mcp-config",
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
    except ValueError:
        _err.print(
            f"[bold red]error:[/bold red] --agent-start-folder must be inside the project "
            f"({project_path}): {start}"
        )
        raise typer.Exit(1)
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
    except ValueError:
        _err.print(
            f"[bold red]error:[/bold red] --mount-folder must contain the project "
            f"({project_path}): {mount_path}"
        )
        raise typer.Exit(1)
    return mount_path


def _inspect_id(rt: str, kind: str, ref: str, fmt: str) -> str:
    r = subprocess.run([rt, kind, "inspect", "-f", fmt, ref], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _img_differs(current: str, used: str) -> bool:
    """True iff two image IDs are both known and differ (sha256: prefix normalized).

    Either side empty (image/container gone, inspect failed) → can't tell → not stale.
    """
    norm = lambda s: s.strip().removeprefix("sha256:")  # noqa: E731
    cur, prev = norm(current), norm(used)
    return bool(cur and prev and cur != prev)


def _container_stale(rt: str, name: str, image: str) -> bool:
    """True if the running container was created from a different image than current `image:latest`
    (i.e. the image was rebuilt since the container started — a re-attach would run the old build)."""
    return _img_differs(_inspect_id(rt, "image", image, "{{.Id}}"),
                        _inspect_id(rt, "container", name, "{{.Image}}"))


def _rt_uses_pods(rt: str) -> bool:
    return rt == "podman"


def _harnessed_dir() -> Path:
    """harnessed's home (honors HARNESSED_DIR). Build context + catalog live under it.

    Never the CWD — see `paths.harnessed_home`. Resolves to the repo root in a source checkout and
    to the installed package dir in a wheel; both really contain `catalog/`.
    """
    return paths.harnessed_home()


def _stacks_dir() -> Path:
    """Repo catalog stacks dir — where `new` scaffolds. Enumeration goes through
    `paths.list_catalog_stacks` (unifies the user overlay), not this repo-only dir."""
    return _harnessed_dir() / "catalog" / "stacks"


def _agent_image(harness: str) -> str:
    """Resolve the agent's container image from catalog/agents/<harness>/agent.yaml (+ :latest)."""
    img = load_agent(harness).image
    return img if ":" in img else f"{img}:latest"


def _ensure_profile_dir(stack: str, harness: str) -> Path:
    """Ensure the XDG profile directory exists and return it."""
    p = profile_dir(stack, harness)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_local_catalog_links() -> None:
    """Ensure the user's overlay dirs exist; symlink them into `catalog-local/` in a source checkout.

    The overlay dirs are created unconditionally (they are how `find_in_catalog` sees user content).

    The symlinks are a DEV convenience — browsing/editing your overlay from inside the checkout — and
    they are deliberately parked in `catalog-local/`, NOT inside `catalog/` (paths.local_links_dir):

      * `catalog/` is shipped inside the wheel, and setuptools FOLLOWS symlinks, so a `<kind>.local`
        link inside it would package the user's private overlay into a distributable artifact.
      * They are keyed to harnessed's own checkout, never the CWD — running `harnessed build` from an
        unrelated project that happens to have a `catalog/` must not scribble symlinks into it, and a
        wheel install must not scribble them into site-packages.
    """
    user_catalog_root = paths.user_catalog()
    for kind in ("agents", "recipes", "services", "stacks"):
        (user_catalog_root / kind).mkdir(parents=True, exist_ok=True)

    checkout = paths.source_checkout()
    if checkout is None:
        return

    # MIGRATION: drop the pre-move `catalog/<kind>.local` links. Every checkout that has ever run
    # `harnessed build` has them, and they point into the user's private overlay from INSIDE the dir
    # we now ship — leave them and a `uv build` would package that overlay. Only ever unlink a
    # symlink, never real content.
    for kind in ("agents", "recipes", "services", "stacks"):
        stale = checkout / "catalog" / f"{kind}.local"
        if stale.is_symlink():
            stale.unlink()

    links_dir = paths.local_links_dir(checkout)
    links_dir.mkdir(parents=True, exist_ok=True)

    for kind in ("agents", "recipes", "services", "stacks"):
        target = links_dir / kind
        dest = user_catalog_root / kind
        if target.is_symlink():
            if target.resolve() == dest.resolve():
                continue  # already correct — no-op
            _err.print(
                f"[bold red]error:[/bold red] {target} is a symlink pointing at the wrong destination "
                f"(expected -> {dest}). Remove it manually to proceed."
            )
            raise typer.Exit(1)
        elif target.exists():
            _err.print(
                f"[bold red]error:[/bold red] {target} already exists and is not a symlink. "
                f"Remove it manually to proceed."
            )
            raise typer.Exit(1)
        else:
            target.symlink_to(dest)


def _ensure_docs_wiki_clone() -> None:
    """Bootstrap docs/ as an unpinned live clone of the repo's GitHub wiki, when missing.

    docs/ is a plain git clone (not a submodule) of <origin>.wiki.git -- no pinned
    commit, no pointer-bump PRs; pull it yourself with `git -C docs pull`. Only runs
    inside the harnessed SOURCE CHECKOUT; leaves an existing docs/ alone.

    Keyed to harnessed's own checkout, never the CWD: keyed to the CWD this would read an unrelated
    project's `origin` and clone THAT repo's wiki into ITS docs/ merely because it happened to have
    a `catalog/` dir — and would be meaningless in a wheel install.
    """
    checkout = paths.source_checkout()
    if checkout is None:
        return
    docs_dir = checkout / "docs"
    if docs_dir.exists():
        return
    try:
        origin_url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=checkout, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return
    wiki_url = re.sub(r"\.git$", "", origin_url) + ".wiki.git"
    try:
        _run(["git", "clone", wiki_url, str(docs_dir)])
    except subprocess.CalledProcessError:
        _err.print(f"[yellow]warning:[/yellow] could not clone docs wiki ({wiki_url}); docs/ left missing")


# --- parallel build logging -----------------------------------------------------------------
# When several stacks build concurrently their podman output interleaves into mush, so each build
# runs under a TAG — a (label, colour) pair set by the worker thread. `_run` and `_say` prefix every
# line with it, which is what makes N concurrent build logs readable in one terminal. Unset (the
# default) means a serial build: output streams through untouched, exactly as before.
_BUILD_TAG: ContextVar[tuple[str, str] | None] = ContextVar("_BUILD_TAG", default=None)

# Distinct, readable on both light and dark terminals. Cycled, so >8 concurrent builds reuse colours
# (the label still disambiguates).
_TAG_COLORS = (
    "cyan", "magenta", "green", "yellow",
    "bright_blue", "bright_magenta", "bright_cyan", "bright_green",
)

# Concurrent stack builds on a bare `harnessed build`. Deliberately NOT cpu_count: a stack build is
# mostly a podman build, and podman serializes chunks of its image store (layer commit / metadata),
# so the curve flattens fast — and each derived image is multi-GB, so N concurrent builds means N
# concurrent multi-GB writes. Half the cores, capped at 4, keeps the machine usable and still lands
# most of the win. Override with -j.
_DEFAULT_JOBS = max(1, min(4, (os.cpu_count() or 2) // 2))


def _say(msg: str) -> None:
    """Print a build message, prefixed with the current build's tag when one is set.

    highlight=False on the tagged path: rich's auto-highlighter styles things that merely LOOK like
    code, and it reads a tag like `mystack(omp)` as a function call — splitting it into differently
    styled fragments mid-word. It does the same to podman's build output (paths, numbers, brackets).
    A build log should come out the way podman wrote it.
    """
    tag = _BUILD_TAG.get()
    if tag is None:
        _out.print(msg)
        return
    label, color = tag
    _out.print(f"[{color}]{label:>34}[/{color}] [dim]│[/dim] {msg}", highlight=False)


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    tag = _BUILD_TAG.get()
    # Only the plain streaming case can be tagged: a caller that captures output (capture_output /
    # explicit stdout=) wants the bytes back, not printed, so leave those exactly as they were.
    streamable = tag is not None and not kwargs.get("capture_output") and "stdout" not in kwargs
    if streamable:
        return _run_tagged(cmd, check=check, **kwargs)
    try:
        return subprocess.run(cmd, check=check, **kwargs)
    except subprocess.CalledProcessError as exc:
        # Captured output is otherwise swallowed — surface it so failures read as an error,
        # not a bare traceback (e.g. "name already in use: pod already exists").
        for label, stream in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            text = stream.decode(errors="replace") if isinstance(stream, (bytes, bytearray)) else (stream or "")
            if text.strip():
                _err.print(f"[bold red]{label}:[/bold red] {text.strip()}")
        raise


def _run_tagged(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run `cmd`, printing each output line prefixed with the current build tag.

    stderr is folded into stdout so a build's diagnostics stay in ITS lane rather than racing to the
    terminal unprefixed. rich's Console holds an internal lock, so concurrent workers never tear a
    line. Output is `escape`d: podman prints things like `[1/2] STEP` that rich would otherwise eat
    as markup.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1, **kwargs,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _say(escape(line.rstrip()))
    returncode = proc.wait()
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)
    return subprocess.CompletedProcess(cmd, returncode)


def _catalog_base(rt_path: str) -> Path:
    return _harnessed_dir() / "catalog" / "base" / rt_path


def _ensure_extra_tools() -> None:
    """Seed the USER-owned extra-tools list from the shipped default when it is absent.

    Source of truth is `~/.config/harnessed/extra-tools.txt` (paths.extra_tools_path). Seeding it from
    `catalog/base/extra-tools.default.txt` (migrating a pre-move repo-root `extra-tools.txt` if one is
    still lying around) means a fresh clone, git worktree, or wheel install builds with no hand-copying.

    It is STAGED INTO THE BUILD CONTEXT — never back into `catalog/` — by `_staged_build_context`.
    """
    user_file = paths.extra_tools_path()
    if user_file.exists():
        return
    legacy = _harnessed_dir() / "extra-tools.txt"  # pre-move repo-root location
    seed = legacy if legacy.exists() else _catalog_base("extra-tools.default.txt")
    if seed.exists():
        user_file.parent.mkdir(parents=True, exist_ok=True)
        user_file.write_text(seed.read_text())


@contextmanager
def _staged_build_context() -> Generator[str]:
    """A throwaway podman build context: a copy of harnessed's `catalog/` + the resolved extra-tools.

    Every harnessed image build (base, agent, derived stack) uses this instead of building straight
    from `harnessed_home()`, because home is not a scratch dir:

      * In a WHEEL install home is `site-packages/harnessed` — staging `catalog/base/extra-tools.txt`
        there would write the user's host config INTO the installed package, and would fail outright
        on a read-only install.
      * In a CHECKOUT home is the repo root, so podman's context would be the ENTIRE repo — `.git`,
        `.venv`, `web/`, `node_modules` — shipped to the daemon on every build.

    `catalog/` sits at the context root either way, so the Dockerfiles' context-relative
    `COPY catalog/base/...` and `COPY catalog/recipes/<name>/...` paths are unchanged. Same pattern
    the service build already uses (see `_build_service_image`). Layer cache is unaffected: podman
    keys COPY layers on file CONTENT, not on the context's path.
    """
    home = _harnessed_dir()
    _ensure_extra_tools()
    with tempfile.TemporaryDirectory(prefix="harnessed-build-ctx-") as ctx:
        ctx_path = Path(ctx)
        shutil.copytree(
            home / "catalog",
            ctx_path / "catalog",
            symlinks=True,  # never FOLLOW a stray symlink out of the catalog into host content
            ignore=shutil.ignore_patterns("*.local"),
        )
        user_file = paths.extra_tools_path()
        if user_file.exists():
            (ctx_path / "catalog" / "base" / "extra-tools.txt").write_text(user_file.read_text())
        yield str(ctx_path)


def _corp_proxy_ca_secret_args() -> list[str]:
    """Return --secret args for the corporate proxy CA when present; empty list otherwise.

    The cert lives at $XDG_CONFIG_HOME/harnessed/corp-proxy-ca.crt (user-owned, never in the repo).
    Dockerfile.harnessed-base receives it via RUN --mount=type=secret so it is never baked into
    image history and nothing needs to be staged into the build context.
    """
    from .paths import corp_proxy_ca_path

    cert = corp_proxy_ca_path()
    if not cert.is_file():
        return []
    return ["--secret", f"id=corp_proxy_ca,src={cert}"]


def _corp_proxy_ca_mount_args() -> list[str]:
    """Return bind-mount args for the corporate proxy CA when present; empty list otherwise.

    Mounts the cert read-only at /run/corp-proxy-ca.crt inside the container. After the container
    starts, call _install_corp_proxy_ca_in_container() to register it with the system trust store.
    """
    from .paths import corp_proxy_ca_path

    cert = corp_proxy_ca_path()
    if not cert.is_file():
        return []
    return ["-v", f"{cert}:/run/corp-proxy-ca.crt:ro"]


def _install_corp_proxy_ca_in_container(rt: str, container: str, *, best_effort: bool = False) -> None:
    """Install the mounted corp CA into the container's system trust store.

    Requires _corp_proxy_ca_mount_args() to have mounted the cert at /run/corp-proxy-ca.crt.
    Execs as root so update-ca-certificates can write to /usr/local/share/ca-certificates/.
    best_effort=True swallows failures (use for service containers whose base image may not have
    the ca-certificates package); False (default) raises on failure.
    """
    from .paths import corp_proxy_ca_path

    if not corp_proxy_ca_path().is_file():
        return
    cmd = [
        rt, "exec", "--user", "root", container, "bash", "-c",
        "cp /run/corp-proxy-ca.crt /usr/local/share/ca-certificates/corp-proxy-ca.crt"
        " && update-ca-certificates",
    ]
    if best_effort:
        subprocess.run(cmd, capture_output=True)
    else:
        _run(cmd, capture_output=True)


# CA block injected into service Dockerfiles that don't already declare the secret mount.
_CORP_CA_DOCKERFILE_BLOCK = """\

# Corporate proxy CA: injected as a build secret when present at
# $XDG_CONFIG_HOME/harnessed/corp-proxy-ca.crt. required=false → no-op when absent.
RUN --mount=type=secret,id=corp_proxy_ca,dst=/tmp/corp-proxy-ca.crt,required=false \\
    if [ -s /tmp/corp-proxy-ca.crt ]; then \\
        cp /tmp/corp-proxy-ca.crt /usr/local/share/ca-certificates/corp-proxy-ca.crt && \\
        update-ca-certificates; \\
    fi
"""


def _service_dockerfile_with_ca(dockerfile: Path) -> Path | None:
    """Return a temp Dockerfile with the corp proxy CA trust block injected, or None if not needed.

    Injection happens right after the first complete RUN block (typically the apt-get install step
    that puts ca-certificates on PATH). This places the cert in the system trust store before any
    subsequent HTTPS downloads (curl/pip/pnpm/etc.). Returns None when:
    - No corp CA cert is configured (no-op path — standard builds unchanged).
    - The Dockerfile already contains the corp_proxy_ca secret mount.
    Caller must unlink the returned temp file.
    """
    import re
    import tempfile

    from .paths import corp_proxy_ca_path

    if not corp_proxy_ca_path().is_file():
        return None

    content = dockerfile.read_text()
    if "corp_proxy_ca" in content:
        return None  # already has the injection

    lines = content.splitlines(keepends=True)
    inject_after: int | None = None
    in_run = False

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if not in_run and re.match(r"\s*RUN\b", line, re.IGNORECASE):
            in_run = True
        if in_run and not stripped.endswith("\\"):
            inject_after = i
            break

    if inject_after is None:
        # No RUN found; fall back to injecting after the first FROM line
        for i, line in enumerate(lines):
            if re.match(r"\s*FROM\b", line, re.IGNORECASE):
                inject_after = i
                break

    if inject_after is None:
        return None

    modified = (
        "".join(lines[: inject_after + 1])
        + _CORP_CA_DOCKERFILE_BLOCK
        + "".join(lines[inject_after + 1 :])
    )

    fd, tmp = tempfile.mkstemp(suffix=".Dockerfile")
    try:
        os.write(fd, modified.encode())
    finally:
        os.close(fd)
    return Path(tmp)


# Images shared by several (stack, harness) pairs in one run — harnessed-base, the per-harness agent
# images, and any service image two stacks both reference. Without a guard a multi-pair build would
# re-issue the same `podman build` once per pair: cache-backed, but each invocation still tars up the
# whole build context, and under `--jobs > 1` two workers would race to build the same tag.
# Building each once per PROCESS is enough — nothing between two pairs in the same run can change
# the base/agent/service Dockerfile under us. The lock makes the check-then-build atomic.
_SHARED_IMAGES_BUILT: set[str] = set()
_SHARED_IMAGES_LOCK = threading.Lock()


def _build_shared_once(image: str, build: Callable[[], None]) -> None:
    """Build `image` exactly once per process, serializing concurrent callers.

    The lock is held across the BUILD, not just the set check. A claim-then-release would let a
    second worker sail past the guard while the first is still building — and go on to build its
    derived image FROM a base that does not exist yet. Shared images are prerequisites of everything
    else, so serializing them costs nothing worth having.
    """
    with _SHARED_IMAGES_LOCK:
        if image in _SHARED_IMAGES_BUILT:
            return
        build()
        _SHARED_IMAGES_BUILT.add(image)


def _build_images_cmd(rt: str, force: bool = False) -> None:
    """(Re)build the shared base + agent images (stack images are built lazily per stack)."""
    no_cache = os.environ.get("HARNESSED_PODMAN_NO_CACHE") == "true"
    cache_arg = ["--no-cache"] if no_cache else []
    secret_args = _corp_proxy_ca_secret_args()

    with _staged_build_context() as ctx:
        base = Path(ctx) / "catalog" / "base"
        pairs = [
            (_BASE_IMAGE, base / "Dockerfile.harnessed-base"),
            (_CLAUDE_IMAGE, base / "Dockerfile.harnessed-claude"),
        ]
        for image, dockerfile in pairs:
            if force or not _image_exists(rt, image):
                _out.print(f"[blue][INFO][/blue] Building {image} ...")
                _run([rt, "build", "-t", image, "-f", str(dockerfile), *cache_arg, *secret_args, ctx])
                with _SHARED_IMAGES_LOCK:
                    _SHARED_IMAGES_BUILT.add(image)
    _out.print("[green][SUCCESS][/green] harnessed images ready")


def _build_base_image(rt: str) -> None:
    """Force-(re)build the parameterised base so edits to Dockerfile.harnessed-base (the supply-chain
    scan script, extra-tools, scanner installs) propagate into every derived stack image (which is
    `FROM harnessed-base` — agent-last lineage). Layer-cached: a no-op when the base Dockerfile is
    unchanged, and skipped outright once this process has already built it."""
    def build() -> None:
        no_cache = os.environ.get("HARNESSED_PODMAN_NO_CACHE") == "true"
        cache_arg = ["--no-cache"] if no_cache else []
        secret_args = _corp_proxy_ca_secret_args()
        _say(f"[blue][INFO][/blue] Building {_BASE_IMAGE} ...")
        with _staged_build_context() as ctx:
            _run([
                rt,
                "build",
                "-t",
                _BASE_IMAGE,
                "-f",
                str(Path(ctx) / "catalog" / "base" / "Dockerfile.harnessed-base"),
                *cache_arg,
                *secret_args,
                ctx,
            ])

    _build_shared_once(_BASE_IMAGE, build)


def _build_agent_image(rt: str, harness: str) -> None:
    """(Re)build the agent image from its agent.yaml Dockerfile (podman layer cache decides whether
    anything actually rebuilds). Build args from agent.yaml are the single source of truth for pinned
    tool versions (e.g. OMP_VERSION) — the agent Dockerfile's ARG carries no default and is supplied
    here, so changing the pin here cache-busts exactly the version layer and onward.

    Built at most once per process: N stacks sharing a harness share one agent image.

    NOTE (agent-last): this standalone image is no longer the FROM parent of the derived stack
    images — emit inlines the agent's Dockerfile body as their LAST layers instead. It is still
    built because `harnessed run` falls back to it for a stack that has no derived image yet.
    """
    agent = load_agent(harness)
    image = _agent_image(harness)

    def build() -> None:
        if not _image_exists(rt, _BASE_IMAGE):
            _say("[yellow][WARNING][/yellow] harnessed-base not found. Building base first…")
            _build_images_cmd(rt, force=False)
        build_args: list[str] = []
        for key, val in agent.build_args.items():
            build_args += ["--build-arg", f"{key}={val}"]
        _say(f"[blue][INFO][/blue] Building {image} ...")
        with _staged_build_context() as ctx:
            # agent.dockerfile is home-relative (e.g. catalog/agents/omp/Dockerfile) — and the staged
            # context mirrors catalog/ at its root, so the same relative path resolves inside it.
            dockerfile = (
                Path(ctx) / agent.dockerfile if agent.dockerfile
                else Path(ctx) / "catalog" / "base" / f"Dockerfile.harnessed-{harness}"
            )
            _run([rt, "build", "-t", image, "-f", str(dockerfile), *build_args, ctx])

    _build_shared_once(image, build)


def _ensure_harness_image(rt: str, harness: str) -> None:
    """Build the agent image only if it is not present (launch-time lazy build)."""
    if not _image_exists(rt, _agent_image(harness)):
        _build_agent_image(rt, harness)


def _build_stack(rt: str, stack: str, harness: str, root: Path | None = None, *, strict: bool = True) -> None:
    """Assemble a stack IN-PROCESS (host-native, emit-only — no tool container) + build hatago.

    `root` is an optional single catalog root (tests); None resolves across the catalog roots
    (repo catalog/ + user ~/.config/harnessed/catalog, user wins).

    `strict` (default True — the authoring gate for `build`/`test`) rejects unknown recipe-manifest
    fields so a typo like `skkills:` fails loudly instead of silently dropping the capability.
    """
    stack_dir = (root / "stacks" / stack) if root else paths.find_in_catalog("stacks", stack)
    if not (stack_dir / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_dir}/stack.yaml)")
        raise typer.Exit(1)

    prof = _ensure_profile_dir(stack, harness)
    # assemble emits to <build-dir>/profiles/<stack>/<harness>; pass the dir that *contains* profiles/.
    build_root = paths.profiles_root().parent

    _say(f"[blue][INFO][/blue] Assembling stack '{stack}' for harness '{harness}' ...")
    try:
        result = assemble(root, stack, build_root, harness, strict=strict)
    except (SchemaError, CollisionError) as exc:
        # Clean rejection (raw npm/npx, floating pin, name collision, missing recipe/agent) — a
        # build that is *meant* to fail should read as a one-line error, not a Python traceback.
        _err.print(f"[bold red]error:[/bold red] assembling stack '{stack}' failed: {exc}")
        raise typer.Exit(1)

    # Always rebuild the parameterised base first: the derived image is `FROM harnessed-base` (which
    # also bakes hatago + the time server — hatago-consolidation), so a stale base (e.g. after
    # editing Dockerfile.harnessed-base) would silently propagate into every derived image.
    # Cache-backed — a no-op when the base Dockerfile is unchanged.
    _build_base_image(rt)

    # The standalone agent image is NO LONGER the derived image's FROM parent (agent-last lineage —
    # the agent's Dockerfile body is inlined as the derived image's last layers by
    # emit.write_derived_dockerfile). It is still built because `harnessed run` falls back to it for
    # a stack with no derived image yet. Once per process, cache-backed.
    _build_agent_image(rt, harness)

    # Always build the derived per-stack image: its FINAL layer is the supply-chain scan (BLD-02,
    # emit.write_derived_dockerfile), so every stack — not just ones shipping a recipe Dockerfile —
    # gets scanned. The scan runs over the agent's mise globals + recipe installs under ~/.claude.
    derived = _derived_image(stack, harness)
    dockerfile = prof / f"Dockerfile.harnessed-{stack}"
    recipe_hash = compute_recipe_hash(stack_dir / "stack.yaml", result.recipes)
    _say(f"[blue][INFO][/blue] Building derived image {derived} (incl. supply-chain scan) ...")
    with _staged_build_context() as ctx:
        _build_derived_image(rt, derived, dockerfile, ctx, recipe_hash)

    # The build's own scan layer is credential-free by design, so snyk + socket sit it out. Re-run the
    # scan here against the image we just built, this time with tokens resolved on the host — same
    # thing `harnessed rescan <image>` does. Advisory: it reports posture and never fails the build.
    # Skipped by `--no-security-scans`.
    # Populate the per-stack volumes BEFORE the scan and before the settings merge (bd
    # harnessed-8px.21.3/.21.4). `build` emits system layers only now, so this is where a stack
    # actually becomes complete — and it is the same call `launch` makes, which is what stops the
    # two paths from diverging. Fingerprint-gated, so a rebuild of an unchanged stack is a no-op.
    _, build_recipes = load_stack_with_recipes(root, stack)
    cfg_vol, tools_vol = _ensure_stack_volumes(rt, stack, harness, prof, derived, build_recipes)
    vol_args = [
        "--userns=keep-id",
        "-v", f"{cfg_vol}:{_CONTAINER_HOME_STR}/.claude",
        "-v", f"{tools_vol}:{_CONTAINER_HOME_STR}/.local",
    ]

    rescan_report = False
    if os.environ.get("HARNESSED_NO_SCANS") != "true":
        _say(f"[blue][INFO][/blue] Credentialed re-scan of {derived} (snyk + socket) ...")
        # Write ITS report to the profile: this is the only scan that runs snyk/socket, so its
        # findings must be the ones surfaced (bd harnessed-de7).
        scan_report = prof / "scan-report.json"
        # Remove any report from a PREVIOUS build first: an existing file would otherwise be taken
        # for this scan's output and treated as authoritative.
        scan_report.unlink(missing_ok=True)
        _scan_image_in_container(rt, derived, report_dest=scan_report, extra_args=vol_args)
        rescan_report = scan_report.is_file()
    # NOTE: the image-baked ~/.claude extraction that used to run here is GONE (bd harnessed-8px.7).
    # It existed because a Dockerfile RUN could deliver skills/commands into the image's ~/.claude,
    # which the profile bind-mount would then hide. Content delivery now goes through `install:`,
    # which writes into $HARNESSED_CONFIG_DIR in both modes, so there is nothing to extract — every
    # recipe Dockerfile was audited and none references ~/.claude at all. `validate_no_claude_writes`
    # keeps it that way LOUDLY, rather than this pass silently papering over a regression.

    # Replace the assemble-time settings.json FLOOR with the image's installer-written
    # settings.json (merged with harnessed's required grant). UNCONDITIONAL — a settings.json can
    # be baked by the agent BASE image, not only by a recipe Dockerfile, so this must NOT hide
    # behind the recipe-bake gate above.
    _merge_baked_settings(rt, derived, prof, harness, volume=cfg_vol)

    # opencode identity (bd main-rlw): when the stack ships `instructions:`, read the image-baked
    # opencode.json, add a custom persona agent + a rules-file glob, and write the merged config
    # into the profile (mounted over the image path by _build_mount_args). Gated on the harness so
    # non-opencode stacks skip the (opencode-only) image read entirely.
    if harness == "opencode":
        _merge_baked_opencode(rt, derived, prof, result.stack)

    # Surface the advisory supply-chain report. When the credentialed re-scan already wrote one,
    # that is authoritative — the image-baked report is credential-free and cannot see snyk/socket.
    _surface_scan_report(rt, derived, prof, keep_existing=rescan_report)

    # Build all service images referenced by this stack so they are ready before first run.
    # Layer-cached: a no-op when each service Dockerfile is unchanged.
    for svc_name in _service_refs(stack):
        _build_service_image(rt, svc_name)

    _say(f"[green][SUCCESS][/green] Stack '{stack}' ({harness}) built — profile: {prof}")


def _built_image_hash(rt: str, stack: str, harness: str) -> str | None:
    """The `harnessed.recipe-hash` label baked into stack's derived image, or None if the image
    doesn't exist yet or was built before this label existed."""
    result = subprocess.run(
        [
            rt, "inspect", "--format",
            '{{if .Config.Labels}}{{index .Config.Labels "harnessed.recipe-hash"}}{{end}}',
            _derived_image(stack, harness),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _declared_harnesses(stack: str, root: Path | None) -> list[str]:
    """The stack's `harnesses:` list, or [] when it declares none (or cannot be loaded)."""
    stack_dir = (root / "stacks" / stack) if root else paths.find_in_catalog("stacks", stack)
    if not (stack_dir / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_dir}/stack.yaml)")
        raise typer.Exit(1)
    try:
        return load_stack(stack_dir).harnesses
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] loading stack '{stack}' failed: {exc}")
        raise typer.Exit(1)


def _declared_pairs(root: Path | None) -> list[tuple[str, str]]:
    """Every (stack, harness) pair declared via a catalog stack's `harnesses:` list.

    A stack that declares no harnesses contributes nothing — bare `harnessed build` then treats it
    exactly as before (reconcile-only, driven by what has already been built). Declaring the key is
    the opt-in that makes a stack build from scratch on a bare `build`.
    """
    if root:
        stacks_dir = root / "stacks"
        names = sorted(
            d.name for d in stacks_dir.iterdir()
            if d.is_dir() and (d / "stack.yaml").is_file()
        ) if stacks_dir.is_dir() else []
    else:
        names = paths.list_catalog_stacks()

    pairs: list[tuple[str, str]] = []
    for name in names:
        stack_dir = (root / "stacks" / name) if root else paths.find_in_catalog("stacks", name)
        try:
            stack = load_stack(stack_dir)
        except SchemaError as exc:
            _err.print(f"[yellow]warn:[/yellow] skipping '{name}' ({exc})")
            continue
        pairs.extend((name, harness) for harness in stack.harnesses)
    return pairs


def _stale_pairs(rt: str, root: Path | None, *, strict: bool) -> list[tuple[str, str, str]]:
    """The (stack, harness, reason) triples a bare `harnessed build` must rebuild. A pair is in
    scope when it is either:

    * DECLARED — the stack's `harnesses:` list names it. These build even if no image exists yet,
      which is how a bare `build` provisions a freshly-authored stack from nothing.
    * PREVIOUSLY BUILT — a `harnessed=true`-labelled image exists for it. Scanning built images
      (rather than the whole catalog) keeps stacks that declare no `harnesses:` opt-in: they are
      only ever rebuilt once someone has named them explicitly at least once.

    It is stale when its recipe-closure hash no longer matches the `harnessed.recipe-hash` label
    baked into its image (or the image is absent). Fresh/unchanged pairs are dropped."""
    pairs: list[tuple[str, str]] = _declared_pairs(root)  # (stack, harness)

    result = subprocess.run(
        [rt, "images", "--filter", "label=harnessed=true", "--format", "{{.Repository}}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        # Parse image names of the form harnessed-<harness>-<stack>.
        # harness = the first hyphen-delimited segment after "harnessed-" that is a known harness
        # name; stack = the remainder after removing "harnessed-<harness>-".
        for repo in result.stdout.splitlines():
            repo = repo.strip()
            if not repo.startswith("harnessed-"):
                continue
            tail = repo[len("harnessed-"):]  # <harness>-<stack>
            for harness_candidate in HARNESS_CONFIG_DIR:
                prefix = harness_candidate + "-"
                if tail.startswith(prefix):
                    stack_name = tail[len(prefix):]
                    if stack_name and (stack_name, harness_candidate) not in pairs:
                        pairs.append((stack_name, harness_candidate))
                    break
    if not pairs:
        _out.print("[blue][INFO][/blue] No declared or previously-built stacks found to reconcile.")
        return []

    _out.print(f"[blue][INFO][/blue] Reconciling {len(pairs)} stack(s) against their recipe hash ...")
    stale: list[tuple[str, str, str]] = []
    for name, harness in pairs:
        stack_dir = (root / "stacks" / name) if root else paths.find_in_catalog("stacks", name)
        if not (stack_dir / "stack.yaml").is_file():
            _err.print(f"[yellow]warn:[/yellow] skipping '{name}' (stack.yaml not found in catalog)")
            continue
        try:
            _, recipes = load_stack_with_recipes(root, name, strict=strict)
            expected = compute_recipe_hash(stack_dir / "stack.yaml", recipes)
        except (SchemaError, CollisionError) as exc:
            _err.print(f"[yellow]warn:[/yellow] skipping '{name}' (failed to resolve recipes: {exc})")
            continue

        current = _built_image_hash(rt, name, harness)
        if current == expected:
            continue
        stale.append((name, harness, "no built image" if current is None else "recipe hash changed"))
    return stale


def _reconcile_stacks(rt: str, root: Path | None, *, strict: bool, jobs: int = 1) -> None:
    """Rebuild every stale (stack, harness) pair — the reconciliation half of a bare
    `harnessed build`. With `jobs > 1` the stale pairs build CONCURRENTLY.

    The shared images (harnessed-base, and one agent image per harness in scope) are built FIRST,
    serially, before any worker starts. They are prerequisites of every derived build, so racing on
    them would either duplicate the work or have a worker build FROM a base that isn't there yet.

    Each worker runs under a colour+label tag (_BUILD_TAG) so N interleaved podman logs stay
    readable. Failures do NOT cancel their siblings: every pair gets its shot, and the failures are
    reported together at the end — one broken stack shouldn't cost you the whole build.
    """
    stale = _stale_pairs(rt, root, strict=strict)
    if not stale:
        _out.print("[green][SUCCESS][/green] All stacks up to date.")
        return

    # Prerequisites, once, before the fan-out (see docstring).
    _build_base_image(rt)
    for harness in dict.fromkeys(h for _, h, _ in stale):
        _build_agent_image(rt, harness)

    jobs = max(1, min(jobs, len(stale)))
    for name, harness, reason in stale:
        _out.print(f"[blue][INFO][/blue] Rebuilding stale stack '{name}' ({harness}) ({reason}) ...")

    if jobs == 1:
        failures = [
            (name, harness, exc)
            for name, harness, _ in stale
            for exc in _build_stack_guarded(rt, name, harness, root, strict=strict, tag=None)
        ]
    else:
        _out.print(f"[blue][INFO][/blue] Building {len(stale)} stack(s) with {jobs} parallel job(s) ...")
        tags = {
            (name, harness): (f"{name}({harness})", color)
            for (name, harness, _), color in zip(stale, cycle(_TAG_COLORS))
        }
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(
                lambda triple: (
                    triple[0], triple[1],
                    _build_stack_guarded(
                        rt, triple[0], triple[1], root,
                        strict=strict, tag=tags[(triple[0], triple[1])],
                    ),
                ),
                stale,
            ))
        failures = [(name, harness, exc) for name, harness, excs in results for exc in excs]

    if failures:
        _err.print(f"\n[bold red]error:[/bold red] {len(failures)} stack(s) failed to build:")
        for name, harness, exc in failures:
            _err.print(f"  [bold red]✗[/bold red] {name} ({harness}): {exc}")
        raise typer.Exit(1)
    _out.print(f"[green][SUCCESS][/green] {len(stale)} stack(s) rebuilt.")


def _build_stack_guarded(
    rt: str, stack: str, harness: str, root: Path | None, *, strict: bool,
    tag: tuple[str, str] | None,
) -> list[Exception]:
    """Run _build_stack under `tag`, returning [] on success or [exc] on failure.

    Returning rather than raising is what lets one stack fail without killing the siblings that are
    already mid-build in other workers.
    """
    token = _BUILD_TAG.set(tag)
    try:
        _build_stack(rt, stack, harness, root, strict=strict)
        return []
    except Exception as exc:  # noqa: BLE001 — the failure is reported, not swallowed
        _say(f"[bold red]✗ build failed:[/bold red] {exc}")
        return [exc]
    finally:
        _BUILD_TAG.reset(token)


# Memo for `_varlock_resolve`, keyed on the resolved schema dir. Populated for the lifetime of one
# CLI process, which is exactly one launch.
#
# `varlock load` shells out and may authenticate against a secrets manager (1Password), so each call
# costs real latency. The same dir is resolved by several callers in a single launch:
# `_varlock_resolve_env_file` builds the --env-file set, then `_claude_oauth_token_configured` asks
# the same dirs whether a token is present (and `_resolve_launch_env` does both on the host path).
# Uncached that is up to 4 subprocesses per launch where 2 suffice.
#
# Caching is safe here BECAUSE the process is short-lived and one launch must see a CONSISTENT
# secret set anyway — resolving the same dir twice and acting on different answers would be a bug,
# not a feature. Tests that need fresh resolution monkeypatch `_varlock_resolve` wholesale (which
# bypasses this entirely) or call `_varlock_cache_clear()`.
_VARLOCK_CACHE: dict[Path, dict[str, str] | None] = {}


def _varlock_cache_clear() -> None:
    """Drop the `_varlock_resolve` memo. For tests that resolve the same dir across differing state."""
    _VARLOCK_CACHE.clear()


def _varlock_resolve(schema_dir: Path) -> dict[str, str] | None:
    """Run `varlock load --format json` in schema_dir and return the resolved `KEY -> value` map
    (values stringified, `None`s dropped). Returns None on varlock failure so a launch degrades
    gracefully rather than hard-failing.

    Uses `--format json` (not `--format env`) because the `env` format double-quotes every value
    (`KEY="val"`) and podman `--env-file` keeps those quotes literal; JSON gives raw values, which
    both consumers want — see `_varlock_resolve_env_file` (container) and `_resolve_launch_env`
    (host, where the values go straight into `os.environ` and never touch disk).

    Memoized per schema dir — see `_VARLOCK_CACHE`. The failure result (None) is cached too, so a
    broken varlock reports its error once per dir instead of once per caller.

    Assumes a `.env.schema` in schema_dir and `varlock` on PATH (checked by the caller).
    `OP_SERVICE_ACCOUNT_TOKEN` is included when already set in the host env (headless / CI path —
    service-account bearer auth, no desktop app required).
    """
    cache_key = schema_dir.resolve()
    if cache_key in _VARLOCK_CACHE:
        return _VARLOCK_CACHE[cache_key]

    result = subprocess.run(
        ["varlock", "load", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(schema_dir),
    )
    if result.returncode != 0:
        _err.print(
            f"[bold red]error:[/bold red] varlock load failed in {schema_dir} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
        _VARLOCK_CACHE[cache_key] = None
        return None

    try:
        resolved = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        _err.print(f"[bold red]error:[/bold red] varlock load returned invalid JSON: {e}")
        _VARLOCK_CACHE[cache_key] = None
        return None

    def _fmt(v: object) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    values = {k: _fmt(v) for k, v in resolved.items() if v is not None}
    op_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if op_token:
        values["OP_SERVICE_ACCOUNT_TOKEN"] = op_token
    _VARLOCK_CACHE[cache_key] = values
    return values


def _varlock_resolve_env_file(schema_dir: Path) -> Path | None:
    """Resolve schema_dir via varlock, writing a mode-0600 temp env-file of clean `KEY=VALUE` lines
    and returning its path. The caller MUST unlink the file after launch.

    Values are written verbatim: `_varlock_resolve` hands back raw (unquoted) values, and podman
    reads an env-file value to end-of-line — so no quoting or escaping is needed for the
    single-line values this carries (API keys/tokens). Returns None when resolution fails, so the
    launch degrades gracefully rather than hard-failing.
    """
    resolved = _varlock_resolve(schema_dir)
    if resolved is None:
        return None

    # podman env-file is KEY=VALUE with the value literal to end-of-line — no quoting needed.
    lines = "".join(f"{k}={v}\n" for k, v in resolved.items())

    fd, tmp = tempfile.mkstemp(prefix="harnessed-env.", suffix=".env")
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(lines)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return Path(tmp)


def _parse_plain_env_line(raw: str) -> tuple[str, str] | None:
    """Parse one dotenv line into (key, value), stripping an `export ` prefix and one pair of
    surrounding quotes. Returns None for blank/comment/`=`-less lines (nothing to set)."""
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):]
    key, _, val = stripped.partition("=")
    key, val = key.strip(), val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return key, val


def _plain_env_values(src: Path) -> dict[str, str]:
    """Read a plain `.env` into a `KEY -> value` map (same normalization as
    `_normalize_plain_env_file`, minus the temp file). Used by the host path, which sets the values
    in-process instead of handing podman an env-file."""
    return dict(
        pair for raw in src.read_text().splitlines()
        if (pair := _parse_plain_env_line(raw)) is not None
    )


def _normalize_plain_env_file(src: Path) -> Path:
    """Copy a plain `.env` into a mode-0600 temp env-file, stripping one pair of surrounding quotes
    from each value and any `export ` prefix. The caller MUST unlink the returned file after launch.

    podman `--env-file` keeps quotes literal (`KEY="v"` → the container sees `"v"`), so a user's
    dotenv-style `.env` — where quoting values is idiomatic — would otherwise land quoted inside the
    container. We rewrite `KEY="v"` / `KEY='v'` → `KEY=v`. Comment/blank lines pass through (podman
    ignores them); lines without `=` pass through unchanged.
    """
    out: list[str] = []
    for raw in src.read_text().splitlines():
        pair = _parse_plain_env_line(raw)
        if pair is None:
            out.append(raw)
            continue
        out.append(f"{pair[0]}={pair[1]}")

    fd, tmp = tempfile.mkstemp(prefix="harnessed-env.", suffix=".env")
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(out) + "\n")
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return Path(tmp)


def _resolve_launch_secrets(project_path: Path | None = None) -> tuple[list[Path], list[Path]]:
    """Resolve launch-time env-files, layered global → project (podman --env-file is last-wins,
    so project values override the global schema).

    Sources, in --env-file order:
      1. User-global ~/.config/harnessed/: `.env.schema` resolved via varlock (opt-in: needs the
         schema present and `varlock` on PATH), else a bare `.env` read literally. This is also the
         sole source of scanner tokens for `harnessed rescan` (_scan_image_in_container).
      2. Per-project env from project_path:
         - <project>/.env.schema present → `varlock load` in the project dir (varlock already
           cascades .env / .env.local overlays on top of the schema).
         - else <project>/.env present → normalized into a temp env-file (surrounding quotes /
           `export ` stripped so podman doesn't ingest them literally); no varlock, no resolution.

    Returns (env_files, temp_files): env_files is the ordered list to hand to --env-file;
    temp_files is the subset the caller MUST unlink after launch (resolved secrets must not
    linger on disk). Every env-file here is a generated temp — the user's own `.env` is copied,
    never handed to podman directly, so it is never modified or unlinked.
    """
    env_files: list[Path] = []
    temp_files: list[Path] = []
    have_varlock = bool(shutil.which("varlock"))

    global_dir = Path.home() / ".config" / "harnessed"
    global_schema = global_dir / ".env.schema"
    global_env = global_dir / ".env"
    if global_schema.is_file() and have_varlock:
        p = _varlock_resolve_env_file(global_dir)
        if p:
            env_files.append(p)
            temp_files.append(p)
    elif global_env.is_file():
        # Same precedence as the per-project pair below: a schema wins (varlock already cascades a
        # sibling .env), and a bare .env is read literally — no varlock, no op:// resolution.
        p = _normalize_plain_env_file(global_env)
        env_files.append(p)
        temp_files.append(p)

    if project_path is not None:
        proj_schema = project_path / ".env.schema"
        proj_env = project_path / ".env"
        if proj_schema.is_file() and have_varlock:
            p = _varlock_resolve_env_file(project_path)
            if p:
                env_files.append(p)
                temp_files.append(p)
        elif proj_env.is_file():
            p = _normalize_plain_env_file(proj_env)
            env_files.append(p)
            temp_files.append(p)

    return env_files, temp_files


def _resolve_launch_env(project_path: Path | None = None) -> dict[str, str]:
    """The host-native twin of `_resolve_launch_secrets`: the same sources and the same
    global → project precedence (project wins), returned as a `KEY -> value` map instead of a list
    of `--env-file` paths.

    Host mode has no pod to hand an env-file to — `os.environ` IS the box — so the values are set
    in-process by the caller and NEVER written to disk. That is strictly better than the container
    path's mode-0600 temp file, which is only there because podman needs a file.

    Returns {} when nothing is configured (no schema / no `varlock` on PATH / no `.env`), or when
    varlock fails — a launch must not hard-fail on secrets that may not be needed at all.
    """
    values: dict[str, str] = {}
    have_varlock = bool(shutil.which("varlock"))

    global_dir = Path.home() / ".config" / "harnessed"
    global_schema = global_dir / ".env.schema"
    global_env = global_dir / ".env"
    if global_schema.is_file() and have_varlock:
        resolved = _varlock_resolve(global_dir)
        if resolved:
            values.update(resolved)
    elif global_env.is_file():
        values.update(_plain_env_values(global_env))

    if project_path is not None:
        proj_schema = project_path / ".env.schema"
        proj_env = project_path / ".env"
        if proj_schema.is_file() and have_varlock:
            resolved = _varlock_resolve(project_path)
            if resolved:
                values.update(resolved)
        elif proj_env.is_file():
            values.update(_plain_env_values(proj_env))

    return values


def _build_derived_image(rt: str, derived: str, dockerfile: Path, ctx: str, recipe_hash: str) -> None:
    """Build the derived image. NEVER touches secrets or varlock — building must always succeed
    without credentials, so recipe install / skill / command / rule verification never depends on
    a secret resolving.

    There is no scan layer in the Dockerfile at all since bd harnessed-8px.21.5. There used to be
    one, declaring `RUN --mount=type=secret,id=snyk_token,required=false,...` so it ran fine with no
    token (snyk warn-skipped; osv-scanner + pip-audit still produced advisory output). It was
    removed because harnessed-8px.21.4 stopped installing anything into the image: the layer then
    scanned an image holding no stack content, and still printed "no high/critical advisories" off
    1 of 4 scanners. This function's no-secrets rule is unchanged and is now trivially true.

    A real, credentialed scan is a deliberately SEPARATE, explicit step — see `harnessed rescan`, which re-scans already
    -built images online — not something `harnessed build` does on your behalf. If you want
    SNYK_TOKEN available for that separate step, resolve it yourself (e.g. `varlock run -- harnessed
    rescan`) — this function does not, and should not, do that resolution implicitly.

    Labels the image with `harnessed=true` (so `rescan` can find it via `podman images --filter`)
    and `harnessed.recipe-hash=<recipe_hash>` (`compute_recipe_hash` — the stack's recipe-closure
    content hash, read back by `_built_image_hash`/`_reconcile_stacks` so a bare `harnessed build`
    knows which stacks are stale without a separate manifest file that could drift from the image).
    """
    _run([
        rt, "build", "-t", derived, "-f", str(dockerfile),
        "--label", "harnessed=true",
        "--label", f"harnessed.recipe-hash={recipe_hash}",
        ctx,
    ])


def _derived_image(stack: str, harness: str) -> str:
    return f"harnessed-{harness}-{stack}:latest"


_T = TypeVar("_T")


def _with_image_container(rt: str, image: str, fn: Callable[[str], _T]) -> _T | None:
    """Create ONE throwaway container from `image`, run `fn(cid)` (the `cp` extractions), and
    always `rm -f` it in a `finally`. Returns `fn`'s result, or None when the create produced no
    container id (defensive — mirrors the old per-site `if not cid: return`).

    Unifies the three post-build passes (extensions / settings / scan-report) onto a single
    create/rm instead of one apiece — same podman commands, one container.
    """
    cid = subprocess.run([rt, "create", image], capture_output=True, text=True).stdout.strip()
    if not cid:
        return None
    try:
        return fn(cid)
    finally:
        subprocess.run([rt, "rm", "-f", cid], capture_output=True)


def _merge_baked_settings(
    rt: str, image: str, prof: Path, harness: str = "", volume: str = "",
) -> None:
    """Replace the assemble-time settings.json FLOOR with the image's installer-written
    settings.json, surgically re-applying harnessed's required grant (emit.merge_settings).

    Why post-build: the installer-written ~/.claude/settings.json (hooks, permissions) only
    exists AFTER the image is built. Writing settings.json from scratch at assemble time and
    mounting it :ro (the old behaviour) masked whatever a recipe/base installer baked.

    Why UNCONDITIONAL (mirrors _surface_scan_report, not the recipe-bake gate): a settings.json
    can be baked by the agent BASE image, not only by a recipe Dockerfile — gating on recipe-bake
    would leave base-sourced settings stomped by the floor.

    Ordering invariant: build() runs assemble → build → here, so the floor stub
    (emit.write_settings_json) is always already on disk; we read it back as `required` (the
    single source of truth for harnessed's contribution) and overwrite it with the merge.

    Failure modes are split deliberately: a `podman cp` of an ABSENT file exits non-zero →
    baked_text stays None → floor kept silently; a baked file that is MALFORMED json →
    emit.read_baked_settings warns and the floor is kept. A recipe's bad settings.json never
    crashes the build.
    """
    stub = prof / "settings.json"
    required: dict = {}
    if stub.is_file():
        try:
            required = json.loads(stub.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            required = {}

    def _copy(cid: str) -> str | None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "settings.json"
            cp = subprocess.run(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.claude/settings.json", str(dest)],
                capture_output=True,
            )
            # cp of a missing file exits non-zero → return None (distinct from malformed).
            if cp.returncode == 0 and dest.is_file():
                return dest.read_text(encoding="utf-8")
        return None

    # create-fail (None) routes the same as a missing baked file: floor kept, nothing written.
    #
    # WHERE the installer-written settings.json lives moved with bd harnessed-8px.21.4: `install:`
    # no longer runs at build, so the file is in the config VOLUME, not in the image. Reading the
    # image here would find nothing, keep the floor, and silently drop every install-written key —
    # which is precisely harnessed-8px.19 ("ccstatusline statusLine gone on every restart"), a P1
    # this epic already fixed once. The image read stays as the fallback because the agent BASE
    # image is an independent bake surface (harnessed-8px.7's reason for keeping this function).
    baked_text = _volume_read(rt, volume, image, "settings.json") if volume else None
    if baked_text is None:
        baked_text = _with_image_container(rt, image, _copy)

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ settings:[/yellow] {msg}")

    baked = emit.read_baked_settings(baked_text, warn=_warn)
    if baked is None:
        return  # nothing usable baked; the floor stub already on disk is correct.
    merged = emit.merge_settings(baked, required, warn=_warn)
    stub.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    if harness:
        emit.warn_duplicate_hooks(merged, harness, warn=_warn)


def _deep_merge_json(base: object, overlay: object) -> object:
    """Recursively merge two JSON-like trees, preferring values from `overlay`.

    Dicts merge by key (recurse on matching keys). Non-dicts (including lists/scalars) are
    replaced wholesale by `overlay` so host-authored arrays preserve order exactly.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, val in overlay.items():
            if key in out:
                out[key] = _deep_merge_json(out[key], val)
            else:
                out[key] = val
        return out
    return overlay


def _merge_host_claude_settings(prof: Path, required: dict, harness: str = "") -> None:
    """Apply host ~/.claude/settings.json into the profile settings for launch-time parity.

    The profile's settings.json is the file mounted into the container. Merge host preferences into
    that file at launch, then re-apply harnessed-required grants/hooks so host customizations do not
    disable the MCP hub.
    """
    host = Path.home() / ".claude" / "settings.json"
    target = prof / "settings.json"
    if not (host.is_file() and target.is_file()):
        return

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ settings:[/yellow] {msg}")

    try:
        target_raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        target_raw = {}
    target_obj = target_raw if isinstance(target_raw, dict) else {}

    try:
        host_text = host.read_text(encoding="utf-8")
    except OSError:
        return
    host_obj = emit.read_baked_settings(host_text, warn=_warn)
    if host_obj is None:
        return

    # `statusLine.command` is a host-absolute path (e.g. /home/<hostuser>/.local/share/mise/shims/…)
    # that can never resolve inside the container (home is /home/harnessed). The ccstatusline recipe
    # bakes a container-correct statusLine into the profile; letting the host's version win here would
    # point Claude Code's status line at a nonexistent binary → it silently renders nothing. Drop the
    # host statusLine so the baked (or absent) profile value survives the merge.
    host_obj.pop("statusLine", None)

    merged = _deep_merge_json(target_obj, host_obj)
    if not isinstance(merged, dict):
        merged = host_obj
    final = emit.merge_settings(merged, required, warn=_warn)
    target.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    if harness:
        emit.warn_duplicate_hooks(final, harness, warn=_warn)


def _merge_baked_opencode(rt: str, image: str, prof: Path, stack: Stack) -> None:
    """Wire the stack's identity into opencode's config POST-BUILD (bd main-rlw).

    opencode reads its config from the image-baked ~/.config/opencode/opencode.json (the hatago
    MCP block), NOT from .claude/.mcp.json, and there is no profile-side opencode.json at assemble
    time — so, mirroring `_merge_baked_settings`, we read the baked config out of the built image,
    ADD a custom persona agent (from the stack's `instructions:`) + a rules-file glob, and write the
    merged config into the profile, where `_build_mount_args` mounts it over the image path.

    No-op unless there is identity text to add (nothing to add — the fixed `opencode` attach
    stands) or the baked config is absent/malformed (leave the image config untouched, warn on
    malformed)."""
    instructions = stack.instructions
    if not instructions:
        return
    agent_name = emit.opencode_agent_name(stack.name)
    if emit.write_opencode_persona(prof, instructions, agent_name) is None:
        return

    def _copy(cid: str) -> str | None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "opencode.json"
            cp = subprocess.run(
                [rt, "cp",
                 f"{cid}:{_CONTAINER_HOME_STR}/.config/opencode/opencode.json", str(dest)],
                capture_output=True,
            )
            if cp.returncode == 0 and dest.is_file():
                return dest.read_text(encoding="utf-8")
        return None

    baked_text = _with_image_container(rt, image, _copy)

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ opencode:[/yellow] {msg}")

    if baked_text is None:
        _warn("no baked opencode.json in image — persona/rules not wired")
        return
    try:
        baked = json.loads(baked_text)
    except json.JSONDecodeError:
        _warn("image opencode.json is not valid JSON — persona/rules not wired")
        return
    if not isinstance(baked, dict):
        _warn("image opencode.json is not a JSON object — persona/rules not wired")
        return

    rules_glob = f"{_CONTAINER_HOME_STR}/.claude/rules/*.md"
    persona_rel = f"./prompts/{agent_name}.md"
    merged = emit.merge_opencode_config(baked, agent_name, persona_rel, rules_glob)
    out = prof / "opencode" / "opencode.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def _surface_scan_report(
    rt: str, image: str, prof: Path, *, keep_existing: bool = False
) -> None:
    """Print a one-line advisory summary of the supply-chain report. Advisory — never gates.

    The report now comes from the CREDENTIALED post-build scan (`keep_existing=True`), which is the
    only pass that has snyk/socket tokens and the only one that mounts the stack volumes. The
    image-baked fallback below survives for images built before bd harnessed-8px.21.5, which carried
    a scan layer; images built since carry no report at all, and the fallback simply finds nothing.

    Saying so out loud matters: a build that scanned nothing must not look identical to a build that
    scanned everything and found nothing.
    """
    dest = prof / "scan-report.json"

    def _copy(cid: str) -> bool:
        subprocess.run(
            [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json", str(dest)],
            capture_output=True,
        )
        return True

    # `keep_existing` means the credentialed re-scan already wrote the authoritative report here.
    # Copying the image-baked one over it would REPLACE snyk/socket findings with a report that
    # structurally cannot contain them, which is what produced a green "no high/critical" verdict on
    # a build that had just reported 4 high (bd harnessed-de7).
    if keep_existing and dest.is_file():
        pass
    # create-fail (None) mirrors the old `if not cid: return` — leave any stale report untouched.
    elif not _with_image_container(rt, image, _copy):
        return
    if not dest.is_file():
        _out.print(
            "[yellow]note:[/yellow] no supply-chain report produced — nothing was scanned "
            "(set HARNESSED_NO_SCANS=false, or run `harnessed rescan <image>` with tokens)"
        )
        return
    try:
        totals = json.loads(dest.read_text())["totals"]
        crit, high = totals["critical"], totals["high"]
    except (json.JSONDecodeError, KeyError, OSError):
        return
    if crit or high:
        _out.print(f"[yellow]⚠ supply-chain (advisory):[/yellow] {crit} critical · {high} high "
                   f"— report: {dest}")
    else:
        _out.print(f"[green]✓ supply-chain:[/green] no high/critical advisories — report: {dest}")


# --- Pod / container lifecycle helpers -----------------------------------------

def _pod_teardown(rt: str, instance: str, pod: str) -> None:
    if _rt_uses_pods(rt):
        subprocess.run([rt, "pod", "rm", "-f", pod], capture_output=True)
    else:
        # Single flat container now — hatago runs in-container (hatago-consolidation), not a
        # separate `{instance}-hatago` member.
        subprocess.run([rt, "rm", "-f", instance], capture_output=True)


def _attach_marker(inst: str) -> Path:
    """Host-side marker whose mtime records when `inst` was last interactively attached."""
    return paths.xdg_state_home() / "harnessed" / "attached" / inst


def _touch_attach_marker(inst: str) -> None:
    m = _attach_marker(inst)
    m.parent.mkdir(parents=True, exist_ok=True)
    m.touch()


def _session_active(rt: str, inst: str) -> bool | None:
    """Whether an interactive harness session is attached: True/False, or None when undetermined.

    After the hatago-consolidation an idle instance is NOT just `sleep infinity`: it also runs the
    detached in-container hatago hub (a `node` process) and any stdio MCP children hatago spawned
    (`uvx mcp-server-time`, …). So the old "any non-sleep process = active" rule is wrong — it would
    never report idle and `harnessed prune` would never fire. Detect the session positively instead,
    by its controlling terminal: only the interactive attach (`exec -it … bash -l -c <harness>`) owns
    a real pts; every infra process (sleep, hatago, stdio children) runs with no tty.

    Returns None (not False) when `top` fails — a transient runtime hiccup must NOT be read as
    "confirmed idle", or `prune` would tear down a live attached session on a momentary error. The
    caller treats None conservatively (do not prune).

    NOTE (podman-gated): the exact idle/attached tty strings must be confirmed against live
    `<rt> top <inst> tty` output — this is the hatago-consolidation's main verification point.
    """
    result = subprocess.run([rt, "top", inst, "tty"], capture_output=True, text=True)
    if result.returncode != 0:
        return None  # couldn't determine — caller must not treat this as idle
    # Drop the header row; a process owning a real terminal (pts/N) is the attached session. Infra
    # processes report no tty ("?" on podman, "-"/"" elsewhere).
    ttys = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return any(t not in ("?", "-", "") for t in ttys)


def _apply_firewall(rt: str, instance: str, domains: list[str] | None = None) -> None:
    if os.environ.get("NO_FIREWALL", "false").lower() == "true":
        return
    # egress-firewall.sh is mounted at /usr/local/sbin/egress-firewall by _build_mount_args. Extra
    # domains (recipe-declared `egress:`) are appended to the script's allowlist — it takes them as
    # positional args and resolves each to its current IPs.
    subprocess.run([
        rt, "exec", instance, "bash", "/usr/local/sbin/egress-firewall",
        *(domains or []),
    ], capture_output=True)


def _wait_hatago(rt: str, instance: str, port: int | None = None, timeout: int = 30) -> bool:
    """Poll until the in-container hatago hub accepts connections on `port`.

    Returns True once the port is live, False on timeout. hatago starts asynchronously via the
    container entrypoint (harnessed-start), so the launch never sees a non-zero exit when hatago
    fails to bind — a missing binary, a bad config, or a crashed hub all look identical to a slow
    start. The caller must surface a False so we don't report `[SUCCESS]` over a dead MCP hub.
    """
    import time
    if port is None:
        port = paths.hatago_port()  # honor the HATAGO_PORT env override (single source: paths)
    _out.print(f"[blue][INFO][/blue] Waiting for hatago hub on :{port} ...")
    for _ in range(timeout):
        result = subprocess.run(
            [rt, "exec", instance, "bash", "-lc",
             f"timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/{port}' 2>/dev/null"],
            capture_output=True,
        )
        if result.returncode == 0:
            return True
        time.sleep(1)
    _err.print(
        f"[bold red]error:[/bold red] hatago hub never came up on :{port} after {timeout}s — "
        f"MCP tools will be unavailable. Inspect the hub log: {rt} exec {instance} cat /tmp/hatago.log"
    )
    return False


def _stack_config_volume(stack: str, harness: str) -> str:
    """Name of the per-stack agent-config volume (bd harnessed-8px.21.2).

    Per (stack, harness) because the composed content differs on both axes: the recipe closure
    picks the content, and the harness picks which profile tree is fanned into it. Two stacks
    sharing a volume would compose each other's skills.
    """
    return f"harnessed-cfg-{harness}-{stack}"


def _ensure_config_volume(
    rt: str, stack: str, harness: str, prof: Path, image: str, *, fresh: bool = False,
) -> str:
    """Create and compose the per-stack agent-config volume, returning its name.

    Replaces the per-subdir `:ro` bind-mounts that caused bd harnessed-8px.22, where a profile
    dir mounted over `~/.claude/skills` hid everything an `install.script` had delivered there —
    measured at 70 of 75 skills invisible, including all 34 `gsd-*`. Nothing is layered over
    anything now: ONE tree, composed in order.

    Two podman behaviours make this work, both verified against 6.0.1 in the bd harnessed-8px.21.1
    spike, and both easy to get wrong:

    1. COPY-UP. Mounting an EMPTY named volume over a path the image populated copies the image's
       content into the volume. That is what delivers the install-written `~/.claude` (and, for
       the `~/.local` volume this bead's sibling adds, the base image's own mise/snyk). It happens
       exactly ONCE — thereafter volume content wins and image updates are invisible, which is why
       the gate in harnessed-8px.21.3 must key on image identity and not only the recipe hash.

    2. USERNS. The pod is created `--userns=keep-id` and the agent inherits it as a pod member, so
       this populate step MUST use keep-id too. A volume first populated under the DEFAULT userns
       is unusable by the agent: uid 1000 inside reads the files as owner 999 and every write
       EACCESes. Verified in both directions.

    The profile is copied in on every launch, deliberately: that preserves today's semantics where
    the profile always wins over baked content. It is a local copy of small trees, not the
    expensive part — installs are what harnessed-8px.21.3 gates.
    """
    vol = _stack_config_volume(stack, harness)
    if fresh:
        # Composition is purely ADDITIVE — copy-up, then `cp -a` of the profile, then installs.
        # Nothing here removes, so without this a recipe dropped from the stack would leave its
        # skills and commands in the volume forever. `_materialize_host_home` rmtree's the host home
        # on every launch for exactly this reason ("so a removed recipe's files never linger"); the
        # container side has to do the same thing, just gated on the fingerprint instead of
        # unconditionally, because here the content is expensive to rebuild.
        #
        # Safe to destroy: the volume holds COMPOSED content only. Credentials and the rw history
        # dirs are bind-mounted over it at launch and live on the host, so they are not in here.
        _run([rt, "volume", "rm", "-f", vol], check=False, capture_output=True)
    _run([rt, "volume", "create", *_volume_labels(stack, harness, "config"), vol],
         check=False, capture_output=True)
    # `cp -a src/. dst/` MERGES into the copy-up'd tree rather than replacing it — the whole point.
    compose = (
        "set -e; "
        f"if [ -d {_CTR_PROFILE_DIR}/.claude ]; then "
        f"  cp -a {_CTR_PROFILE_DIR}/.claude/. {_CONTAINER_HOME_STR}/.claude/; "
        "fi; "
        f"if [ -f {_CTR_PROFILE_DIR}/settings.json ]; then "
        f"  cp -a {_CTR_PROFILE_DIR}/settings.json {_CONTAINER_HOME_STR}/.claude/settings.json; "
        "fi"
    )
    _run([
        rt, "run", "--rm", "--userns=keep-id",
        "-v", f"{vol}:{_CONTAINER_HOME_STR}/.claude",
        "-v", f"{prof}:{_CTR_PROFILE_DIR}:ro",
        "--entrypoint", "sh", image, "-c", compose,
    ], capture_output=True)
    return vol


# Shared by every stack, on purpose — see _run_container_installs.
_SHARED_DL_CACHE_VOLUME = "harnessed-dl-cache"
# Volumes are identified by LABEL, not by parsing their name: a stack name may contain the same
# hyphens the name format uses, so `harnessed-cfg-claude-a-b` is ambiguous about where the harness
# ends and the stack begins. The labels carry the fields directly (bd harnessed-8px.21.8).
_VOL_LABEL = "harnessed.role"
_VOL_STACK_LABEL = "harnessed.stack"
_VOL_HARNESS_LABEL = "harnessed.harness"


def _volume_labels(stack: str, harness: str, role: str) -> list[str]:
    return [
        "--label", f"{_VOL_LABEL}={role}",
        "--label", f"{_VOL_STACK_LABEL}={stack}",
        "--label", f"{_VOL_HARNESS_LABEL}={harness}",
    ]


def _stack_tools_volume(stack: str, harness: str) -> str:
    """Name of the per-stack TOOLS volume — `~/.local`, which covers all three PATH-bearing dirs.

    Verified in the bd harnessed-8px.21.1 spike: `$PNPM_HOME` is `~/.local/share/pnpm`, mise keeps
    its installs and its 67 shims under `~/.local/share/mise`, and `$HARNESSED_BIN_DIR` is
    `~/.local/bin`. One volume at the common parent covers all three, and podman's copy-up carries
    the base image's own mise/snyk/socket IN rather than hiding them.
    """
    return f"harnessed-tools-{harness}-{stack}"


def _container_stack_fingerprint(rt: str, stack: str, recipes: list, image: str) -> str:
    """The container gate: the host fingerprint PLUS the image's identity.

    The extra component is forced by podman's copy-up, which runs exactly ONCE per volume. After
    that the volume's content wins permanently and image updates are invisible — so a base image
    that gained a tool would never reach an existing stack, and nothing would signal it. Verified in
    the harnessed-8px.21.1 spike.

    Host mode needs no such component because a host launch has no image at all, which is why
    `_host_stack_fingerprint` carries `__version__` instead.
    """
    img = subprocess.run(
        [rt, "image", "inspect", "-f", "{{.Id}}", image], capture_output=True, text=True,
    ).stdout.strip()
    return f"{_host_stack_fingerprint(stack, recipes)}:{img}"


def _volume_read(rt: str, volume: str, image: str, rel: str) -> str | None:
    """`cat` one file out of the config volume, or None when absent.

    None vs "" is load-bearing for the settings merge, which must distinguish "no baked file"
    (keep the floor) from "empty file".
    """
    out = subprocess.run(
        [rt, "run", "--rm", "--userns=keep-id",
         "-v", f"{volume}:{_CONTAINER_HOME_STR}/.claude", "--entrypoint", "sh", image,
         "-c", f"cat {_CONTAINER_HOME_STR}/.claude/{rel}"],
        capture_output=True, text=True,
    )
    # Anything other than a clean read is "absent", NOT "empty". Returning "" for a failed podman
    # run made `_merge_baked_settings` treat an unreadable volume as MALFORMED JSON — it warned and
    # kept the floor, which looks identical to the harnessed-8px.19 regression this is meant to
    # prevent. Caught by test_merge_baked_settings_reads_the_VOLUME_not_the_image.
    return out.stdout if out.returncode == 0 else None


def _run_container_installs(
    rt: str, stack: str, harness: str, image: str, recipes: list, cfg_vol: str, tools_vol: str,
) -> None:
    """Run `tools:` then every `install.script` INSIDE a container, writing to the two volumes.

    The container half of `_host_run_installs`, in deliberately the same ORDER: `tools:` owns the
    binary and an install.sh CONFIGURES it (`serena init -b LSP`, ccstatusline's `command -v`), so
    the binary must exist first. A real build failed the other way round.

    One container per step rather than one generated shell script: each recipe's env differs, and
    passing it with `-e` avoids hand-quoting a script whose failure mode is silent and
    arbitrary-code-shaped.

    `--userns=keep-id` on every step, matching the pod the agent inherits. A volume written under
    any other mapping is unreadable by the agent (harnessed-8px.21.1).
    """
    common = [
        "--userns=keep-id",
        "-v", f"{cfg_vol}:{_CONTAINER_HOME_STR}/.claude",
        "-v", f"{tools_vol}:{_CONTAINER_HOME_STR}/.local",
        # The download cache, and the direct successor to the build's `--mount=type=cache` (bd
        # harnessed-1t4.2: "a layer cache MISS must not mean a re-download"). Those mounts died with
        # the layers; without this the container's ~/.cache is ephemeral and every reinstall
        # re-fetches from the network, which would make the runtime executor SLOWER than the build
        # it replaces.
        #
        # Deliberately NOT per-stack: one volume shared by every stack, which is the sharing 1t4.2
        # existed for. It covers ~/.cache/{mise,pnpm,uv} in one mount because an install.sh may
        # reach for any of them and that is the recipe author's choice to make.
        "-v", f"{_SHARED_DL_CACHE_VOLUME}:{_CONTAINER_HOME_STR}/.cache",
    ]

    tool_specs = sorted({t for r in recipes for t in r.tools})
    if tool_specs:
        joined = " ".join(f'"{t}"' for t in tool_specs)
        _say(f"[blue][INFO][/blue] tools: {len(tool_specs)} pinned tool(s) → {tools_vol}")
        # MISE_NPM_PACKAGE_MANAGER=pnpm is required, not preferred: mise's own `aube` resolver
        # enforces a tree-wide publisher-trust policy that hard-fails a correctly-pinned package
        # over an untrusted transitive dep. Sorted+deduped so the set, not the authoring order,
        # determines the work.
        _run([rt, "run", "--rm", *common, "-e", "MISE_NPM_PACKAGE_MANAGER=pnpm",
              "--entrypoint", "sh", image, "-c", f"mise use -g {joined} && mise install"])

    for recipe in recipes:
        inst = recipe.install
        if inst is None or inst.script is None:
            continue  # root-only install: the whole step is a system layer in the recipe Dockerfile
        cache_host = paths.install_cache_dir(recipe.name, inst.cache) if inst.cache else None
        ctr_cache = f"{emit.CTR_INSTALL_CACHE}/{recipe.name}/{inst.cache}" if cache_host else ""
        env = emit.install_env(
            recipe, mode="container", harness=harness,
            config_dir=f"{_CONTAINER_HOME_STR}/.claude",
            # The SHARED, cross-stack source cache — the same host dir `_host_run_installs` uses.
            # The build path threw this away (`rm -rf` in the same layer), so every stack re-cloned
            # what another had already fetched. Running at runtime is what makes it reachable.
            cache_dir=ctr_cache,
            bin_dir=f"{_CONTAINER_HOME_STR}/.local/bin",
            home_shim=_CONTAINER_HOME_STR,
        )
        # Recipe `env:` beats the inherited environment; the harnessed contract beats BOTH — same
        # winner as the Dockerfile emission, where inline RUN assignments beat preceding ENV lines.
        merged = {**resolve_recipe_env(recipe, mode="container", project_path=None), **env}
        args = [rt, "run", "--rm", *common,
                "-v", f"{recipe.root}:{emit.CTR_RECIPE_DIR}/{recipe.name}:ro"]
        if cache_host is not None:
            cache_host.parent.mkdir(parents=True, exist_ok=True)
            args += ["-v", f"{cache_host}:{ctr_cache}:rw"]
        for k, v in merged.items():
            args += ["-e", f"{k}={v}"]
        args += ["--entrypoint", "bash", image,
                 f"{emit.CTR_RECIPE_DIR}/{recipe.name}/{inst.script}"]
        _say(f"[blue][INFO][/blue] install ({recipe.name}): {inst.script} (container)")
        _run(args)


def _ensure_stack_volumes(
    rt: str, stack: str, harness: str, prof: Path, image: str, recipes: list,
) -> tuple[str, str]:
    """Compose both per-stack volumes, running installs only when the fingerprint moved.

    The container mirror of the host path's `rebuilt` gate: when the stack is unchanged the install
    output is still sitting in the volume, so re-running would re-download and re-extract bytes
    already on disk.

    Called by BOTH `harnessed build` and `harnessed launch`. That shared call is what keeps `build`
    meaningful once it emits system layers only — build populates and then scans, launch populates
    and runs.

    The stamp is written only AFTER the installs succeed, mirroring the host path: a failed install
    must never certify content that was never finished, or the next launch trusts a stamp for a
    half-populated volume instead of retrying.

    The fingerprint is read BEFORE composing, because a changed stack must start from an EMPTY
    config volume. Composition only ever adds, so reusing the old volume would leave a removed
    recipe's skills and commands in place forever.
    """
    tools_vol = _stack_tools_volume(stack, harness)
    _run([rt, "volume", "create", *_volume_labels(stack, harness, "tools"), tools_vol],
         check=False, capture_output=True)
    _run([rt, "volume", "create", "--label", f"{_VOL_LABEL}=shared", _SHARED_DL_CACHE_VOLUME],
         check=False, capture_output=True)

    want = _container_stack_fingerprint(rt, stack, recipes, image)
    have = _volume_read(
        rt, _stack_config_volume(stack, harness), image, _HOST_STACK_FINGERPRINT
    )
    unchanged = (have or "").strip() == want

    # `fresh=` discards the old config volume when the stack moved. The TOOLS volume is kept either
    # way: `mise use -g` is declarative, so a changed tool set rewrites the config it reads, and
    # discarding it would re-download every pinned tool for no benefit. Host mode draws the same
    # line — `_materialize_host_home` wipes the config home but never the stack's tools dir.
    cfg_vol = _ensure_config_volume(rt, stack, harness, prof, image, fresh=not unchanged)
    if unchanged:
        _say(f"[blue][INFO][/blue] Stack unchanged — reusing {cfg_vol} (installs skipped)")
        return cfg_vol, tools_vol

    _run_container_installs(rt, stack, harness, image, recipes, cfg_vol, tools_vol)
    _run([rt, "run", "--rm", "--userns=keep-id",
          "-v", f"{cfg_vol}:{_CONTAINER_HOME_STR}/.claude", "--entrypoint", "sh", image, "-c",
          f"printf %s {shlex.quote(want)} > {_CONTAINER_HOME_STR}/.claude/{_HOST_STACK_FINGERPRINT}"],
         capture_output=True)
    return cfg_vol, tools_vol


def _build_mount_args(
    harness: str,
    prof: Path,
    mount_path: Path,
    config_volume: str = "",
    tools_volume: str = "",
) -> list[str]:
    """Assemble -v mount arguments for the harness container.

    `mount_path` is the host folder path-mirrored into the container (the project itself by default,
    or a parent dir via --mount-folder). The agent's cwd (start_dir) lives at or under it.

    `config_volume` is the composed agent-config volume from `_ensure_config_volume`. When empty
    (a harness with no `~/.claude` surface) nothing is mounted there at all.
    """
    args: list[str] = []
    ctr_home = _CONTAINER_HOME_STR

    # .mcp.json → $CONTAINER_HOME/.mcp.json (claude only; --mcp-config points here)
    mcp_src = prof / ".mcp.json"
    if mcp_src.is_file() and harness == "claude":
        args += ["-v", f"{mcp_src}:{ctr_home}/.mcp.json:ro"]

    # The agent config tree — ONE composed volume (bd harnessed-8px.21.2), not the per-subdir `:ro`
    # bind-mounts this replaces. Those mounted `<profile>/.claude/<subdir>` OVER the image's own,
    # hiding every skill/command an `install.script` had delivered: 70 of 75 skills invisible, and
    # an EMPTY profile `commands/` dir shadowing a real one, because `synclinks._fan_into` creates
    # skills/commands/rules unconditionally and the mount gate was existence, not non-emptiness.
    # `_ensure_config_volume` composes image content and profile content into one tree instead, so
    # there is nothing left to shadow.
    if config_volume and harness in ("claude", "omp", "opencode"):
        args += ["-v", f"{config_volume}:{ctr_home}/.claude"]
    # `~/.local` — mise installs + shims, $PNPM_HOME, and $HARNESSED_BIN_DIR, all three on PATH.
    # Harness-independent: `tools:` is a recipe declaration, not a claude-shaped one.
    if tools_volume:
        args += ["-v", f"{tools_volume}:{ctr_home}/.local"]

    # opencode persona config (bd main-rlw): the merged opencode.json + persona prompt (written
    # post-build by _merge_baked_opencode, only when the stack has `instructions:`) override the
    # image-baked config, wiring the custom agent + rules-glob. Mounted only when present, so a
    # no-instructions opencode stack falls back to the untouched image config.
    if harness == "opencode":
        oc_cfg = prof / "opencode" / "opencode.json"
        if oc_cfg.is_file():
            args += ["-v", f"{oc_cfg}:{ctr_home}/.config/opencode/opencode.json:ro"]
        oc_prompts = prof / "opencode" / "prompts"
        if oc_prompts.is_dir():
            args += ["-v", f"{oc_prompts}:{ctr_home}/.config/opencode/prompts:ro"]

    # antigravity identity (bd main-6he): the baked GEMINI.md + settings.json emitted by
    # emit.write_antigravity_identity mirror the container's ~/.gemini/ tree. Mounted ro only when
    # present, so a no-instructions antigravity stack leaves the image config untouched.
    if harness == "antigravity":
        agy_settings = prof / ".gemini" / "settings.json"
        if agy_settings.is_file():
            args += ["-v", f"{agy_settings}:{ctr_home}/.gemini/settings.json:ro"]
        agy_identity = prof / ".gemini" / "GEMINI.md"
        if agy_identity.is_file():
            args += ["-v", f"{agy_identity}:{ctr_home}/.gemini/GEMINI.md:ro"]

    # codex identity (bd main-6he): the baked AGENTS.md emitted by emit.write_codex_agents_md is
    # codex's top-level memory doc (~/.codex/AGENTS.md). Mounted ro only when present.
    if harness == "codex":
        codex_agents = prof / ".codex" / "AGENTS.md"
        if codex_agents.is_file():
            args += ["-v", f"{codex_agents}:{ctr_home}/.codex/AGENTS.md:ro"]

    # History dirs (rw) — sourced from host $HOME for session persistence.
    home = str(Path.home())
    for rel in (".claude/projects", ".claude/file-history", ".claude/tasks",
                ".claude/session-env", ".claude/todos"):
        host_d = Path(home) / rel
        host_d.mkdir(parents=True, exist_ok=True)
        args += ["-v", f"{host_d}:{ctr_home}/{rel}:rw"]

    # omp: the whole agent dir (auth + sessions) is bind-mounted rw from the host by
    # _omp_agent_mount (appended in launch()); _omp_mcp_seed_mount then shadows just its mcp.json
    # with a per-instance copy that adds the hatago endpoint.

    # Claude's OAuth credentials: seeded + mounted rw by _claude_creds_seed_mount (appended in
    # launch()) — a ro mount here would block Claude Code's in-container token refresh, causing
    # the "gets logged out" bug (see _claude_creds_seed_mount docstring).

    # egress-firewall.sh (run inside the container by _apply_firewall).
    fw = _catalog_base("egress-firewall.sh")
    if fw.is_file():
        args += ["-v", f"{fw}:/usr/local/sbin/egress-firewall:ro"]

    # Path mirroring (MNT2-02): the mount root is accessible at its host absolute path inside the
    # container (so the agent sees host paths). With --mount-folder this is a parent of the project.
    args += ["-v", f"{mount_path}:{mount_path}"]

    return args


def _claude_config_seed_mount(harness: str, inst: str) -> list[str]:
    """Mount a minimal, token-free ~/.claude.json stub so Claude Code skips first-run onboarding.

    The real OAuth token lives in the rw ~/.claude/.credentials.json mount (see
    _claude_creds_seed_mount). But Claude Code *also* gates its onboarding (the "Select login
    method" screen) on ~/.claude.json — a credentialed container with no .claude.json still shows
    onboarding. We seed ONLY onboarding + identity fields (never the token), copied from the host
    ~/.claude.json, written to a per-instance state dir and mounted rw so Claude's runtime writes
    never touch the host file. (design §4b; ports lib/harnessed-isolated-config.sh.)
    """
    if harness not in ("claude", "omp"):
        return []

    oauth_account: object = {}
    user_id: object = ""
    host_json = Path.home() / ".claude.json"
    if host_json.is_file():
        try:
            data = json.loads(host_json.read_text(encoding="utf-8"))
            oauth_account = data.get("oauthAccount", {})
            user_id = data.get("userID", "")
        except (ValueError, OSError):
            pass  # missing/malformed host config → seed the onboarding flag only

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    stub = state_dir / "claude.json"
    stub.write_text(
        json.dumps({
            "hasCompletedOnboarding": True,
            "firstStartTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "numStartups": 1,
            "oauthAccount": oauth_account,
            "userID": user_id,
        }),
        encoding="utf-8",
    )
    return ["-v", f"{stub}:{_CONTAINER_HOME_STR}/.claude.json:rw"]


_OAUTH_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"


def _claude_oauth_token_args(harness: str) -> list[str]:
    """Pass a long-lived `CLAUDE_CODE_OAUTH_TOKEN` through to the container when one is configured.

    This is the SUPPORTED way to authenticate a containerized Claude Code against a subscription
    (`claude setup-token`, ~1-year lifetime, precedence above the credentials file). Because it
    never expires mid-session, it needs no in-container refresh — which is what makes the
    credential-file copy (and its whole divergence problem) unnecessary. See
    _claude_creds_seed_mount for the legacy fallback.

    Two supply routes, in order:
      * the host environment — forwarded as a bare `-e NAME` so podman reads the value from its
        own env instead of putting the secret on the command line (visible in `ps`);
      * a resolved `--env-file` (varlock/1Password or a project `.env`) — already handed to the
        container by the caller, so nothing extra is emitted here. This is the recommended route:
        the token is long-lived, so it belongs in a secret store, not a shell profile.
    """
    if harness not in ("claude", "omp"):
        return []
    if os.environ.get(_OAUTH_TOKEN_VAR):
        return ["-e", _OAUTH_TOKEN_VAR]
    return []


def _claude_oauth_token_configured(harness: str, project_path: Path | None = None) -> bool:
    """True when ``CLAUDE_CODE_OAUTH_TOKEN`` will reach the container at runtime.

    Checks, in order:
    1. ``os.environ`` — the token is already in the host process environment.
    2. Varlock resolution — structured check via ``_varlock_resolve``; asking
       ``resolved.get(KEY)`` is the authoritative answer and avoids a fragile
       text scan of a serialised env-file (the previous approach).
    3. Plain ``.env`` fallback — when no ``.env.schema`` / varlock is present,
       ``_plain_env_values`` parses the raw file directly.

    Drives ``_claude_creds_seed_mount``'s decision to skip or restore the legacy
    credential-file mount.

    Empty is NOT configured — ``export CLAUDE_CODE_OAUTH_TOKEN=`` is how a shell
    profile disables a token, and treating the bare name as "configured" would
    retire the credential file and silently log the user out with no recovery path
    (same semantics as ``_host_oauth_token_configured``).

    Emits a warning when ``_varlock_resolve`` itself fails (returns ``None``): the
    token may be configured but is unreachable at launch time (e.g. via a runtime
    secrets agent that does not write env-files).  The warning distinguishes this
    "cannot determine" state from "genuinely no token", so the credential-file
    mount that follows is not a silent regression.
    """
    if harness not in ("claude", "omp"):
        return False

    # Route 1: already in the host process environment.
    if os.environ.get(_OAUTH_TOKEN_VAR):
        return True

    have_varlock = bool(shutil.which("varlock"))
    global_dir = Path.home() / ".config" / "harnessed"
    dirs: list[Path] = [global_dir]
    if project_path is not None:
        dirs.append(project_path)

    # Dirs where varlock ran and FAILED. Collected rather than warned about inline: a later dir can
    # still supply the token (global varlock down, project `.env` has it), in which case we return
    # True and mount nothing — so an inline warning would promise a credential-file fallback that
    # never happens. Deferring to the return-False path also means ONE warning per launch listing
    # every failed dir, instead of one per dir.
    unresolved: list[Path] = []

    for d in dirs:
        schema = d / ".env.schema"
        if schema.is_file() and have_varlock:
            # Route 2: structured varlock query — no text-file scan.
            resolved = _varlock_resolve(d)
            if resolved is None:
                unresolved.append(d)
            elif resolved.get(_OAUTH_TOKEN_VAR):  # empty string is NOT configured
                return True
        else:
            plain = d / ".env"
            if plain.is_file():
                # Route 3: plain .env — _plain_env_values strips export / surrounding quotes.
                if _plain_env_values(plain).get(_OAUTH_TOKEN_VAR):
                    return True

    if unresolved:
        # No source produced a token AND varlock failed somewhere, so we genuinely cannot tell
        # "no token" from "token we could not reach". Say so before the credential file is mounted.
        where = ", ".join(str(d) for d in unresolved)
        _err.print(
            f"[bold yellow]warning:[/bold yellow] could not resolve "
            f"{_OAUTH_TOKEN_VAR} via varlock in {where} — varlock failed, so "
            "the token may be present but is unreachable here.\n"
            "  Mounting a credential file as fallback.  If a runtime secrets "
            "agent supplies the token inside the container, this mount is "
            "unnecessary — configure the token explicitly to suppress it."
        )

    return False


def _claude_creds_seed_mount(harness: str, inst: str, token_configured: bool = False) -> list[str]:
    """LEGACY FALLBACK: seed a per-instance copy of ~/.claude/.credentials.json, mounted rw.

    Mounting host credential files into a container is an anti-pattern (Anthropic's own
    devcontainer guidance says to prefer short-lived/scoped tokens), and it cannot be made
    correct: host and container refresh their copies independently, and concurrent refresh-token
    rotation is undocumented. `CLAUDE_CODE_OAUTH_TOKEN` supersedes this entirely — when one is
    configured (`token_configured`) no credential file is mounted at all.

    This path remains only so hosts that have not yet run `claude setup-token` keep working.
    It seeds from the host's credentials, and — unlike the original — RE-SEEDS when the existing
    copy has expired. The old code seeded exactly once, so an instance whose copy aged out was
    permanently logged out: relaunching never refreshed it and the only cure was deleting the
    state dir by hand. Re-seeding is gated on expiry precisely so a token the container itself
    refreshed is never clobbered while it is still valid (the reason for the original guard).
    """
    if harness not in ("claude", "omp") or token_configured:
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    stub = state_dir / "credentials.json"

    if not stub.is_file() or _claude_creds_expired(stub):
        host_creds = Path.home() / ".claude" / ".credentials.json"
        if not host_creds.is_file():
            return []
        stub.write_bytes(host_creds.read_bytes())
        stub.chmod(0o600)

    _err.print(
        "[bold yellow]warning:[/bold yellow] mounting a copy of your Claude credentials into the "
        "container — it expires in hours and cannot refresh in step with the host.\n"
        f"  Fix once:  [cyan]claude setup-token[/cyan]  then store the token as [bold]{_OAUTH_TOKEN_VAR}[/bold] "
        "in 1Password/varlock or your project .env\n"
        "  That token lasts ~1 year, needs no refresh, and this mount disappears."
    )
    return ["-v", f"{stub}:{_CONTAINER_HOME_STR}/.claude/.credentials.json:rw"]


def _claude_creds_expired(creds: Path) -> bool:
    """True when a seeded credential copy's OAuth access token has passed its `expiresAt`.

    Unparseable/absent expiry counts as expired: a copy we cannot vouch for is worth replacing
    with the host's current one. Reads only the expiry timestamp — never the token itself.
    """
    try:
        data = json.loads(creds.read_text(encoding="utf-8"))
        expires_at = data.get("claudeAiOauth", {}).get("expiresAt")
    except (ValueError, OSError):
        return True
    if not isinstance(expires_at, (int, float)):
        return True
    return (expires_at / 1000) <= datetime.now(timezone.utc).timestamp()


def _keyring_state_mount(harness: str, inst: str) -> list[str]:
    """Persist agy's Secret Service keyring store across recreates (bd main-ec5, antigravity only).

    Mirrors _claude_config_seed_mount's per-instance state-dir pattern: a host dir under
    XDG_STATE_HOME/harnessed/<inst>/keyrings is bind-mounted rw at the container's
    ~/.local/share/keyrings (agy's keyring store). `inst` is deterministic (stack + project), and a
    recreate only tears down the pod — host state dirs are never touched — so the same dir re-mounts
    and the in-pod OAuth token persists automatically. Unlike the claude.json stub, the token is
    generated in-pod and is NOT re-derivable from the host, so nothing is seeded; the dir is simply
    preserved as-is. Empty for every non-antigravity harness (they are unaffected).
    """
    if harness != "antigravity":
        return []
    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    keyring_dir = state_root / "harnessed" / inst / "keyrings"
    keyring_dir.mkdir(parents=True, exist_ok=True)
    return ["-v", f"{keyring_dir}:{_CONTAINER_HOME_STR}/.local/share/keyrings:rw"]


def _keyring_fresh_wipe(harness: str, inst: str) -> None:
    """--fresh wipes the persisted agy keyring so the next launch re-prompts OAuth (bd main-ec5).

    _keyring_state_mount's dir deliberately SURVIVES a normal recreate — that is the whole point of
    persisting the token — and neither _persist_mounts nor the per-instance state dir is wiped on
    --fresh (both are designed to survive it). So --fresh's "start clean" contract needs an explicit
    removal here; routing this through _persist_mounts would carry the wrong (survives-fresh)
    semantics. No-op for every non-antigravity harness.
    """
    if harness != "antigravity":
        return
    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    shutil.rmtree(state_root / "harnessed" / inst / "keyrings", ignore_errors=True)


def _keyring_init(harness: str) -> str:
    """Keyring-daemon init prefix for the antigravity attach shell (bd main-ec5).

    agy persists its Google-OAuth token to the Secret Service keyring, but the isolated container has
    no keyring daemon. Start a session D-Bus + gnome-keyring-daemon HERE — in the same shell that
    execs agy — so agy inherits DBUS_SESSION_BUS_ADDRESS / GNOME_KEYRING_CONTROL / SSH_AUTH_SOCK. A
    detached daemon (exec -d) would not export its env into this attach shell, so it MUST run inline.
    The keyring is unlocked with an empty password (printf ''), auto-creating the login keyring empty
    on first run; its store is a persistent host mount (_keyring_state_mount), so the token survives
    recreates. Returns "" for every non-antigravity harness (their attach shell is unchanged).
    """
    if harness != "antigravity":
        return ""
    return (
        "export $(dbus-launch) "
        "&& printf '' | gnome-keyring-daemon --unlock --components=secrets "
        '&& eval "$(printf \'\' | gnome-keyring-daemon --start --components=secrets)"'
    )


def _omp_agent_mount(harness: str) -> list[str]:
    """Bind-mount the host's omp agent dir so the pod shares one omp state with the host.

    omp (Oh My Pi) keeps everything under ~/.omp/agent — credentials (agent.db `auth_credentials`,
    plaintext JSON), setup/provider config (config.yml), usage tracking, and sessions. Rather than
    copy a per-instance snapshot, we bind-mount the host dir rw: auth is always current, usage is
    written back to the single host ledger, and sessions are shared across the host and every
    container (the user runs these containers as their primary omp — the host is not a separate
    source of truth). The omp image bakes ~/.omp/{plugins,natives}, NOT agent/, so this shadows
    nothing. Trade-off: full host-state sharing (not isolated); SQLite/WAL coordinates concurrent
    host+container access on the same kernel, but avoid heavy simultaneous writes from both.
    """
    if harness != "omp":
        return []
    host_agent = Path.home() / ".omp" / "agent"
    if not host_agent.is_dir():
        _err.print(
            "[yellow]note:[/yellow] no ~/.omp/agent on the host — omp will prompt to log in "
            "(run `omp` on the host first)."
        )
        return []
    return ["-v", f"{host_agent}:{_CONTAINER_HOME_STR}/.omp/agent:rw"]


def _omp_mcp_seed_mount(harness: str, inst: str) -> list[str]:
    """Point omp at the in-container hatago hub by seeding a per-instance ~/.omp/agent/mcp.json.

    harnessed wires the MCP layer for claude via `claude --mcp-config <profile .mcp.json>` — the
    single hatago endpoint that fronts every assembled server (stdio children hatago spawns, http
    servers it proxies). omp has no such flag: it reads MCP servers only from ~/.omp/agent/mcp.json,
    which `_omp_agent_mount` bind-mounts rw from the host (shared state). So a stack's MCP servers,
    which live behind hatago, are invisible to omp — the exact gap behind "repowise didn't install".

    Fix: generate a per-instance mcp.json = the host file's contents (preserving whatever the user
    manages there) plus a `hatago` HTTP entry, and bind-mount it ro OVER ~/.omp/agent/mcp.json. This
    nested file mount shadows the dir mount's own mcp.json (podman applies the more-specific
    destination), so omp connects to hatago — WITHOUT mutating the shared host file. Regenerated
    every launch (a pure function of the host file + the hatago endpoint), so host edits propagate on
    the next launch and nothing in-container writes back (ro)."""
    if harness != "omp":
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    seed = state_dir / "omp-mcp.json"

    cfg: dict = {}
    host_mcp = Path.home() / ".omp" / "agent" / "mcp.json"
    if host_mcp.is_file():
        try:
            cfg = json.loads(host_mcp.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.setdefault("mcpServers", {})["hatago"] = {"type": "http", "url": paths.hatago_endpoint()}
    seed.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    return ["-v", f"{seed}:{_CONTAINER_HOME_STR}/.omp/agent/mcp.json:ro"]


def _ccstatusline_settings_mount(home: Path | None = None) -> list[str]:
    """Forward the host's ccstatusline config read-only, if present.

    The `ccstatusline` recipe bakes a Claude `statusLine` that runs the `ccstatusline` renderer;
    that renderer reads ~/.config/ccstatusline/settings.json. Bind-mounting the host's file :ro
    (same file-by-file, is_file()-guarded, read-only pattern as the gh-hosts credential forward)
    lets the container's status line match the host's layout/segments. This is personalization, not
    a credential, so it is NOT gated on `forward_git_credentials` — and it is guarded on host-file
    existence, so a host with no ccstatusline config is a clean no-op (ccstatusline falls back to
    its built-in defaults). Harness-agnostic: for a non-claude harness (no baked statusLine) the
    mounted file simply goes unread.
    """
    home = home or Path.home()
    cfg = home / ".config" / "ccstatusline" / "settings.json"
    if not cfg.is_file():
        return []
    return ["-v", f"{cfg}:{_CONTAINER_HOME_STR}/.config/ccstatusline/settings.json:ro"]


def _host_os() -> str:
    """'macos' | 'linux' | 'other'. Drives per-OS agent socket paths + YubiKey passthrough."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):  # pyright: ignore[reportUnreachable]
        return "linux"
    return "other"


def _op_agent_socket(home: Path) -> Path:
    """Host path to the 1Password SSH agent socket, per OS (paths are 1Password-published)."""
    if _host_os() == "macos":
        return home / "Library" / "Group Containers" / "2BUA8C4S2C.com.1password" / "t" / "agent.sock"
    return home / ".1password" / "agent.sock"


def _gpg_ssh_socket() -> Path | None:
    """Host path to the gpg-agent SSH socket (YubiKey-resident keys), cross-platform.

    `gpgconf --list-dirs agent-ssh-socket` is the portable source of truth on Linux AND macOS; fall
    back to the Linux default only when gpgconf isn't on PATH. None when undeterminable.
    """
    try:
        out = subprocess.run(
            ["gpgconf", "--list-dirs", "agent-ssh-socket"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    if _host_os() == "linux":
        return Path(f"/run/user/{os.getuid()}/gnupg/S.gpg-agent.ssh")
    return None


def _macos_op_socket_mount_source(rt: str, host_sock: Path) -> Path | None:
    """macOS only: a path the container runtime can bind-mount for the 1Password agent socket.

    PENDING VERIFICATION (macOS-gated — I could not test this from Linux). On macOS the container
    runtime is a Linux VM (podman machine / Docker Desktop), and a host unix socket does NOT
    traverse the host→VM file share, so a plain `-v <host_sock>:…` usually fails. The working pattern
    is to reverse-forward the socket INTO the VM and bind-mount the in-VM path. This wires the podman
    machine reverse-forward; it is UNVERIFIED on real hardware — see
    docs/todos/2026-06-30-macos-ssh-agent-forwarding.md before trusting it.

    Returns the in-VM socket path on a best-effort success, else None (caller falls back to the raw
    host path + a note). Never raises; never blocks the launch.
    """
    if rt != "podman":
        return None  # Docker Desktop uses a different relay; not wired yet (see the todo).
    vm_sock = Path("/tmp/harnessed-op-agent.sock")
    try:
        # Reverse-forward host_sock → vm_sock inside the running podman machine, backgrounded.
        # StreamLocalBindUnlink=yes clears a stale vm_sock so a second launch's -R bind doesn't fail
        # (the fixed path would otherwise leak a dead socket + a backgrounded ssh forever).
        # ExitOnForwardFailure=yes makes ssh exit non-zero if the forward can't be established, so we
        # DON'T return a path pointing at nothing.
        r = subprocess.run(
            ["podman", "machine", "ssh", "-f", "-N", "-T",
             "-o", "StreamLocalBindUnlink=yes", "-o", "ExitOnForwardFailure=yes",
             "-R", f"{vm_sock}:{host_sock}"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None  # forward failed → caller falls back to the note, not a dead socket path
    return vm_sock


def _ssh_agent_args(home: Path, gpg_ssh_sock: Path | None, *, rt: str = "podman") -> list[str]:
    """Forward the host's SSH signing/auth agent into the container, setting SSH_AUTH_SOCK.

    Two agents, in precedence order (ports container.sh):
    - 1Password SSH agent — primary. op-ssh-sign signs commits through it and `git push` over SSH
      authenticates through it. Private keys never leave 1Password. Path is OS-aware
      (`_op_agent_socket`); on macOS the mountable source may be a podman-machine relay path.
    - gpg-agent SSH socket — the YubiKey path. Mounted when present, but only claims SSH_AUTH_SOCK
      when 1Password's socket is absent, so a machine with both keeps 1Password as the active signer.

    Each is conditioned on the socket existing, so this is a clean no-op when neither agent is running.
    """
    ctr = _CONTAINER_HOME_STR
    args: list[str] = []
    op_agent = _op_agent_socket(home)
    op_present = op_agent.is_socket()
    if op_present:
        source = op_agent
        if _host_os() == "macos":
            relayed = _macos_op_socket_mount_source(rt, op_agent)
            if relayed is not None:
                source = relayed
            else:
                _err.print(
                    "[yellow]note:[/yellow] macOS 1Password agent forwarding is unverified "
                    "(host→VM socket relay) — if push/sign fails, see "
                    "docs/todos/2026-06-30-macos-ssh-agent-forwarding.md"
                )
        ctr_sock = f"{ctr}/.1password/agent.sock"
        args += ["-v", f"{source}:{ctr_sock}", "-e", f"SSH_AUTH_SOCK={ctr_sock}"]
    if gpg_ssh_sock is not None and gpg_ssh_sock.is_socket():
        # A ':' in the socket path would reparse the `-v src:dst` spec. Sockets don't normally
        # contain ':', but gpgconf output is host-derived — skip defensively rather than mis-mount.
        if ":" in str(gpg_ssh_sock):
            _err.print(
                f"[yellow]note:[/yellow] gpg-agent SSH socket path {gpg_ssh_sock} contains ':' "
                "— skipping mount."
            )
        else:
            ctr_gpg = f"{ctr}/.gnupg-sockets/S.gpg-agent.ssh"
            args += ["-v", f"{gpg_ssh_sock}:{ctr_gpg}"]
            if not op_present:  # 1Password wins; gpg only drives SSH_AUTH_SOCK when it's the only agent
                args += ["-e", f"SSH_AUTH_SOCK={ctr_gpg}"]
    return args


def _yubikey_device_args() -> list[str]:
    """`--device` passthrough for a connected YubiKey (Yubico vendor id 1050) so in-container gpg/
    op-ssh can reach the token. LINUX ONLY: macOS runs the container in a Linux VM with no
    `/dev/bus/usb`, so USB passthrough isn't possible there (the YubiKey reaches the container via
    the gpg-agent SSH socket relay instead). Best-effort `lsusb` parse; [] when absent.
    """
    if _host_os() != "linux":
        return []
    try:
        out = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    for line in out.stdout.splitlines():
        low = line.lower()
        if "yubico" not in low and "id 1050:" not in low:
            continue
        # "Bus 003 Device 004: ID 1050:0407 Yubico.com ..." → /dev/bus/usb/003/004
        parts = line.split()
        if len(parts) >= 4:
            bus, dev = parts[1], parts[3].rstrip(":")
            device = f"/dev/bus/usb/{bus}/{dev}"
            if Path(device).exists():
                return ["--device", device]
    return []


def _ssh_dir_mounts(home: Path, ssh_keys: list[str]) -> list[str]:
    """Forward the non-secret SSH surface + opt-in private keys, file-by-file (NOT the whole ~/.ssh).

    The repo hard-denies `~/.ssh` to recipes for a reason (persist.py); blanket-mounting it would
    drop every private key into the container. Instead:
    - Always (when present, ro): `config`, `known_hosts`, and every `*.pub` — host verification +
      ssh config + public identities, none of which are secret.
    - Private keys ONLY when the stack's `ssh_keys:` opts them in by basename — for hosts without an
      agent (1Password/gpg). The name is schema-validated to a single component, so it can't escape
      ~/.ssh; we still re-check the resolved path stays under ~/.ssh as defense-in-depth.
    """
    ctr = _CONTAINER_HOME_STR
    ssh_dir = (home / ".ssh").resolve()
    if not ssh_dir.is_dir():
        return []
    args: list[str] = []

    def _mount_named(name: str) -> None:
        # Resolve the entry and require it be a regular file living DIRECTLY under ~/.ssh.
        # Symlinks are followed, so a config / known_hosts / *.pub whose target escapes ~/.ssh
        # (e.g. ~/.ssh/config -> ~/.aws/credentials) is rejected — the same defense-in-depth the
        # opt-in ssh_keys path uses — rather than mounting the secret target read-only. `:` is the
        # podman `-v src:dst:opts` separator: a name containing one would reparse the spec (no shell
        # injection — list args), so skip it.
        if ":" in name:
            _err.print(f"[yellow]note:[/yellow] skipping ~/.ssh/{name} (':' in name).")
            return
        target = (ssh_dir / name).resolve()
        if target.parent != ssh_dir or not target.is_file():
            return
        args.extend(["-v", f"{target}:{ctr}/.ssh/{name}:ro"])

    for name in ("config", "known_hosts"):
        _mount_named(name)
    for pub in sorted(ssh_dir.glob("*.pub")):
        _mount_named(pub.name)
    for name in ssh_keys:
        target = (ssh_dir / name).resolve()
        if target.parent != ssh_dir or not target.is_file():
            _err.print(
                f"[yellow]note:[/yellow] ssh_keys: '{name}' not found in ~/.ssh (or not a regular "
                f"file) — skipping."
            )
            continue
        args += ["-v", f"{target}:{ctr}/.ssh/{name}:ro"]
    return args


def _gnupg_mounts(home: Path) -> list[str]:
    """Forward only the NON-SECRET GPG files — NEVER the private keyring.

    The bash launcher mounted all of ~/.gnupg, which drags in `private-keys-v1.d/*.key` — the actual
    secret key material for SOFTWARE openpgp keys (only YubiKey-resident keys are stubs there). `ro`
    doesn't help: read-only still means fully readable → exfiltratable by an autonomous agent (or a
    compromised dep) in the container. That also overrides persist.py's hard-deny of ~/.gnupg. So we
    forward ONLY the public/config surface, file-by-file, and never `private-keys-v1.d/`.

    This means SSH-format signing (op-ssh-sign / gpg-agent SSH socket, see `_ssh_agent_args`) is the
    supported in-container path; full openpgp GPG *signing* in-container (which needs the gpg-agent
    socket + selectively-forwarded YubiKey stubs, without the software secrets) is a scoped follow-up
    — see docs/todos/2026-06-30-macos-ssh-agent-forwarding.md.
    """
    ctr = _CONTAINER_HOME_STR
    gnupg = home / ".gnupg"
    if not gnupg.is_dir():
        return []
    args: list[str] = []
    for name in ("pubring.kbx", "trustdb.gpg", "gpg.conf", "gpg-agent.conf", "sshcontrol"):
        f = gnupg / name
        if f.is_file():
            args += ["-v", f"{f}:{ctr}/.gnupg/{name}:ro"]
    return args


def _trusted_ssh_keys(stk_ssh_keys: list[str], from_overlay: bool, stack: str) -> list[str]:
    """Private-key (`ssh_keys`) mounts are honored ONLY from the user's own overlay catalog.

    A stack.yaml can come from a SHARED repo catalog (per CLAUDE.md). Mounting a real private key is
    the KEY OWNER's decision, not a third-party stack author's — so `ssh_keys` from anywhere but the
    user overlay (`~/.config/harnessed/catalog`) is dropped with a warning. (Public keys / config /
    known_hosts, which are not secret, are unaffected — this only gates private-key files.)
    """
    if stk_ssh_keys and not from_overlay:
        _err.print(
            f"[yellow]note:[/yellow] ignoring ssh_keys from shared-catalog stack '{stack}' — declare "
            f"private keys only in your user overlay (~/.config/harnessed/catalog)."
        )
        return []
    return stk_ssh_keys


def _stack_from_overlay(stack: str) -> bool:
    """True when this stack resolves to the user's own overlay catalog — the gate _trusted_ssh_keys
    applies before mounting any private key. False if the stack can't be resolved at all (fail
    closed: an unresolvable stack is not "yours")."""
    try:
        stack_dir = paths.find_in_catalog("stacks", stack)
    except Exception:
        return False
    return stack_dir.resolve().is_relative_to(paths.user_catalog().resolve())


def _gh_hosts_missing_plaintext_token(gh_hosts: Path) -> bool:
    """True when hosts.yml has host/user entries but no plaintext `oauth_token` anywhere.

    Modern `gh` defaults to storing the OAuth token in the OS credential store (macOS Keychain,
    Secret Service, Credential Manager) instead of this file, falling back to plain text only when
    no store is available or `--insecure-storage` is passed. The container only gets this file
    bind-mounted in (read-only, see below) — it has no access to the host's keychain — so a
    hosts.yml with real entries but no `oauth_token` field anywhere means `gh` inside the container
    has no usable token, even though `gh auth status` succeeds on the host. Confirmed on macOS: a
    keychain-backed entry looks like `users: {<name>: {}}` — the token is entirely absent, not
    present-but-empty.
    """
    try:
        data = YAML(typ="safe", pure=True).load(gh_hosts.read_text())
    except Exception:
        return False  # can't parse — don't warn on a guess

    def has_token(node: object) -> bool:
        if isinstance(node, dict):
            if "oauth_token" in node:
                return True
            return any(has_token(v) for v in node.values())
        return False

    return bool(data) and not has_token(data)


def _git_identity_config_mount(home: Path) -> list[str]:
    """Mount the host's git identity config (`~/.config/git` dir, else legacy `~/.gitconfig`) ro.

    Carries user.signingkey, gpg.format=ssh, gpg.ssh.program=op-ssh-sign, commit.gpgsign — the
    settings op-ssh-sign needs to actually sign commits. It's a public-key reference, not a secret.
    """
    ctr = _CONTAINER_HOME_STR
    xdg_git = home / ".config" / "git"
    legacy_git = home / ".gitconfig"
    if xdg_git.is_dir():
        return ["-v", f"{xdg_git}:{ctr}/.config/git:ro"]
    if legacy_git.is_file():
        return ["-v", f"{legacy_git}:{ctr}/.gitconfig:ro"]
    return []


def _ssh_agent_auto_forward_args(home: Path | None = None, rt: str = "podman") -> list[str]:
    """Auto-forward the host SSH signing/auth agent (1Password primary, gpg-agent fallback) plus the
    ro git identity config WHENEVER the agent socket is live on the host — independent of the stack's
    `forward_git_credentials` opt-in.

    Rationale (why this is safe to make the default, unlike the full credential bundle): the agent
    socket exposes no key material and gates every sign/auth behind a host-side 1Password approval or
    YubiKey touch, and the git config it needs to drive op-ssh-sign is a public signing-key reference,
    not a secret. So "1Password available → wired up" holds. The genuinely-secret surface — the gh
    oauth token in hosts.yml and opt-in private SSH keys — stays behind `forward_git_credentials` in
    `_credential_forward_args`. No-op when no agent socket is present.
    """
    home = home or Path.home()
    args = _ssh_agent_args(home, _gpg_ssh_socket(), rt=rt)
    if not args:
        return []
    args += _git_identity_config_mount(home)
    return args


# Default port the aws-sso ECS server listens on (aws-sso-cli default). Kept in sync with the
# `--port` default of `harnessed aws-sso serve`.
AWS_SSO_ECS_PORT = 4144


def _aws_sso_ecs_forward_args(port: int = AWS_SSO_ECS_PORT, token_file: Path | None = None) -> list[str]:
    """Wire the container to the host's aws-sso ECS server (default slot) for stacks that opt in with
    `forward_aws_sso: true`.

    Emits AWS_CONTAINER_CREDENTIALS_FULL_URI (the AWS SDK's ECS-task-role endpoint, pointed at the
    host's `aws-sso ecs server` via host.containers.internal) + AWS_CONTAINER_AUTHORIZATION_TOKEN
    (the bearer token gating that server). The in-container AWS SDK then pulls short-lived STS creds
    over HTTP — no aws-sso binary, ~/.aws-sso store, or SSO token ever enters the container.

    The bearer token is read from the user-owned token file that `harnessed aws-sso serve` writes
    (single source of truth). No-op when that file is absent/empty — so a `forward_aws_sso` stack
    launches fine on a host that hasn't set up the server (the SDK just finds no AWS creds), and the
    token never lands in an image layer (it arrives as a per-launch `-e`).
    """
    tf = token_file or paths.aws_sso_ecs_token_file()
    try:
        token = tf.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not token:
        return []
    uri = f"http://host.containers.internal:{port}/"
    return [
        "-e", f"AWS_CONTAINER_CREDENTIALS_FULL_URI={uri}",
        "-e", f"AWS_CONTAINER_AUTHORIZATION_TOKEN=Bearer {token}",
    ]


def _aws_sso_server_reachable(port: int = AWS_SSO_ECS_PORT, timeout: float = 1.5) -> bool:
    """True iff the host aws-sso ECS server is up AND has a role loaded.

    Probes the server's unauthenticated `GET /healthcheck`, which returns 200 only when the default
    slot holds valid credentials — so a single check covers both "server not running" and "no role
    loaded". Any failure (connection refused, timeout, non-200) is treated as unreachable. The probe
    hits 127.0.0.1 (host loopback), not host.containers.internal — this runs on the host, at launch.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: S310 (fixed host-local http URL)
            f"http://127.0.0.1:{port}/healthcheck", timeout=timeout
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _credential_forward_args(
    home: Path | None = None, ssh_keys: list[str] | None = None, rt: str = "podman"
) -> list[str]:
    """Forward the host's git signing + push credential surface into the harness container.

    Restores what the bash launcher (container.sh) forwarded — so the agent can `git push` and sign
    commits inside the container WITHOUT baking any secret into an image — but OS-aware and with the
    blunt whole-`~/.ssh` mount narrowed to the non-secret surface plus opt-in private keys. Every
    piece is conditioned on host-side existence, so it's a clean no-op when nothing is configured.

    - SSH signing/auth agent (1Password primary, gpg-agent/YubiKey fallback) — see `_ssh_agent_args`.
    - NON-SECRET GPG files only (pubring/trustdb/config, NEVER the private keyring) — `_gnupg_mounts`.
    - YubiKey USB device passthrough (`--device`, Linux only) — see `_yubikey_device_args`.
    - git config (`~/.config/git` dir, else legacy `~/.gitconfig`, ro): carries user.signingkey,
      gpg.format=ssh, gpg.ssh.program=op-ssh-sign, commit.gpgsign so commits actually sign.
    - gh auth (`~/.config/gh/hosts.yml`, ro): the file that carries gh's oauth_token, so `gh pr
      create` etc. authenticate as the host user — just the hosts file, no wider gh config, no token
      baked into env or image.
    - ssh config + known_hosts + public keys (ro), plus stack `ssh_keys` opt-in privates — see
      `_ssh_dir_mounts`.

    NOTE: the dropped "transparent mode" (rw `~/.claude`) is intentionally NOT restored.
    """
    home = home or Path.home()
    ssh_keys = ssh_keys or []
    ctr = _CONTAINER_HOME_STR
    args = _ssh_agent_args(home, _gpg_ssh_socket(), rt=rt)

    args += _gnupg_mounts(home)

    args += _yubikey_device_args()

    args += _git_identity_config_mount(home)

    gh_hosts = home / ".config" / "gh" / "hosts.yml"
    if gh_hosts.is_file():
        args += ["-v", f"{gh_hosts}:{ctr}/.config/gh/hosts.yml:ro"]
        if _gh_hosts_missing_plaintext_token(gh_hosts):
            _err.print(
                "[yellow]note:[/yellow] gh config found, but no plaintext token — it's likely "
                "stored in the host's system credential store (e.g. macOS Keychain), which this "
                "container cannot reach. `gh` will not authenticate inside the container. Run "
                "[bold]gh auth login --insecure-storage[/bold] (or `gh auth refresh "
                "--insecure-storage` if already logged in) on the host to store a plaintext token."
            )

    gh_config = home / ".config" / "gh" / "config.yml"
    if gh_config.is_file():
        args += ["-v", f"{gh_config}:{ctr}/.config/gh/config.yml:ro"]

    args += _ssh_dir_mounts(home, ssh_keys)

    return args


def _ensure_gitignore_entry(project_path: Path, name: str) -> None:
    """Idempotently add `name` to project_path/.gitignore, but only when inside a git repo.

    Skips silently when project_path is not a git repository — an in_repo persist entry may
    reasonably be used in a non-git project (it just means harnessed won't manage .gitignore).
    Never raises — failure to update .gitignore is non-fatal; the persist still works.
    """
    if paths.git_common_dir(project_path) is None:
        return
    gitignore = project_path / ".gitignore"
    try:
        if gitignore.exists():
            existing = gitignore.read_text(encoding="utf-8")
            for line in existing.splitlines():
                stripped = line.strip()
                if stripped == name or stripped == f"/{name}":
                    return  # already present
            gitignore.write_text(existing.rstrip("\n") + f"\n{name}\n", encoding="utf-8")
        else:
            gitignore.write_text(f"{name}\n", encoding="utf-8")
    except OSError:
        pass  # non-fatal


def harnessed_env(
    stack: str,
    project_path: Path,
    *,
    harness: str,
    mode: str,
    mount_path: Path | None = None,
    recipe=None,
    sockets: bool = True,
) -> dict[str, str]:
    """THE folder-env contract — the same var names, with the same meanings, on every surface.

    One definition, injected everywhere a catalog-authored string or file can run: the container
    attach shell (`_init_shell_prologue`), both `setup.condition` eval sites
    (`_collect_setup_notices` host-side, `_host_run_setups`), `setup.script`/`setup.run`, the
    container itself (`podman run -e`), and the host agent process (`os.environ` in `_launch_host`).
    A recipe author writes `${MAIN_REPO_DIR}` once and it resolves the same in all of them.

    See ARCHITECTURE.md §"Folder-env contract" for the authoritative table. Notes on two entries:

    * `HARNESSED_GIT_COMMON_DIR` is the explicitly-named handle for the git common dir (same value
      as MAIN_REPO_DIR). A bare `GIT_COMMON_DIR` is deliberately NEVER exported: git itself consumes
      that variable, so it would hijack common-dir resolution the moment the agent cd's into a
      different repository.
    * `HARNESS` is unprefixed on purpose — it is already the token a recipe Dockerfile branches on
      (`ARG HARNESS`), so a setup script branching on `$HARNESS` means exactly the same thing.

    `mode` is "host" or "container". Socket-backed service vars (HARNESSED_<NAME>_SOCKET) are
    container-only: their value is a container-side path, and a host launch runs no service sidecars, so
    exporting them host-side would hand a recipe a path that does not exist. `sockets=False`
    suppresses them entirely — `_script_env` needs a key set that is IDENTICAL in both modes, and
    the container gets the socket vars box-wide anyway.
    """
    main_repo = paths.git_common_dir(project_path) or project_path
    workspace = mount_path or paths.bare_worktree_container(project_path) or project_path
    env = {
        "HARNESS": harness,
        "PROJECT_DIR": str(project_path),
        "MAIN_REPO_DIR": str(main_repo),
        "HARNESSED_GIT_COMMON_DIR": str(main_repo),
        "CONTAINER_WORKSPACE_DIR": str(workspace),
        "HOST_WORKSPACE_DIR": str(workspace),
        # The host $HOME, which is NOT the container's ($HOME is /home/harnessed in the pod). A
        # `scope: global` persist entry is mounted path-preserving, so a recipe whose tool reads a
        # dotdir under the host home (e.g. pulumi's ~/.pulumi) must point the tool at the mirrored
        # path — `$HOST_HOME/.pulumi`, not `~/.pulumi`. This export is that handle.
        "HOST_HOME": str(Path.home()),
        # The dir an `install.script` landed its executables in — the SAME value the install
        # contract hands that script (emit.install_env's bin_dir), so a recipe that installs a
        # wrapper at build time can put it on PATH at attach time (`init: run: export
        # PATH="${HARNESSED_BIN_DIR:?}/…:$PATH"`, beads' bd-shim). Mode-resolved for the same
        # reason every other path here is: the container's bin dir is the image's, the host's is
        # the stack's own tools dir.
        "HARNESSED_BIN_DIR": (
            f"{CONTAINER_HOME}/.local/bin" if mode == "container" else str(_stack_tools_dirs(stack)[1])
        ),
    }
    if sockets:
        # Both modes (bd harnessed-162). This used to be container-only, so a host launch never got
        # HARNESSED_<SVC>_SOCKET and the beads recipes' `setup:` line — which interpolates it with a
        # `:?` guard — always aborted, even with the sidecar running. The guard was telling the truth:
        # the variable genuinely did not exist. Correct in host mode only because _service_data_dir
        # now resolves the agent path per mode (harnessed-5ek); before that this would have exported
        # a container path onto the host.
        env.update(svc_socket_env(stack, project_path, mode))
        # A service's own declared client env (host/port/password for a published sidecar). Last,
        # so a service that declares both a HARNESSED_<SVC>_SOCKET-style handle and explicit
        # client vars resolves them from the same launch.
        env.update(svc_client_env(stack, project_path, mode))
    if recipe is not None:
        # A setup script does `cp` where a recipe Dockerfile did `COPY`, so it needs its own source
        # dir. Container-side that is the ro mount from `_setup_script_mounts`; host-side it is the
        # catalog dir itself.
        env["HARNESSED_RECIPE_DIR"] = (
            f"{_CTR_RECIPE_DIR}/{recipe.name}" if mode == "container" else str(recipe.root)
        )
    return env


def _init_shell_prologue(stack: str, project_path: Path, mount_path: Path, *, harness: str) -> str:
    """Shell snippet run in the attach shell BEFORE the harness starts (Model A).

    Exports the generic path contract, then runs each recipe's `init.run` inline in this SAME shell
    so init-derived env (e.g. beads' BEADS_DIR) flows straight into the agent process — no
    profile.d, no transient container. A failing init aborts the attach with a clear message so the
    harness never starts on a half-initialized tool. Init runs on EVERY attach; recipe `init.run`
    strings self-gate cheaply (idempotent) now that the declarative host-side marker is gone.

    Paths are path-mirrored into the container (host path == container path, see _build_mount_args),
    so these host-side values are also the correct container-side values. MAIN_REPO_DIR is the git
    common dir — in a bare + linked-worktree layout that is the bare repo dir (deliberately NOT the
    default-branch work tree: tool-specific resolution like beads' bd-resolve-beads-dir stays a baked
    helper the init.run sources from). Returns just the exports when no recipe declares init.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    parts = [
        # Rootless podman on macOS maps host UIDs through the VM; git refuses to operate in mounted
        # dirs ("dubious ownership") — breaking mise templates that shell out to git. Use git's
        # env-var config mechanism (git 2.32+, Ubuntu 24.04 ships 2.43) instead of writing to
        # ~/.gitconfig: the launcher mounts the host's ~/.gitconfig :ro, so any write attempt
        # fails with "Device or resource busy". These env vars are inherited by mise and all
        # subprocesses it spawns, including the git invocations inside mise templates.
        "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0='safe.directory' GIT_CONFIG_VALUE_0='*'",
    ]
    # The folder-env contract (incl. socket-backed project-scoped services, e.g. beads-server, so a
    # recipe's `setup:` can reference the socket verbatim instead of recomputing path arithmetic).
    contract = harnessed_env(
        stack, project_path, harness=harness, mode="container", mount_path=mount_path
    )
    for var, val in contract.items():
        parts.append(f"export {var}={shlex.quote(val)}")
    # Plain exports never fail, so they're joined with `;` — `&&` is reserved for the recipe-init
    # fail-fast blocks below, keeping it absent entirely when no recipe declares init.
    prologue = "; ".join(parts)
    for recipe in recipes:
        if recipe.init is None:
            continue
        # `{ run; }` is a brace group (current shell — a subshell would discard exports); a non-zero
        # run prints a clear error and `exit`s the attach shell before the harness is reached.
        prologue += (
            f" && {{ {recipe.init.run}; }} || "
            f"{{ echo 'harnessed: init failed for recipe {recipe.name} — fix and relaunch' >&2; exit 1; }}"
        )
    return prologue


def _persist_mounts(stack: str, project_path: Path) -> list[str]:
    """Bind-mount each recipe's declared persist entries (rw) so their state survives `--fresh`.

    scope: workspace, location: host (T4a):
        harnessed owns a dir at persist/<recipe>/<workspace_hash>/<name>/ and mounts it rw at
        $HOME/<name> inside the pod. Keyed by the resolved launch path (per-worktree).

    scope: project, location: host:
        Same as workspace but keyed by git-common-dir, so every worktree of the same checkout
        shares one dir. Falls back to workspace scope (with a warning) for non-git projects.

    scope: global, location: (none) (T4b):
        Mounts a REAL host dir PATH-PRESERVING (host path == container path) so the tool finds
        its data where it expects — but ONLY after the hard-deny + allowlist gate clears it.

    scope: workspace|project, location: in_repo:
        No extra mount — the workspace is already mounted rw. For vcs: ignored, harnessed
        ensures the project .gitignore contains the entry name (idempotent).

    Ownership (T5): every host-side target dir is ownership-guarded — a pre-existing dir owned
    by another uid would silently EACCES under `--userns=keep-id`, rejected with a remediation.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    args: list[str] = []
    for recipe in recipes:
        for entry in recipe.persist.entries:
            if entry.scope == "global":
                assert entry.path is not None, "global persist entry must have path"
                host_dir = persist.resolve_global_persist(entry.path)
                persist.guard_ownership(host_dir)
                args += ["-v", f"{host_dir}:{host_dir}:rw"]

            elif entry.location == "host":
                assert entry.name is not None, "non-global persist entry must have name"
                if entry.scope == "workspace":
                    host_dir = paths.persist_workspace_dir(recipe.name, project_path, entry.name)
                else:  # project
                    if paths.git_common_dir(project_path) is None:
                        _err.print(
                            f"[yellow]warning:[/yellow] recipe '{recipe.name}' persist entry "
                            f"'{entry.name}' uses scope: project, but {project_path} is not "
                            "inside a git repository — falling back to workspace scope "
                            "(keyed by the current path, not git-common-dir)."
                        )
                    host_dir = paths.persist_project_dir(recipe.name, project_path, entry.name)
                persist.guard_ownership(host_dir)
                host_dir.mkdir(parents=True, exist_ok=True)
                ctr_dir = f"{_CONTAINER_HOME_STR}/{entry.name}"
                args += ["-v", f"{host_dir}:{ctr_dir}:rw"]

            else:  # location: in_repo
                assert entry.name is not None, "non-global persist entry must have name"
                if entry.vcs == "ignored":
                    _ensure_gitignore_entry(project_path, entry.name)
                # No mount — the workspace is already mounted read-write.

    return args


# --- Shared-service sidecars (design §3/§9) ------------------------------------
#
# A recipe references a service via `mcp.servers[].service: <name>`; the assembler resolves it to a
# hatago URL-proxy entry at host.containers.internal:<port>. Something must actually RUN that
# container. Services are host-published and outlive any instance, so they are started idempotently
# (skip if already running) and are NOT torn down by `--fresh` (only the pod is).

def _svc_container(name: str, project_key: str = "") -> str:
    """Container name for a service. Project-scoped services are keyed so one runs PER project."""
    if project_key:
        return f"harnessed-svc-{name}-{project_key}"
    return f"harnessed-svc-{name}"


def _svc_project_key(svc: "ServiceDef", project_path: Path | None) -> str:
    """Per-project key for a project-scoped service — git-common-dir keyed (cross-worktree).

    Every worktree of one checkout resolves to the SAME key, so they share ONE server container
    (which is the whole point: a dolt sql-server holds an exclusive lock on its data dir, and the
    worktrees all resolve to the same in-repo `.beads`). Global services get no key.
    """
    if svc.scope != "project" or project_path is None:
        return ""
    gcd = paths.git_common_dir(project_path)
    return paths.project_hash(gcd if gcd is not None else project_path)


def _service_data_dir(
    svc: "ServiceDef", stack: str, project_path: Path, mode: str = "container"
) -> tuple[Path, str, str]:
    """Resolve a project-scoped service's data dir → (host_dir, agent_path, location).

    The service does NOT choose where its bytes live — the RECIPE does. The service names a persist
    entry (`data.persist`), the launcher finds the recipe in this stack that declares it, and
    follows that entry's placement:

      * location: in_repo → host dir is the checkout-root-anchored dir (paths.persist_in_repo_dir),
        and agents see it at the SAME path (the workspace is mounted path-preserving).
      * location: host    → host dir is the persist dir keyed per that entry's scope, and agents
        see it at $HOME/<name> (exactly where _persist_mounts puts it).

    That is the single knob: `beads/team` declares `.beads` in_repo, `beads/stealth` declares it
    host, and the same service manifest follows either one.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    for recipe in recipes:
        for entry in recipe.persist.entries:
            if entry.name is None or entry.name != svc.data_persist:
                continue
            if entry.location == "in_repo":
                host_dir = paths.persist_in_repo_dir(project_path, entry.name)
                return host_dir, str(host_dir), "in_repo"
            if entry.scope == "project":
                host_dir = paths.persist_project_dir(recipe.name, project_path, entry.name)
            else:
                host_dir = paths.persist_workspace_dir(recipe.name, project_path, entry.name)
            # The AGENT-visible path genuinely differs by mode, and only for `location: host`: in a
            # pod the entry is bind-mounted at $CONTAINER_HOME/<name>, while a host launch has no
            # mount at all and the agent sees the real persist dir. Returning the container path
            # unconditionally (bd harnessed-5ek) meant any host-mode consumer got
            # `/home/harnessed/<name>` — a path that does not exist on the machine it would be used
            # on. Same two-modes-disagree problem `{persist:<name>}` solves for recipe `env:`.
            agent_dir = str(host_dir) if mode == "host" else f"{_CONTAINER_HOME_STR}/{entry.name}"
            return host_dir, agent_dir, "host"

    raise SchemaError(
        f"service '{svc.name}' declares data.persist: '{svc.data_persist}', but no recipe in stack "
        f"'{stack}' declares a persist entry with that name"
    )


def svc_socket_env(stack: str, project_path: Path, mode: str = "container") -> dict[str, str]:
    """Container-side socket path for each socket-backed project-scoped service in the stack.

    Exported into the attach shell (see _init_shell_prologue) as HARNESSED_<NAME>_SOCKET so a
    recipe's `setup:` can reference the socket without recomputing the launcher's path arithmetic —
    e.g. `bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET"`. A service
    reached over a published port uses `client_env` (svc_client_env) instead — the port is not a
    path, and it is not known until the container is running.
    """
    env: dict[str, str] = {}
    for name in _service_refs(stack):
        svc = load_service(None, name)
        if not (svc.scope == "project" and svc.is_socket_only):
            continue
        _, agent_dir, _ = _service_data_dir(svc, stack, project_path, mode)
        var = "HARNESSED_" + svc.name.upper().replace("-", "_") + "_SOCKET"
        env[var] = f"{agent_dir}/{svc.socket}"
    return env


def _svc_password(svc: ServiceDef, project_path: Path | None) -> str:
    """Machine-local shared secret for a published service — created once, reused thereafter.

    Stored under XDG state, NEVER in the service's data dir. For `location: in_repo` that dir is
    the user's repo: a secret written there is one `git add -A` from the remote, and bd's own
    `.beads/.gitignore` covers the files bd knows about, not ours. Same reasoning as D6 — the
    machine-local value stays machine-local.

    Why a password at all: `publish: ephemeral` binds the port to 127.0.0.1, which stops the LAN
    but not other local processes and other users on the box. The socket form got its access
    control from filesystem permissions on the data dir; a TCP port has none, so it has to
    authenticate instead. 0600, and the parent dir 0700.
    """
    key = _svc_project_key(svc, project_path) or "global"
    store = paths.xdg_state_home() / "harnessed" / "svc-secrets"
    store.mkdir(parents=True, exist_ok=True)
    store.chmod(0o700)
    secret = store / f"{svc.name}-{key}"
    if not secret.is_file():
        # token_urlsafe, not a hash of the project path: the path is guessable, a secret must not be.
        secret.write_text(secrets.token_urlsafe(24), encoding="utf-8")
        secret.chmod(0o600)
    return secret.read_text(encoding="utf-8").strip()


# High ports, above everything IANA-registered and above the usual container-runtime scratch, so a
# stable allocation is unlikely to sit where something else later wants a fixed port.
_STABLE_PORT_RANGE = (20000, 59999)


def _port_is_free(port: int) -> bool:
    """Can we bind 127.0.0.1:<port> right now? Only ever used to REJECT a candidate."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _svc_stable_port(svc: "ServiceDef", project_path: Path | None) -> int:
    """The permanent host port for a `publish: stable` service — allocated once, reused forever.

    This is the difference between a port harnessed knows and a port the PROJECT knows. An ephemeral
    publish is re-read from `podman port` at every launch and deliberately never written down, so
    nothing outside a harnessed launch can be configured with it: a plain `bd` in the repo, a
    `claude` the user started themselves, a hook. Persisting the port is what lets the project's own
    mise.local.toml carry a beads config that is still correct after a reboot or a `--fresh`.

    ONE machine-wide registry (paths.svc_ports_file), taken under an exclusive lock, because two
    launches racing in different projects must not be handed the same number. An entry is kept even
    when the port is momentarily unbindable — that is the normal case, since OUR OWN sidecar is
    usually holding it. It is only re-allocated when the recorded port is unusable AND no container
    of ours is listening on it, which is the "something else moved in while we were away" case.
    """
    key = f"{svc.name}-{_svc_project_key(svc, project_path) or 'global'}"
    registry_path = paths.svc_ports_file()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                registry = {}
            existing = registry.get(key)
            if isinstance(existing, int):
                return existing
            taken = {p for p in registry.values() if isinstance(p, int)}
            for _ in range(200):
                candidate = secrets.randbelow(_STABLE_PORT_RANGE[1] - _STABLE_PORT_RANGE[0] + 1)
                candidate += _STABLE_PORT_RANGE[0]
                if candidate in taken or not _port_is_free(candidate):
                    continue
                registry[key] = candidate
                registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True), "utf-8")
                return candidate
            raise SchemaError(
                f"could not allocate a free host port for service '{svc.name}' after 200 tries "
                f"in {_STABLE_PORT_RANGE[0]}-{_STABLE_PORT_RANGE[1]}"
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _svc_published_port(rt: str, cname: str, ctr_port: int) -> int:
    """Host port the runtime chose for `ctr_port`, via `podman port` — 0 if it cannot be read.

    The single source of truth for an ephemeral publish. Deliberately not cached anywhere: the
    port changes whenever the container is recreated, and a stale copy in a file or an env var is
    exactly the failure the socket design was avoiding when it refused to persist its own path.
    """
    result = subprocess.run(
        [rt, "port", cname, str(ctr_port)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return 0
    # `podman port <c> 3307` prints e.g. "127.0.0.1:49183"; may print several lines (one per
    # published address family). Take the first that parses.
    for line in result.stdout.splitlines():
        _, _, tail = line.strip().rpartition(":")
        if tail.isdigit():
            return int(tail)
    return 0


def svc_client_env(stack: str, project_path: Path, mode: str = "container") -> dict[str, str]:
    """Resolve each project-scoped service's `client_env` for this launch.

    The service declares what its clients need (`BEADS_DOLT_SERVER_PORT: "{port}"`); this fills in
    the values that only exist once the container is running. Templated rather than hard-coded in
    the launcher so `launcher` knows "a service declares client env", not "beads wants
    BEADS_DOLT_SERVER_PORT" — the same separation `data.persist` gives placement.

    `{host}` differs by mode and that is the entire reason this is resolved per launch rather than
    baked: a host agent dials 127.0.0.1, a containerized agent dials host.containers.internal, and
    both mean the same published port.
    """
    env: dict[str, str] = {}
    for name in _service_refs(stack):
        svc = load_service(None, name)
        if svc.scope != "project" or not svc.client_env:
            continue
        values = {
            "host": "127.0.0.1" if mode == "host" else "host.containers.internal",
            "password": _svc_password(svc, project_path) if svc.wants_password else "",
        }
        if svc.is_socket_only:
            _, agent_dir, _ = _service_data_dir(svc, stack, project_path, mode)
            values["socket"] = f"{agent_dir}/{svc.socket}"
        if svc.is_stable_port:
            # No `podman port` round-trip: harnessed chose this number, so it already knows it —
            # and it stays knowable when the container is stopped, which is exactly when a plain
            # `bd` in the project still needs a configured environment.
            values["port"] = str(_svc_stable_port(svc, project_path))
        if svc.is_ephemeral_port:
            cname = _svc_container(svc.name, _svc_project_key(svc, project_path))
            port = _svc_published_port(_runtime(), cname, svc.port)
            if not port:
                # No silent fallback to a plausible-looking default. A wrong port here is the
                # 2026-07-19 shape: the client cannot reach the server, bd's auto-start is what
                # would normally paper over it, and auto-start is exactly what we disable.
                _err.print(
                    f"[yellow][WARNING][/yellow] service '{svc.name}': could not read the "
                    f"published port for {cname}; clients will not be configured"
                )
                continue
            values["port"] = str(port)
        for key, template in svc.client_env.items():
            env[key] = template.format(**values)
    return env


def _service_refs(stack: str) -> list[str]:
    """Distinct service names a stack requires as host-published sidecars.

    Three sources, unioned (first-seen order, de-duped): (1) recipe `service:` MCP-server refs
    (the assembler proxies these by URL), (2) recipe `services:` — sidecars a RECIPE requires that
    have no MCP surface, and (3) the stack's own `services:` list. (2) is what lets a bare recipe
    list describe a working stack: a `dolt sql-server` speaks MySQL, not MCP, so it can never be a
    `service:` MCP ref, and before harnessed-7rx.1 only a stack could attach it. All three feed
    `_ensure_services`, which starts each one idempotently at launch.
    """
    stk, recipes = load_stack_with_recipes(None, stack)
    names: list[str] = []
    for recipe in recipes:
        for server in recipe.servers:
            if server.service and server.service not in names:
                names.append(server.service)
        for name in recipe.services:
            if name not in names:
                names.append(name)
    for name in (stk.services if stk else []):
        if name not in names:
            names.append(name)
    return names


def _build_service_image(rt: str, name: str) -> None:
    """Build a service image (layer-cached: no-op when the Dockerfile is unchanged).

    Always called from _build_stack so service images are ready before first run. Also called from
    _ensure_service when the image is simply missing at run time.

    When a corporate proxy CA cert is configured, a temp Dockerfile is generated with the CA trust
    block injected after the first RUN (typically the apt-get install step), so subsequent HTTPS
    downloads (curl/pip/pnpm/etc.) succeed through SSL-inspecting proxies.

    Built once per process (_build_shared_once): two stacks in the same `harnessed build` may
    reference the same service, and under `--jobs > 1` they would otherwise race to build one tag.
    """
    svc = load_service(None, name)
    svc_dir = paths.find_in_catalog("services", name)
    orig_dockerfile = svc_dir / "Dockerfile"

    def build() -> None:
        _say(f"[blue][INFO][/blue] Building service image {svc.image} ...")
        tmp = _service_dockerfile_with_ca(orig_dockerfile)
        try:
            effective = tmp if tmp else orig_dockerfile
            # Use a temp dir as build context so podman's --secret temp files (podman-build-secret-*)
            # land in /tmp rather than in svc_dir's parent, which may be repo-tracked.
            with tempfile.TemporaryDirectory() as build_ctx:
                shutil.copytree(svc_dir, build_ctx, dirs_exist_ok=True)
                _run([rt, "build", "-t", svc.image, "-f", str(effective),
                      *_corp_proxy_ca_secret_args(), build_ctx])
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    _build_shared_once(svc.image, build)


_SVC_CONFIG_HASH_LABEL = "harnessed.svc-config-hash"
_SVC_STACK_LABEL = "harnessed.svc-stack"


def _svc_run_cmd(
    rt: str,
    svc: "ServiceDef",
    cname: str,
    stack: str,
    project_path: Path | None,
    mount_path: Path | None,
) -> list[str]:
    """The exact `<rt> run` argv for this sidecar, minus the config-hash label.

    PURE BY CONTRACT — no mkdir, no ownership guard, no placement assert. It is called twice: once on
    the create path (where `_ensure_service` runs those side effects first), and once on the CHECK
    path against an ALREADY-RUNNING container, to work out what the current code *would* create.
    Side effects on the second call would fire for a container nobody is touching.

    Everything that a container fixes at CREATE time — mounts, published ports, env, userns — is in
    here, which is what makes hashing this argv a faithful fingerprint of the running container's
    configuration (`_svc_config_hash`).
    """
    run_cmd = [rt, "run", "-d", "--name", cname, *_corp_proxy_ca_mount_args()]
    if svc.is_ephemeral_port:
        # 127.0.0.1 with NO host port: the runtime allocates. That is the whole dynamic-port
        # story — N project-scoped sidecars can never collide, and nothing is written down to go
        # stale, because the port is read back with `podman port` at every launch.
        #
        # Loopback-bound, not 0.0.0.0: an unqualified `-p` publishes on every interface, which
        # would put a project's issue database on the LAN.
        run_cmd += ["-p", f"127.0.0.1::{svc.port}"]
    elif svc.is_stable_port:
        # Same loopback binding, but the host side is OURS and permanent (_svc_stable_port), so the
        # value can be written into the project and still be right next week. Ephemeral cannot.
        run_cmd += ["-p", f"127.0.0.1:{_svc_stable_port(svc, project_path)}:{svc.port}"]
    elif not svc.is_socket_only:
        run_cmd += ["-p", f"{svc.port}:{svc.port}"]
    if svc.wants_password:
        # Generic name: the launcher provisions a secret, the ENTRYPOINT decides what to call it
        # in its own protocol's terms. Same layering as client_env.
        run_cmd += ["-e", f"HARNESSED_SVC_PASSWORD={_svc_password(svc, project_path)}"]

    if svc.scope == "project":
        assert project_path is not None  # guarded by the caller
        host_dir, _, location = _service_data_dir(svc, stack, project_path)
        # keep-id: the service writes as the invoking user, so bind-mounted bytes stay host-owned
        # (a dolt data dir written by a foreign uid would EACCES for every agent container).
        run_cmd += ["--userns=keep-id", "-v", f"{host_dir}:/data:rw"]
        # Path-preserving mirror: a host-side client (e.g. `bd`) that passes its absolute path to
        # the containerised Dolt server (e.g. via `CALL dolt_backup('add', ..., '<abs-path>')`)
        # will have Dolt resolve that path against the CONTAINER filesystem. Without this second
        # mount the parent dirs (e.g. `.bare/`) are absent from the container and any mkdir inside
        # them fails with EACCES from the unprivileged `harnessed` user trying to create a
        # root-owned stub. Mounting host_dir at its own absolute path gives the container the same
        # view the host has, so the path resolves to the same already-mounted rw directory.
        run_cmd += ["-v", f"{host_dir}:{host_dir}:rw"]
        # No HARNESSED_SOCKET_PATH: it existed solely so the beads-server entrypoint could stamp the
        # client-visible socket into .beads/metadata.json, and that writer is gone (metadata.json is
        # tracked, the socket path is machine-local — BEADS.md §4). Clients now learn the socket from
        # their own environment, which the recipes resolve through the same persist entry, so nothing
        # has to be passed into the server for the clients' benefit.
        if location == "in_repo" and mount_path is not None:
            # The git repo itself — remote git traffic (bd's `dolt clone` of refs/dolt/data at init,
            # and `bd dolt push` at sync) runs HERE, because bd shells out to a dolt CLI that only
            # routes to a server on its own loopback. That means the CLONE and the PUSH happen in
            # this container, so it needs exactly what an agent container needs to reach the remote:
            # the repo, the host's git identity, the SSH agent, AND the rest of the ssh surface.
            #
            # The last one is the whole point of using the shared helpers rather than an ad-hoc pair
            # of mounts (which is what this used to be, and it broke):
            #   * `~/.ssh/config` + `*.pub` — a repo whose git config pins an identity
            #     (`core.sshCommand = ssh -o IdentityAgent=... -i ~/.ssh/<key>.pub`, the 1Password
            #     multi-account pattern) resolves that `-i` path INSIDE this container. Absent, ssh
            #     warns "Identity file ... not accessible" and falls back to the agent's FIRST key —
            #     a different GitHub account — and the remote answers `ERROR: Repository not found.`
            #     even though the very same clone works from an agent container.
            #   * git identity via `_git_identity_config_mount`, which honours `~/.config/git/`
            #     (XDG) as well as legacy `~/.gitconfig`. The old code mounted only the latter, so a
            #     host that uses the XDG path gave this container NO git config at all — no
            #     user.email, no `includeIf` per-org identity, no signing key.
            run_cmd += ["-v", f"{mount_path}:{mount_path}:rw",
                        "-e", f"HARNESSED_PROJECT_DIR={project_path}"]
            home = Path.home()
            run_cmd += _ssh_agent_args(home, _gpg_ssh_socket(), rt=rt)
            run_cmd += _git_identity_config_mount(home)
            # Non-secret surface (config/known_hosts/*.pub) always; private keys only when the stack
            # opted in AND the stack came from the user's own overlay — same gate as the agent
            # container (_trusted_ssh_keys), so a shared-catalog stack can never mount your key.
            stk, _ = load_stack_with_recipes(None, stack)
            keys: list[str] = []
            if stk is not None and stk.forward_git_credentials:
                keys = _trusted_ssh_keys(stk.ssh_keys, _stack_from_overlay(stack), stack)
            run_cmd += _ssh_dir_mounts(home, keys)
    elif svc.volume:
        run_cmd += ["-v", f"{svc.volume}:/data"]

    run_cmd.append(svc.image)
    return run_cmd


def _svc_config_hash(run_cmd: list[str]) -> str:
    """Fingerprint of a sidecar's create-time configuration, stamped on the container as
    `harnessed.svc-config-hash` and re-derived at every launch to detect drift.

    Same idea as the derived image's `harnessed.recipe-hash`, applied to the one thing a container
    can NEVER pick up later: `podman restart` re-runs the existing container, so mounts, ports and
    env stay frozen at whatever the code emitted the day it was created. Without this label a
    sidecar drifts arbitrarily far from the code that would create it today and nothing notices —
    which is exactly how five beads-servers ran for days without the mount that makes dolt_backup
    work (bd harnessed-ku9), each failing every backup silently.
    """
    return hashlib.sha256("\0".join(run_cmd).encode("utf-8")).hexdigest()[:12]


def _container_label(rt: str, cname: str, label: str) -> str | None:
    """One label off a container (running or stopped), or None if absent."""
    value = _inspect_id(
        rt, "container", cname,
        '{{if .Config.Labels}}{{index .Config.Labels "' + label + '"}}{{end}}',
    )
    return value or None


def _container_config_hash(rt: str, cname: str) -> str | None:
    """The `harnessed.svc-config-hash` label on a container, or None if it predates the label."""
    return _container_label(rt, cname, _SVC_CONFIG_HASH_LABEL)


def _svc_container_stack(rt: str, cname: str) -> str | None:
    """The stack a sidecar was created for, read back off the container itself.

    A `scope: project` sidecar's data dir is chosen by the STACK (which recipe declares the persist
    entry), so rebuilding one needs to know which stack made it. Recording it on the container means
    `svc recreate` does not have to ask: the answer is already there, and it is the exact stack the
    container was built from rather than a guess about which stack this folder "means". Nothing else
    on the machine records project → stack for a service.
    """
    return _container_label(rt, cname, _SVC_STACK_LABEL)


def _svc_drift_reason(rt: str, cname: str, svc: "ServiceDef", want_hash: str) -> str | None:
    """Why a RUNNING sidecar needs recreating, or None if it is current.

    Two independent kinds of staleness: the image was rebuilt under it (`_container_stale`), or its
    create-time configuration no longer matches what this code would emit (`_svc_config_hash`).
    A missing label is the second kind — the container was created before harnessed recorded any
    configuration, so it cannot be shown to match and by construction predates every fix since.
    """
    if _container_stale(rt, cname, svc.image):
        return f"the image {svc.image} was rebuilt since this container started"
    have = _container_config_hash(rt, cname)
    if have is None:
        return ("it was created before harnessed stamped service configuration, so it may predate "
                "fixes to how the container is built (mounts, ports, env)")
    if have != want_hash:
        return (f"its create-time configuration no longer matches this code "
                f"({have} != {want_hash}) — mounts, ports or env changed, and a restart cannot "
                "pick those up")
    return None


def _ensure_service(
    rt: str,
    name: str,
    stack: str = "",
    project_path: Path | None = None,
    mount_path: Path | None = None,
    force_recreate: bool = False,
) -> None:
    """Build (if missing) and start (if not running) one service sidecar.

    `scope: global` → the original shape: one container, `-p <port>:<port>`, named volume at /data.

    `scope: project` → one container per project (git-common-dir keyed), whose /data is a BIND MOUNT
    of the persist dir the owning recipe declared (see _service_data_dir), and which publishes no
    port when socket-backed. For an `in_repo` data dir the workspace is also mounted
    path-preserving, because the service needs the git repo itself: bd's `dolt push` (the
    refs/dolt/data sync) shells out to the dolt CLI, which only routes to a server on ITS OWN
    loopback — so the sync can only ever run inside this container, not in an agent container.

    If the running container is stale — the image was rebuilt under it, or its create-time
    configuration no longer matches what this code would emit (`_svc_drift_reason`) — prompts the
    user to confirm recreation before the harness launches. Data (named volume or bind mount) is
    always preserved. In headless mode the recreation proceeds automatically.

    `force_recreate` tears down a healthy container and rebuilds it through this same path — what
    `harnessed svc recreate` calls. It has to be this function and not a down+up, because a
    container's mounts and env are fixed at CREATE time: `podman restart` reuses the existing
    container and reports success while changing nothing.
    """
    svc = load_service(None, name)
    if svc.scope == "project" and project_path is None:
        _err.print(
            f"[bold red]error:[/bold red] service '{name}' is scope: project and needs a project "
            "context. Run it via a stack launch, not `harnessed svc up`."
        )
        raise typer.Exit(1)
    if not _image_exists(rt, svc.image):
        _build_service_image(rt, name)
    cname = _svc_container(name, _svc_project_key(svc, project_path))
    if svc.scope == "project":
        assert project_path is not None  # guarded above
        # BEFORE the running-container check below, not with the other workspace guards further
        # down: a HEALTHY running sidecar returns early from that check, and this migration has to
        # run for exactly the workspace that has one. It is also cheap and idempotent — after the
        # first launch the key is gone and this is a dict lookup.
        _ensure_no_stale_socket_key(svc, _service_data_dir(svc, stack, project_path)[0])
    # What the current code WOULD create — the yardstick for both the drift check below and the
    # label stamped on the new container. Built before the running-container check precisely so a
    # healthy-looking sidecar can be compared against it.
    want_cmd = _svc_run_cmd(rt, svc, cname, stack, project_path, mount_path)
    want_hash = _svc_config_hash(want_cmd)
    if _container_running(rt, cname) and not force_recreate:
        reason = _svc_drift_reason(rt, cname, svc, want_hash)
        if reason is None:
            return
        headless = os.environ.get("HARNESSED_HEADLESS", "false").lower() == "true"
        _err.print(f"[yellow]warning:[/yellow] service '{name}' needs recreating: {reason}.")
        _err.print(f"  Will run: {rt} rm -f {cname}  (data — named volume or bind mount — is preserved)")
        if not headless and sys.stdin.isatty():
            if not typer.confirm("Recreate now to continue?", default=True):
                _err.print(
                    f"[bold red]error:[/bold red] cannot launch with stale service '{name}'. "
                    f"Fix manually: harnessed svc recreate {name}"
                    + (f" --stack {stack}" if svc.scope == "project" else "")
                )
                raise typer.Exit(1)
        # fall through to start below
    # Remove the running container we just decided against, or any stopped leftover of the same name.
    subprocess.run([rt, "rm", "-f", cname], capture_output=True)
    if svc.is_socket_only:
        where = f"socket {svc.socket}"
    elif svc.is_ephemeral_port:
        where = f"127.0.0.1:<ephemeral>->{svc.port}"
    elif svc.is_stable_port:
        where = f"127.0.0.1:{_svc_stable_port(svc, project_path)}->{svc.port}"
    else:
        where = f":{svc.port}"
    _out.print(f"[blue][INFO][/blue] Starting service '{name}' on {where} ({cname})")
    if svc.scope == "project":
        assert project_path is not None  # guarded above
        # The side effects and aborts `_svc_run_cmd` deliberately does not carry, because they must
        # fire only when a container is actually about to be created.
        host_dir, _, location = _service_data_dir(svc, stack, project_path)
        persist.guard_ownership(host_dir)
        host_dir.mkdir(parents=True, exist_ok=True)
        _assert_data_dir_unlocked(svc, host_dir)
        _assert_data_dir_not_self_served(svc, host_dir)
        _assert_placement_matches(svc, location, project_path)
        _assert_placement_unchanged(svc, location, project_path)
        _assert_named_database_present(svc, host_dir)
        _ensure_dolt_autostart_disabled(svc, host_dir)

    # `want_cmd` (built above) is exactly what we run — the same argv the hash was taken over, so
    # the label a container carries always describes the argv that created it. Labels go in last,
    # before the image ref, and are NOT part of the hash: the config hash cannot contain itself, and
    # the stack is already reflected in the argv it produced (it picks the data dir), so hashing the
    # name too would only add a second way to say the same thing.
    labels = ["--label", f"{_SVC_CONFIG_HASH_LABEL}={want_hash}"]
    if stack:
        labels += ["--label", f"{_SVC_STACK_LABEL}={stack}"]
    run_cmd = [*want_cmd[:-1], *labels, want_cmd[-1]]
    _run(run_cmd, capture_output=True)
    _assert_service_running(rt, cname, svc)
    _install_corp_proxy_ca_in_container(rt, cname, best_effort=True)
    _wait_service_healthy(rt, cname, svc)



def _host_process_in_dir(exe: str, host_dir: Path) -> tuple[int, str] | None:
    """Find a HOST process named `exe` whose cwd is inside `host_dir`. None if there is none.

    Matching on cwd (not on the command line) is what makes this precise: a dolt sql-server chdirs
    into the data dir it locks, so cwd identifies the *contended resource*, whereas the port or db
    name on the command line does not.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # Other users' processes raise PermissionError here — not our contention to worry about.
            if not (entry / "cwd").resolve().is_relative_to(host_dir):
                continue
            if Path(os.readlink(entry / "exe")).name != exe:
                continue
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue  # the process exited mid-scan, or is not ours to inspect
        return int(entry.name), cmdline.strip()
    return None


def _assert_data_dir_unlocked(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort BEFORE starting a sidecar whose data dir is already locked by a host process.

    A `scope: project` service exists because it holds an exclusive on-disk lock over per-project
    data. The sidecar shape removes contention between CONTAINERS by construction — but a HOST
    process on the same data dir still wins the lock, and the sidecar then dies on startup. The
    symptom lands far from the cause: clients fail against a socket that was never created, and the
    engine's own advice ("start the server yourself") is unactionable inside an agent container that
    deliberately ships no engine binary. Catching it here keeps the diagnosis next to the problem.
    """
    if not svc.exclusive_lock:
        return
    holder = _host_process_in_dir(svc.exclusive_lock, host_dir.resolve())
    if holder is None:
        return
    pid, cmdline = holder
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot start: a host "
        f"'{svc.exclusive_lock}' process already holds {host_dir}"
    )
    _err.print(f"  PID {pid}: {cmdline}")
    _err.print("  Stop it and retry, or run this stack with --host so it uses that server instead.")
    raise typer.Exit(1)


def _assert_data_dir_not_self_served(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort when a host engine has initialized the sidecar's data dir AS a database.

    Dolt serves the *subdirectories* of its --data-dir as databases, so the beads-server entrypoint
    points it at `<data>/dolt/` and the project database lands at `<data>/dolt/<db>/`. A host `bd`
    that cannot reach a server auto-starts its own — chdir'd into that same `<data>/dolt/` and with
    NO --data-dir — and that run initializes the data dir itself as a repo. The directory is now a
    database in its own right, so ANY server later pointed at it serves exactly one database named
    `dolt`, and the project database becomes unreachable: every `bd` call dies with
    `database "<project>" not found` (errno 1049).

    Observed 2026-07-19 on harnessed's own checkout, where it survived three server restarts and
    five days. The failure is reported by the CLIENT as a missing database, and nothing in that
    message points at the data dir's shape — so the obvious readings ("the server is down", "the
    database was lost") are both wrong and both lead away from the fix.

    The signature is `repo_state.json`, NOT the mere existence of `<data>/dolt/.dolt/`: a perfectly
    healthy sql-server also creates that directory, for `sql-server.info` and a `tmp/`. Only an
    INITIALIZED repo carries `repo_state.json` (beside `noms/`, `config.json`, `stats/`). Keying on
    the directory alone would reject every healthy running server — both states were compared on
    disk before this was written.
    """
    if svc.exclusive_lock != "dolt":
        return
    data_dir = host_dir / "dolt"
    repo_state = data_dir / ".dolt" / "repo_state.json"
    if not repo_state.is_file():
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot start: {data_dir} is itself a "
        "Dolt database"
    )
    _err.print("  A host 'dolt' initialized the data dir in place. A server pointed at it serves")
    _err.print("  one database named 'dolt', so the project database is unreachable (errno 1049).")
    _err.print("  Move it aside (this preserves anything in it) and relaunch:")
    _err.print(f"    mv {data_dir / '.dolt'} {data_dir / '.dolt'}.poisoned")
    raise typer.Exit(1)


def _dolt_migration_sources(host_dir: Path, db: str) -> list[Path]:
    """Directories that hold database `db` and could be migrated into this data dir.

    Only two are guessable, and both are where the database actually ends up in practice:
      * `~/.beads/shared-server/dolt/<db>` — bd's own multi-project server, which a plain `bd init`
        adopts silently. This is where harnessed's own issues lived while every `bd` call reported
        the database missing.
      * `<data>/dolt.*/<db>` — a data dir quarantined out of the way by the self-served guard.

    Anything else is named explicitly with `--from`; guessing more widely would mean scanning the
    filesystem for something the user can point at in one argument.

    A candidate counts only if it carries `.dolt/repo_state.json` — the marker of an initialized
    repo, and the same signal `_assert_data_dir_not_self_served` keys on.
    """
    found: list[Path] = []
    for cand in [Path.home() / ".beads" / "shared-server" / "dolt" / db, *sorted(host_dir.glob(f"dolt.*/{db}"))]:
        if (cand / ".dolt" / "repo_state.json").is_file() and cand not in found:
            found.append(cand)
    return found


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _ensure_no_stale_socket_key(svc: ServiceDef, host_dir: Path) -> None:
    """Drop a `dolt_server_socket` left in metadata.json by a socket-era workspace.

    The migration for the socket→published-port reversal (BEADS.md §11). Every workspace
    initialized before it carries an absolute socket path in metadata.json, and **that key beats
    the environment on bd's data path** — verified 2026-07-26 on a real workspace, and it is a
    split inside bd rather than a precedence rule you can reason around:

        bd dolt status  → reads BEADS_DOLT_SERVER_HOST/PORT → finds the server, works
        bd list / stats → reads metadata.json dolt_server_socket → dials a socket that no longer
                          exists → "Auto-start is not supported in socket mode"

    So the workspace is hard-blocked on every data command while `status` cheerfully reports a
    healthy server. Nothing recreates the key — the entrypoint's metadata writer was deleted
    deliberately (BEADS.md §4) — so removing it once is permanent.

    This is not a workaround for the reversal; it restores the invariant §4 already stated. The key
    is an absolute host path in a file bd TRACKS, so committed it hands every teammate a path that
    cannot exist for them, and socket mode denies them the auto-start fallback. §4's words: "do not
    commit a metadata.json containing a dolt_server_socket."

    Announced when written. For `beads/team` this dirties a tracked file, and silently editing a
    file the user is about to commit is its own kind of surprise (same convention as
    `_ensure_dolt_autostart_disabled`).

    Skipped for a socket-backed service — there the key is not stale, it is the configuration.
    """
    if svc.exclusive_lock != "dolt" or svc.is_socket_only:
        return
    meta = host_dir / "metadata.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # no workspace yet, or one we did not write — leave it alone
    if not isinstance(data, dict) or "dolt_server_socket" not in data:
        return
    stale = data.pop("dolt_server_socket")
    # indent=2 + trailing newline is bd's own formatting, so the diff is one deleted line rather
    # than a whole-file reflow in a tracked file.
    meta.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _err.print(
        f"[yellow][NOTICE][/yellow] {meta}: removed stale 'dolt_server_socket' ({stale}).\n"
        "  This service is reached over a published port now; the key would have overridden that "
        "on bd's data path and blocked every command. Commit the change (see BEADS.md §11)."
    )


def _ensure_dolt_autostart_disabled(svc: "ServiceDef", host_dir: Path) -> None:
    """Turn bd's auto-start off in the workspace's own config, for everyone who touches this repo.

    `BEADS_DOLT_SERVER_SOCKET` only protects processes harnessed launched. This key protects the
    rest: a stray `bd` in a plain terminal, a git hook, a SessionStart hook — and a TEAMMATE who
    never runs harnessed at all. Without it bd starts a server chdir'd into its data dir with no
    --data-dir, which on an EMPTY data dir initializes that directory as a database and makes the
    project database permanently unreachable. A fresh clone is exactly that empty-data-dir case, so
    the teammate scenario is not hypothetical (two repos on this machine caught it independently).

    `config.yaml` is part of bd's tracked surface, so for `beads/team` this lands in a file the user
    will commit — deliberately, since the protection is only repo-wide if it is shared. Announced
    when written, because silently dirtying a tracked file is its own kind of surprise.

    Skipped when there is no workspace yet: `bd init` writes config.yaml, and the next launch adds
    the key. Additive and idempotent — an existing setting of either value is left alone, so a user
    who deliberately re-enables auto-start is not overridden on every launch.
    """
    if svc.exclusive_lock != "dolt":
        return
    cfg = host_dir / "config.yaml"
    try:
        text = cfg.read_text()
    except OSError:
        return
    if re.search(r"^\s*dolt\.auto-start\s*:", text, re.MULTILINE):
        return
    with cfg.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n# harnessed: bd auto-starts a dolt sql-server chdir'd into its data dir with no\n"
            "# --data-dir whenever it cannot reach one. On an empty data dir — a fresh clone —\n"
            "# that initializes the directory ITSELF as a database and the project database becomes\n"
            "# unreachable (errno 1049). Start the server explicitly instead: `bd dolt start`.\n"
            "dolt.auto-start: false\n"
        )
    _out.print(f"[blue][INFO][/blue] set dolt.auto-start: false in {cfg}")


def _placement_marker(project_path: Path) -> Path | None:
    """Where the active placement is recorded — inside the git COMMON dir, or None outside a repo.

    The git dir is deliberate on both counts: it is shared by every worktree of the checkout (so the
    record cannot disagree between them), and git never tracks its own internals, so this stays
    invisible — which `beads/stealth`, whose entire purpose is invisibility, requires.
    """
    gcd = paths.git_common_dir(project_path)
    return None if gcd is None else gcd / "harnessed-placement.json"


def _assert_placement_unchanged(svc: "ServiceDef", location: str, project_path: Path) -> None:
    """Abort when this service's data was last placed somewhere else, and record it when it was not.

    `_assert_placement_matches` catches only stealth-over-team, because the team dir sits at a known
    recipe-independent path while a stealth dir is keyed by recipe name plus a project hash — a team
    launch cannot enumerate where a stealth workspace might be. Recording the placement closes the
    other direction: whichever ran first leaves a note, and a later launch in the other placement is
    refused instead of silently starting a second, EMPTY workspace whose missing issues read as data
    loss.

    Deliberately not self-healing. Both placements may hold real data by the time they disagree, and
    picking one would discard the other; the user has to say which they meant.
    """
    marker = _placement_marker(project_path)
    if marker is None:
        return  # not a git checkout — nothing stable to key the record on
    try:
        seen = json.loads(marker.read_text()).get(svc.name)
    except (OSError, ValueError):
        seen = None
    if seen is not None and seen != location:
        _err.print(
            f"[bold red]error:[/bold red] service '{svc.name}' was last used with "
            f"'{seen}' placement, but this stack wants '{location}'"
        )
        _err.print("  Launching would start a second, empty workspace — your issues would simply")
        _err.print("  not appear. Use the stack matching the placement above, or, once you are sure")
        _err.print(f"  which copy you want, delete the record: rm {marker}")
        raise typer.Exit(1)
    if seen == location:
        return
    try:
        current = json.loads(marker.read_text()) if marker.is_file() else {}
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current[svc.name] = location
    # Best-effort: this record only ever PREVENTS a future mistake, so failing to write it must not
    # take down the launch in front of us (a read-only git dir, or one that does not exist yet).
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass


def _beads_metadata(host_dir: Path) -> dict | None:
    """`metadata.json` from a beads data dir, or None when there is no readable workspace there."""
    try:
        meta = json.loads((host_dir / "metadata.json").read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _assert_named_database_present(svc: "ServiceDef", host_dir: Path) -> None:
    """Abort when the workspace names a database this data dir does not contain.

    `metadata.json` records `dolt_database`, and the sidecar serves `<data>/dolt/` as its --data-dir,
    so that database MUST exist at `<data>/dolt/<name>/`. When it does not, the sidecar starts
    perfectly happily and every client then fails with `database "<name>" not found` (errno 1049) —
    a message that points at the server, not at the missing bytes, which is why the state is so hard
    to read from the client side.

    Two ways to get here, both real:
      * The workspace was pointed at ANOTHER server that holds the database — bd's own multi-project
        `~/.beads/shared-server`, for instance, which a plain `bd init` will silently adopt. The
        bytes exist, just not here; they have to be migrated in.
      * A `beads/team` checkout was cloned fresh. `metadata.json` is tracked, the Dolt bytes are not,
        so the workspace arrives naming a database that was never materialized locally. It needs
        `bd bootstrap` (or a Dolt remote that actually has data — see harnessed's own 2026-07-24
        failure, where the remote had none).

    Checked on the host, from the filesystem alone: no server, no client, no connection required.
    """
    if svc.exclusive_lock != "dolt":
        return
    meta = _beads_metadata(host_dir)
    if meta is None:
        return  # no workspace yet — first-run init owns that case, not this guard
    db = meta.get("dolt_database")
    if not db or (host_dir / "dolt" / str(db)).is_dir():
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' cannot serve this workspace: it names "
        f"database '{db}', which is not in {host_dir / 'dolt'}"
    )
    _err.print("  The sidecar would start and every 'bd' call would fail with errno 1049.")
    _err.print("  The bytes live wherever this workspace was previously pointed (commonly bd's own")
    _err.print("  ~/.beads/shared-server/dolt). Bring them in with:")
    _err.print(f"    harnessed svc migrate {svc.name} --stack <stack>")
    _err.print("  or run 'bd bootstrap' if the Dolt remote has data.")
    raise typer.Exit(1)


def _assert_placement_matches(svc: "ServiceDef", location: str, project_path: Path) -> None:
    """Abort when a host-placed (stealth) launch would ignore an in-repo (team) workspace.

    The two beads recipes differ ONLY in placement: `beads/team` puts `.beads` in the repo,
    `beads/stealth` puts it on the host outside the repo. Nothing in either one notices the other,
    so launching the stealth stack over a checkout that already carries a team workspace silently
    starts a SECOND, empty workspace — the issues do not appear, nothing errors, and the obvious
    reading ("my data is gone") is wrong.

    Only this direction is detectable from placement alone: the team dir is at a known,
    recipe-independent path under the checkout, whereas the stealth dir is keyed by recipe name and
    a project hash, so a team launch cannot enumerate where a stealth workspace might be.
    """
    if location != "host":
        return
    team_dir = paths.persist_in_repo_dir(project_path, svc.data_persist)
    if _beads_metadata(team_dir) is None:
        return
    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' is running host-placed (stealth), but "
        f"{team_dir} already holds an in-repo workspace"
    )
    _err.print("  Launching stealth here would start a second, empty workspace and your issues")
    _err.print("  would simply not appear. Use the team stack for this checkout, or move the")
    _err.print(f"  in-repo workspace aside first: mv {team_dir} {team_dir}.bak")
    raise typer.Exit(1)


def _service_container_status(rt: str, cname: str) -> str:
    """Container status ('running', 'exited', ...), or '' if the container is gone."""
    result = subprocess.run(
        [rt, "inspect", "-f", "{{.State.Status}}", cname],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _abort_dead_service(rt: str, cname: str, svc: "ServiceDef") -> None:
    """Report why a service container died and abort the launch.

    `podman run -d` returns 0 once the container is CREATED, so a service whose process dies a
    moment later leaves the launch believing it succeeded. The reason is already in the container's
    log — surface it rather than making the user go find it.
    """
    logs = subprocess.run([rt, "logs", "--tail", "20", cname], capture_output=True, text=True)
    _err.print(f"[bold red]error:[/bold red] service '{svc.name}' exited at startup ({cname})")
    detail = f"{logs.stdout}{logs.stderr}".strip()
    if detail:
        _err.print(f"[dim]--- {rt} logs --tail 20 {cname} ---[/dim]")
        _err.print(detail)
    raise typer.Exit(1)


def _assert_service_running(rt: str, cname: str, svc: "ServiceDef") -> None:
    """Fail the launch immediately if the container we just started is already dead."""
    if _service_container_status(rt, cname) != "running":
        _abort_dead_service(rt, cname, svc)


def _wait_service_healthy(rt: str, cname: str, svc: "ServiceDef", timeout: int = 60) -> None:
    """Wait for the service to accept traffic, then exec svc.healthcheck until it passes.

    Two-phase for a published service: raw TCP first (fast, 30s), then the service's own
    healthcheck (full protocol, 60s). For dolt this means waiting for MySQL-level auth readiness,
    not just the listener. Services without a healthcheck fall back to TCP only.

    A socket-backed service publishes no port, so there is nothing to TCP-probe: its healthcheck
    (exec'd in the container, where the socket lives) IS the readiness signal.

    **A healthcheck that never passes ABORTS the launch** (harnessed-dwt). It used to warn and let
    the launch continue, which closed only half of the silent-degradation class: harnessed-709 made
    a service that DIES abort, but one that starts, stays up, and never becomes usable still sailed
    through. The agent then comes up attached to a service it cannot talk to, and every command
    against it fails somewhere far away from the cause — which is exactly how a healthy system and a
    broken one became indistinguishable in the beads work of 2026-07-26.

    There is no `required:` flag. A stack does not attach a sidecar whose health it is indifferent
    to, and a warning nobody can act on is not a lesser failure, just a later one.
    """
    import socket
    import time

    if not svc.is_socket_only:
        # An ephemeral publish means svc.port is the CONTAINER port; probing it on the host would
        # test a port nothing is listening on (or worse, someone else's). Ask the runtime.
        probe_port = (
            _svc_published_port(rt, cname, svc.port) if svc.is_ephemeral_port else svc.port
        )
        for _ in range(30):
            if not probe_port:
                probe_port = _svc_published_port(rt, cname, svc.port)
            if probe_port:
                try:
                    with socket.create_connection(("127.0.0.1", probe_port), timeout=1):
                        break
                except OSError:
                    pass
            time.sleep(1)

    if not svc.healthcheck:
        return

    result = None
    for _ in range(timeout):
        result = subprocess.run(
            [rt, "exec", cname, "bash", "-c", svc.healthcheck],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        # A dead container fails the healthcheck for a reason no amount of waiting fixes: every
        # `exec` is failing because there is nothing to exec INTO. Distinguishing that from a
        # slow start is what separates "wait longer" from "abort now" — without it, a service that
        # died in its first second still burns the whole timeout before a warning nobody can act on.
        if _service_container_status(rt, cname) != "running":
            _abort_dead_service(rt, cname, svc)
        time.sleep(1)

    _err.print(
        f"[bold red]error:[/bold red] service '{svc.name}' started but never became healthy "
        f"within {timeout}s ({cname})"
    )
    # The LAST healthcheck's own output, not the container log. For an auth failure the log shows a
    # server running contentedly while the healthcheck holds the actual reason
    # (`Error 1045 (28000): Access denied for user 'root'`) — print what the check saw, or the user
    # goes looking in the one place that cannot tell them.
    detail = ""
    if result is not None:
        detail = (result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")).strip()
    if detail:
        _err.print("[dim]--- last healthcheck output ---[/dim]")
        _err.print(detail)
    _err.print(f"  Inspect with: {rt} logs --tail 50 {cname}")
    raise typer.Exit(1)


def _ensure_services(
    rt: str, stack: str, project_path: Path | None = None, mount_path: Path | None = None
) -> None:
    for name in _service_refs(stack):
        _ensure_service(rt, name, stack=stack, project_path=project_path, mount_path=mount_path)


def _collect_setup_notices(
    recipes: list[Recipe], project_path: Path, stack: str, harness: str
) -> list[Recipe]:
    """Recipes whose user-facing `setup:` notice should be shown at this launch, in recipe order.

    A recipe qualifies when:
      - it declares a `setup.condition` that, run host-side in the project dir, exits 0 — i.e. the
        manual step is STILL needed (unchanged polarity; e.g. `! bd list` is 0 until beads is set
        up). A non-zero exit means "already satisfied → suppress"; OR
      - it declares `setup:` with no `condition` and the user has not dismissed this stack's
        notices for this project (`paths.setup_dismissed_flag`).

    The dismiss flag gates ONLY unconditional notices — conditional ones always follow their
    condition. Conditions are catalog-authored shell strings; they run on the host here (not in
    the container), in the project directory, so project-scoped checks like `bd list` see the
    right state — and with the folder-env contract in env (`harnessed_env`), so a condition can
    test a real path (`[ ! -f "${MAIN_REPO_DIR}/.beads/metadata.json" ]`) instead of expanding an
    unset var to the empty string and passing falsely.
    """
    dismissed = paths.setup_dismissed_flag(stack, harness, project_path).exists()
    out: list[Recipe] = []
    for recipe in recipes:
        if recipe.setup is None:
            continue
        if recipe.setup.condition:
            proc = subprocess.run(
                ["bash", "-lc", recipe.setup.condition],
                cwd=str(project_path),
                env={**os.environ, **harnessed_env(
                    stack, project_path, harness=harness, mode="host", recipe=recipe
                )},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                continue  # condition satisfied → suppress
        elif dismissed:
            continue
        out.append(recipe)
    return out


def _prompt_setup_notices(
    recipes: list[Recipe],
    project_path: Path,
    stack: str,
    harness: str,
    *,
    allow_terminal: bool = True,
) -> bool:
    """Show aggregated user-facing `setup:` notices host-side at launch and act on the choice.

    No-op when nothing qualifies (`_collect_setup_notices`) or stdin is not a TTY (headless/CI
    cannot answer — never block a scripted launch). Otherwise prints one bullet per recipe and
    prompts: [O]k (default, just launch), [T]erminal (launch into an interactive shell instead of
    the agent, as if `--shell` were passed, so the setup step can be done in the container),
    [D]ismiss (silence this stack's unconditional notices for this project, then launch), [Q]uit
    (abort the launch, exit 0). Case-insensitive; ^C also aborts. Conditional notices keep
    reappearing until their condition is satisfied regardless of a prior dismiss.

    Returns True when the user chose [T]erminal — the caller ORs it into its `--shell` flag.
    """
    notices = _collect_setup_notices(recipes, project_path, stack, harness)
    if not notices or not sys.stdin.isatty():
        return False
    _out.print("\n[bold]Setup needed for this stack:[/bold]")
    for recipe in notices:
        assert recipe.setup is not None  # guaranteed by _collect_setup_notices
        # escape() — the summary is AUTHOR-WRITTEN PROSE, not markup. Interpolated raw, rich parses
        # any `[word]` in it as a style tag and DROPS it silently: beads/team's
        # "add `services: [beads-server]` to the stack" printed as "add `services: ` to the stack",
        # deleting the one token the instruction exists to convey (observed 2026-07-26). Silent is
        # the trap — an unknown tag is not an error, so nothing surfaces but the missing words.
        _out.print(f"  • [bold]{recipe.name}[/bold]: {escape(recipe.setup.summary)}")
        _out.print(f"    see: {escape(recipe.setup.reference)}")
    # [T]erminal means "launch into a container shell instead of the agent". A host launch has no
    # container to drop into — `host-run` does not even accept `--shell` — so offering it there would
    # be a choice that silently does nothing. Omit it rather than accept-and-ignore.
    choice = typer.prompt(
        "[O]k / [T]erminal (shell in the container) / [D]ismiss (don't show again) / [Q]uit"
        if allow_terminal
        else "[O]k / [D]ismiss (don't show again) / [Q]uit",
        default="O",
    )
    choice = choice.strip().lower()
    if choice.startswith("q"):
        raise typer.Exit(0)
    if choice.startswith("d"):
        flag = paths.setup_dismissed_flag(stack, harness, project_path)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    return allow_terminal and choice.startswith("t")


def _acknowledge_warnings() -> None:
    """Hold the terminal until the user acknowledges any warning printed during this launch.

    Call immediately before the `os.execvp` handoff. Past that point harnessed is gone and the
    agent owns the terminal: Claude Code's fullscreen renderer draws on the alternate screen
    buffer, so anything printed here is hidden until the session ends. A warning nobody reads is
    a warning that did not happen.

    Deliberately gated on warnings ONLY — `[INFO]` lines are reference material, and making every
    launch cost a keypress would be worse than the problem. Skipped when stdin is not a TTY, so
    headless/CI/capability-test launches never block (same guard as `_prompt_setup_notices`).
    """
    count = _out.warnings + _err.warnings
    if not count or not sys.stdin.isatty():
        return
    noun = "warning" if count == 1 else "warnings"
    _out.print(
        f"\n[bold yellow]{count} {noun} above.[/bold yellow] "
        "The agent is about to take over the screen — they will scroll out of view."
    )
    try:
        typer.prompt("Press Enter to continue", default="", show_default=False)
    except (EOFError, KeyboardInterrupt):
        raise typer.Exit(0) from None


# --- Typer commands ------------------------------------------------------------

# Host-native content-only backend subdirs to materialize from the assembled profile's .claude tree.
_HOST_HARNESS = "claude"  # spike scope: only claude consumes CLAUDE_CONFIG_DIR directly here.

# Breadcrumb written into every host config dir so orphan detection can reverse the project_hash.


def _host_stack_fingerprint(stack: str, recipes: list) -> str:
    """What the host config dir's content is a function of: the stack's recipe closure, plus
    harnessed's own version.

    The version is in there because a host launch has no image build to force a refresh. Change what
    `emit` writes into settings.json and the recipe closure is byte-identical, so without the version
    every existing config dir would keep serving the old output forever.
    """
    stack_dir = paths.find_in_catalog("stacks", stack)
    return f"{__version__}:{compute_recipe_hash(stack_dir / 'stack.yaml', recipes)}"


# Written INSIDE the config dir, deliberately: the stamp must die with the content it describes, so
# a hand-deleted or half-written dir reads as "no fingerprint" and rebuilds rather than being trusted.
_HOST_STACK_FINGERPRINT = ".harnessed-stack"
# `<project_hash>` dirs from the pre-8px.12 layout, now nested inside the config dir itself.
_LEGACY_PROJECT_DIR_RE = re.compile(r"^[0-9a-f]{8}$")


def _migrate_legacy_host_homes(home: Path) -> None:
    """Scrub pre-8px.12 per-project config dirs that are now nested INSIDE the config dir.

    The old key was `<stack>/<harness>/<project_hash>`; the new config dir IS `<stack>/<harness>`, so
    every old per-project dir became a child of it. They must be SCRUBBED rather than swept away by
    the rmtree below: after bd harnessed-8px.10 any of them that saw a token refresh holds a real
    `.credentials.json`, and a bare rmtree would leave that token recoverable on disk.

    Matched narrowly — an 8-hex name AND something that actually looks like a config dir — so a
    recipe that ever ships an 8-hex-named directory is not silently deleted.
    """
    if not home.is_dir():
        return
    for child in sorted(home.iterdir()):
        if not (child.is_dir() and not child.is_symlink()):
            continue
        if not _LEGACY_PROJECT_DIR_RE.match(child.name):
            continue
        if not ((child / "settings.json").is_file() or (child / ".credentials.json").exists()):
            continue  # 8-hex name but not a config dir — leave it alone
        _err.print(
            f"[blue][INFO][/blue] Migrating away a pre-8px.12 per-project config dir "
            f"({child.name}); its credential file is scrubbed, not just unlinked."
        )
        _scrub_host_home(child)


@contextmanager
def _host_home_lock(home: Path) -> Generator[None, None, None]:
    """Serialize fingerprint-check + wipe + rebuild + install for one (stack, harness).

    The window this closes is narrow by construction: with the wipe gated on the fingerprint
    (bd harnessed-8px.12), an unchanged stack never rebuilds, so two launches only contend when both
    observe a CHANGED fingerprint. Compare the behaviour it replaces, where every launch was
    destructive and a second launch could wipe a running session's config dir outright.

    Held across the installs too, not just the materialize: releasing after the rebuild would let a
    second launch see a matching stamp, skip installs, and exec the agent while the first launch's
    install scripts were still writing into the same dir.

    The lock file is a SIBLING of the config dir — anything inside it dies in the rmtree.
    `<harness>.lock` is a file, so host-gc's `is_dir()` scan skips it.
    """
    lock_path = home.parent / f"{home.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


# Files Claude Code's daemon keeps in its per-project state dir. Presence of ANY of these marks a
# directory as live daemon state rather than recipe content.
_DAEMON_STATE_MARKERS = (
    "daemon.json", "daemon.log", "daemon-auth-status.json", "daemon-auth-cooldown",
)


def _is_daemon_state(entry: Path) -> bool:
    """True when `entry` is Claude Code's own daemon/runtime state, which a rebuild must NOT delete.

    Identified by CONTENT, not by name. The daemon's per-project state dirs are opaque 8-hex-char
    keys (`51ba83b8`, `d8551d86`); matching that shape would be guesswork, and a recipe is free to
    ship a directory with any name. A directory holding `daemon.json`/`daemon.log`/`daemon-auth-*`
    is unambiguously the daemon's.
    """
    if not entry.is_dir() or entry.is_symlink():
        return False
    if entry.name == "daemon":
        return True
    return any((entry / marker).exists() for marker in _DAEMON_STATE_MARKERS)


def _clear_host_home_except_runtime(home: Path) -> None:
    """Empty the config dir the way the wholesale rmtree did — but spare live daemon state.

    bd harnessed-8px.20. `_materialize_host_home` used to `shutil.rmtree(home)`. That is right for
    RECIPE CONTENT: the wipe is what stops a recipe dropped from the stack leaving files behind
    (8px.12). It is wrong for Claude Code's own runtime state, which lives in the same directory and
    belongs to a process that may be RUNNING.

    Observed (2026-07-21): a rebuild deleted `daemon.json`/`daemon.log` out from under a daemon alive
    13h53m. ~200ms after losing its state the daemon wrote `{"status":"auth_required"}` and the
    credential file was gutted; the orphaned daemon then held `control.sock` with nothing valid
    behind it, so the next launch timed out reaching the background service. One rmtree, both bugs.

    Selective deletion rather than move-aside-and-restore: an interrupted rebuild can then never
    strand the preserved state somewhere the next launch will not look for it.
    """
    for entry in home.iterdir():
        if _is_daemon_state(entry):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()  # covers files AND symlinks (never follow one into ~/.claude)


def _materialize_host_home(prof: Path, home: Path, *, fingerprint: str | None = None) -> bool:
    """Copy the assembled profile's CONTENT layer into a host CLAUDE_CONFIG_DIR (`home`).

    Content-only: the `.claude/*` tree (skills/commands/rules/agents + CLAUDE.md) plus the
    settings.json floor — exactly what the container bind-mounts onto ~/.claude, minus the
    container-only artifacts (.mcp.json, hatago.config.json, the derived Dockerfile) which wire the
    MCP hub that does not exist host-side.

    Returns True if it (re)built, False if an up-to-date home was left untouched.

    GATED on `fingerprint` (bd harnessed-8px.12). The rebuild is still WHOLESALE — the dir stays a
    pure function of (profile + installs), so a recipe removed from the stack still cannot leave
    files behind — but it now happens only when the stack actually changed, instead of on every
    launch. That wipe-every-time was the root of three separate problems: it forced the project into
    the config-dir key (to stop one launch wiping another's live dir), it made install scripts re-run
    per project per launch (with `install.cache` existing purely to make that affordable), and it
    reset `.claude.json` — so MCP approvals and folder trust never persisted.

    Passing `fingerprint=None` keeps the old unconditional-rebuild behaviour, which is what the
    materialize-only tests want.
    """
    if fingerprint is not None:
        stamp = home / _HOST_STACK_FINGERPRINT
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    # BEFORE the rmtree: it would delete a legacy per-project dir without scrubbing its credential.
    _migrate_legacy_host_homes(home)
    if home.exists():
        _clear_host_home_except_runtime(home)
    home.mkdir(parents=True, exist_ok=True)
    src_claude = prof / ".claude"
    if src_claude.is_dir():
        # Contents of .claude/ become the config-dir root: .claude/skills -> <home>/skills, etc.
        shutil.copytree(src_claude, home, dirs_exist_ok=True)
    settings = prof / "settings.json"
    if settings.is_file():
        shutil.copy2(settings, home / "settings.json")
    return True


def _stamp_host_home(home: Path, fingerprint: str) -> None:
    """Record the fingerprint — the LAST step of a successful build, after the installs.

    Deliberately NOT written by `_materialize_host_home`: the content it certifies is not complete
    until every `install.script` has run. Stamping at the end of the copy instead meant a FAILED
    install left a matching stamp behind, so the next launch saw "unchanged", skipped both the
    rebuild and the installs, and started the agent against a permanently half-installed stack —
    silently. Seen for real: a host launch died on context-mode's install with the stamp already on
    disk (bd harnessed-8px.15).
    """
    (home / _HOST_STACK_FINGERPRINT).write_text(fingerprint + "\n", encoding="utf-8")


def _host_claude_source() -> Path:
    """The host's live claude config dir — source for auth seeding. Honors a CLAUDE_CONFIG_DIR the
    host may already run under; else the ~/.claude default."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


# Session-state subdirs SHARED with the real ~/.claude — the host analog of the container's
# bind-mounts (projects/file-history/tasks/session-env/todos), plus shell-snapshots.
_HOST_SHARED_STATE = ("projects", "file-history", "todos", "tasks", "session-env", "shell-snapshots")


def _relink(link: Path, target: Path) -> None:
    """Point `link` at `target`, replacing whatever is there (a prior symlink, file, or dir)."""
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(target)


def _scrub_host_home(home: Path) -> None:
    """Remove a host config dir, overwriting any real .credentials.json before deletion.

    Overwrites the credential file with null bytes and fsync's before unlinking, then removes the
    entire directory tree. This reduces the window in which a stranded token is recoverable from
    disk. LIMITATION: on SSDs with wear-leveling firmware the controller may have already remapped
    the underlying flash blocks, so overwrite does not guarantee physical erasure — it is better
    than a bare unlink and is the level of assurance available without raw device access.
    """
    cred = home / ".credentials.json"
    if cred.is_file() and not cred.is_symlink():
        size = max(cred.stat().st_size, 1)
        with cred.open("r+b") as fh:
            fh.write(b"\x00" * size)
            fh.flush()
            os.fsync(fh.fileno())
        cred.unlink()
    shutil.rmtree(home)


def _credentials_are_usable(path: Path) -> bool:
    """True when this credentials file actually holds a token worth propagating.

    Observed failure (real logout, 2026-07-21): `~/.claude/.credentials.json` and a stack home both
    held a GUTTED credential — the envelope intact (scopes, subscriptionType, rateLimitTier,
    refreshTokenExpiresAt) but `accessToken` and `refreshToken` empty strings and `expiresAt` 0.
    `_rescue_host_credentials` promoted it anyway, because its only guard was mtime: an emptied file
    that happens to be NEWEST overwrites a perfectly good shared token, and every stack sourcing
    from shared is then logged out. One stack going empty poisoned all of them.

    So freshness is necessary but NOT sufficient — a credential must also be usable. Unreadable or
    unparseable counts as unusable: this gate only ever decides whether to COPY a file over a
    working one, so refusing on doubt costs nothing and prevents exactly the poisoning above.

    Deliberately NOT checked: whether `expiresAt` is in the future. An expired ACCESS token is the
    normal, healthy state of a credential whose refresh token is still good — that is the case the
    whole refresh mechanism exists to serve. Rejecting it would throw away the token we most need to
    keep. Only a MISSING/EMPTY token or a zeroed expiry marks the gutted file.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    oauth = data.get("claudeAiOauth", data)
    if not isinstance(oauth, dict):
        return False
    if not (oauth.get("accessToken") or "").strip():
        return False
    if not (oauth.get("refreshToken") or "").strip():
        return False
    # expiresAt 0 accompanied the gutted file; a real credential always carries a real stamp.
    return bool(oauth.get("expiresAt"))


def _host_oauth_token_configured() -> bool:
    """True when a `CLAUDE_CODE_OAUTH_TOKEN` will reach the host agent, so the credentials file is
    dead weight and must not be maintained, shared or rescued.

    `os.environ` alone is sufficient HERE.  The container twin
    `_claude_oauth_token_configured` calls `_varlock_resolve` directly for the
    same reason this function only reads `os.environ`: both check the authoritative
    structured source rather than scanning a serialised file.  `_launch_host`
    applies `_resolve_launch_env` (varlock / `.env`) to this process at
    launcher.py:5209 BEFORE `_host_launch_plan` runs, so any token from those
    sources is already in `os.environ` by the time the credential wiring fires.
    Keep that ordering if either function moves.

    Empty is NOT configured — `export CLAUDE_CODE_OAUTH_TOKEN=` is how a shell profile turns it off,
    and reading the bare name as "configured" would retire a load-bearing credential file and log
    the user out with no way back.
    """
    return bool(os.environ.get(_OAUTH_TOKEN_VAR))


def _rescue_host_credentials() -> None:
    """Promote the newest refreshed token found in ANY host home into the shared `~/.claude` copy.

    Must run BEFORE `_materialize_host_home`, which `shutil.rmtree`s the home being launched —
    otherwise that home's copy of the token is deleted before it can be rescued.

    Scans EVERY home, not just the one being launched, because a config dir is keyed
    `<stack>/<harness>/<project>`: one stack open in three projects has three of them. Rescuing only
    the launching home would converge lazily — a token refreshed in project A would not reach the
    shared copy until project A itself relaunched, so launching project B first would still restore
    a stale token and force a login. Scanning all of them is what makes "one login everywhere" true
    across stacks and projects rather than only within one.

    `_share_host_claude_state` symlinks `home/.credentials.json` at the real `~/.claude` one so a
    refresh propagates and one login serves everywhere. That holds only while the symlink survives.
    Claude Code rewrites this file on token refresh, and the rewrite REPLACES the symlink with a
    regular file: the refreshed token lands in the stack's config dir and the shared copy never sees
    it. The next launch then wipes the config dir and re-links to the now-stale shared copy — so the
    user is logged out roughly every time the token would have refreshed (bd harnessed-8px.10).

    Evidence it is a replace and not a write-through: the shared file's mtime stayed hours behind the
    per-stack regular files that had superseded it.

    So: if the symlink is gone and what replaced it is NEWER than the shared copy, copy it back
    before the wipe. Self-healing — no exit hook, which matters because `_launch_host` hands the
    process to `os.execvpe` and never regains control.
    """
    # Under a token nothing reads this file, so promoting a copy is pure downside: the rescue exists
    # to keep a credential alive, and its worst failure mode is writing a bad candidate over the
    # user's real login. Skip it rather than run it for a file the harness ignores.
    if _host_oauth_token_configured():
        return
    root = paths.host_homes_root()
    if not root.is_dir():
        return
    # Explicit depths, never `**`: a config dir contains SYMLINKED state dirs (projects/, tasks/, …)
    # pointing back into ~/.claude, and a recursive walk risks following them out of the tree.
    # `*/*/*` is the current <stack>/<harness>/<project> layout; `*/*` catches pre-project-keying
    # homes still on disk.
    newest: Path | None = None
    for cand in (*root.glob("*/*/*/.credentials.json"), *root.glob("*/*/.credentials.json")):
        # A surviving symlink means that home's refresh propagated live — it IS the shared copy.
        if cand.is_symlink() or not cand.is_file():
            continue
        # Freshness alone is not enough: a GUTTED credential (empty tokens, expiresAt 0) is often
        # the newest file on disk, and promoting it overwrites a working shared token and logs
        # every other stack out. Never let one become the winner.
        if not _credentials_are_usable(cand):
            continue
        if newest is None or cand.stat().st_mtime > newest.stat().st_mtime:
            newest = cand
    if newest is None:
        return
    real = _host_claude_source() / ".credentials.json"
    # A shared copy that is already gutted must be HEALED even though it is newer — that is exactly
    # the state a previous poisoning leaves behind, and the mtime guard alone would preserve it
    # forever while every stack that sources from it starts logged out.
    if real.is_file() and _credentials_are_usable(real):
        if real.stat().st_mtime >= newest.stat().st_mtime:
            return  # shared copy is usable AND at least as fresh — never move a token backwards
    real.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(newest, real)
    real.chmod(0o600)


def _share_host_claude_state(home: Path) -> None:
    """Wire the stack home to the real ~/.claude for the pieces that should be SHARED — the host
    analog of the container's bind-mounts:
      * session state (projects/file-history/todos/tasks/session-env/shell-snapshots) → SYMLINKED, so
        transcripts, todos, and resumable sessions persist and also show up in your normal claude;
      * the auth token (.credentials.json) → SYMLINKED, so a refresh in either place propagates —
        one login everywhere, no stale copy.
    The account snapshot (.claude.json) is COPIED (skips onboarding) so the stack's own writes don't
    leak back into your global claude state. Config (skills/commands/rules/agents/CLAUDE.md/settings/
    .mcp.json) stays isolated per-stack (copied from the profile by _materialize_host_home)."""
    real = _host_claude_source()
    if real.resolve() == home.resolve():
        return
    real.mkdir(parents=True, exist_ok=True)
    for name in _HOST_SHARED_STATE:
        src = real / name
        src.mkdir(parents=True, exist_ok=True)  # ensure it exists so the symlink resolves
        _relink(home / name, src)
    # A configured CLAUDE_CODE_OAUTH_TOKEN takes precedence over the credentials file, so linking one
    # in maintains state nothing reads — while carrying the entire 8px.10 failure mode, because a
    # refresh replaces the symlink with a regular file and the next launch restores a stale copy.
    # The container path has refused to mount a credential file under a token since it was added
    # (`_claude_creds_seed_mount`); this is the host's missing half.
    #
    # Retire a copy an earlier no-token launch left behind, or the stale file this gate exists to
    # eliminate simply outlives the switch. ONLY the per-stack copy: `real` is the user's own login,
    # outside any stack, and deleting it would log them out of plain `claude` too.
    cred = real / ".credentials.json"
    stack_cred = home / ".credentials.json"
    if _host_oauth_token_configured():
        if stack_cred.is_symlink() or stack_cred.exists():
            stack_cred.unlink(missing_ok=True)
    elif cred.exists():
        _relink(stack_cred, cred)  # live token, shared
    # .claude.json (account/onboarding) lives NEXT TO the config dir, not inside it: at
    # $CLAUDE_CONFIG_DIR/.claude.json when that's set, else $HOME/.claude.json — NOT ~/.claude/.claude.json.
    env_ccd = os.environ.get("CLAUDE_CONFIG_DIR")
    acct = (Path(env_ccd) if env_ccd else Path.home()) / ".claude.json"
    if acct.is_file():
        shutil.copy2(acct, home / ".claude.json")  # snapshot account → skips onboarding, isolated writes


def _propagate_host_settings(profile_settings: Path, live: Path) -> None:
    """Write the freshly-computed profile settings.json over the live one WITHOUT dropping keys an
    install script wrote into it.

    Resolves a collision between two gates. `install:` scripts write into $HARNESSED_CONFIG_DIR —
    the LIVE home, not the profile — e.g. ccstatusline's `statusLine` block. Those installs are
    skipped when the stack fingerprint matches (bd harnessed-8px.12), while settings.json is
    re-propagated on every launch (bd harnessed-8px.18). A plain copy therefore deleted the
    installer's output with nothing left to put it back: the status line survived the first launch
    after a stack change and vanished on every restart after it.

    Profile keys always WIN — that is 8px.18's whole point (the host's live ~/.claude preferences
    and harnessed's required grants are recomputed each launch). ONLY keys the profile does not
    define at all are carried over. This is the host-side analogue of `emit.merge_settings` carrying
    every non-required baked key through verbatim container-side.
    """
    try:
        fresh = json.loads(profile_settings.read_text() or "{}")
        prior = json.loads(live.read_text() or "{}") if live.is_file() else {}
    except (OSError, ValueError):
        # Unparseable/unreadable on either side → fall back to the plain copy. A settings file the
        # user hand-edited into invalid JSON must not take the whole launch down with it.
        shutil.copy2(profile_settings, live)
        return
    carried = (
        {k: v for k, v in prior.items() if k not in fresh}
        if isinstance(fresh, dict) and isinstance(prior, dict)
        else {}
    )
    if not carried:
        shutil.copy2(profile_settings, live)  # nothing to preserve → byte-identical propagation
        return
    live.write_text(json.dumps({**fresh, **carried}, indent=2) + "\n")


def _host_launch_plan(
    stack: str, harness: str, project_path: Path, *, recipes: list | None = None
) -> tuple[Path, list[str], Path, bool]:
    """Materialize the host home (+ seed auth) and return (home, argv, cwd, rebuilt) WITHOUT exec'ing.

    Split out from _launch_host so the plan is verifiable in tests without handing over the TTY.

    `rebuilt` is False when the stack fingerprint matched and the existing home was left alone; the
    caller uses it to skip the install scripts, which have nothing to do (bd harnessed-8px.12).
    Passing `recipes=None` disables the gate and rebuilds unconditionally.
    """
    prof = profile_dir(stack, harness)
    home = paths.host_home(stack, harness)
    # BEFORE the materialize: if it rebuilds, it rmtree's `home`, and a token the last session
    # refreshed lives in there as a regular file that replaced our symlink (bd harnessed-8px.10).
    _rescue_host_credentials()
    fingerprint = _host_stack_fingerprint(stack, recipes) if recipes is not None else None
    rebuilt = _materialize_host_home(prof, home, fingerprint=fingerprint)
    # settings.json is the ONE profile artifact recomputed on EVERY launch, so it must be propagated
    # even when the fingerprint gate skipped the rebuild (bd harnessed-8px.18). It is not a pure
    # function of the recipe closure the fingerprint covers: `_merge_host_claude_settings` folds in
    # the host's LIVE ~/.claude preferences and re-applies harnessed's required grants each time.
    # Without this, changing your host defaultMode — or harnessed fixing what it emits — never
    # reaches the config dir until something unrelated happens to change the stack. That is exactly
    # how the 8px.17 duplicate-hook fix landed in the profile and left the live config untouched.
    # Everything else in here (skills/rules/commands/CLAUDE.md) IS a function of that closure.
    settings = prof / "settings.json"
    if settings.is_file():
        _propagate_host_settings(settings, home / "settings.json")
    _share_host_claude_state(home)
    # Content-only: no --mcp-config / --strict-mcp-config — that flag wires the (absent) hub.
    argv = ["claude"]
    return home, argv, project_path, rebuilt


def _gcd_db_name(project_path: Path) -> str:
    """Derive a unique, worktree-stable beads database name from the repo's git-common-dir:
    dirname(git-common-dir), relative-to-$HOME, lowercase, separators → '_', dropping LEADING
    components until ≤64 chars (deepest/most-specific kept); hash-suffix if even the tail overflows.
    Every worktree of a repo → the same name; different repos never collide."""
    gcd = paths.git_common_dir(project_path) or Path(project_path)
    root = gcd.parent  # dirname(git-common-dir) = the dir containing .bare/.git
    home = Path.home()
    try:
        parts = list(root.relative_to(home).parts)
    except ValueError:
        parts = [p for p in root.parts if p not in ("/", "")]
    parts = [re.sub(r"[^a-z0-9]+", "_", p.lower()).strip("_") for p in parts]
    parts = [p for p in parts if p]
    while len(parts) > 1 and len("_".join(parts)) > 64:
        parts.pop(0)  # drop leading (shallowest) first, keep the specific tail
    name = "_".join(parts) or "beads"
    if len(name) > 64:
        name = name[:55].rstrip("_") + "_" + hashlib.sha1(str(root).encode()).hexdigest()[:8]
    return name


def _repo_primitives(project_path: Path) -> dict[str, str]:
    """Repo-identity substitution values for a recipe's `setup.config` derive/prompt templates."""
    gcd = paths.git_common_dir(project_path) or Path(project_path)
    repo = gcd.parent.name if (gcd.name in (".bare", ".git") or gcd.name.endswith(".git")) else gcd.name
    return {
        "repo": re.sub(r"[^A-Za-z0-9_-]+", "-", repo).strip("-") or "repo",
        "gcd_db": _gcd_db_name(project_path),
        "gcd_hash": hashlib.sha1(str(gcd).encode()).hexdigest()[:8],
        "project_hash": paths.project_hash(project_path),
    }


def _subst(template: str, values: dict[str, str]) -> str:
    """Substitute {key} placeholders from `values`; leave unknown {…} intact."""
    return re.sub(r"\{([a-zA-Z0-9_.]+)\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _resolve_setup_config(setup, primitives: dict[str, str], *, interactive: bool) -> dict[str, str]:
    """Resolve each `setup.config` item → value: derive (silent) or prompt (asked; default when
    non-interactive). Returns primitives + {config.<key>: value}, ready for _subst into `run`."""
    values = dict(primitives)
    for item in setup.config:
        if item.derive is not None:
            val = _subst(item.derive, values)
        else:
            default = _subst(item.default or "", values)
            val = typer.prompt(_subst(item.prompt, values), default=default) \
                if (interactive and item.prompt) else default
        values[f"config.{item.key}"] = val
    return values


def _stack_tools_dirs(stack: str) -> tuple[Path, Path, Path]:
    """(tools_root, bin_dir, uv_tool_dir) for a stack's host-native tool installs.

    Stack-scoped, not global, so two stacks can pin different versions without clobbering each
    other. Shared by `provision:` (_host_provision) and `setup.script` (_script_env) so both land
    executables in ONE dir that _launch_host puts on PATH exactly once.
    """
    tools_root = paths.xdg_data_home() / "harnessed" / "tools" / stack
    return tools_root, tools_root / "bin", tools_root / "uv-tools"


def _script_env(
    stack: str,
    project_path: Path,
    values: dict[str, str],
    *,
    mode: str,
    harness: str,
    recipe=None,
    bin_dir: Path | None = None,
) -> dict[str, str]:
    """The env a recipe's `setup.script` sees — IDENTICAL keys in host and container mode.

    This is the whole point of `setup.script` over `setup.run`: `run` received its inputs by
    `{config.<key>}` string substitution, which only works host-side where the launcher can template
    the command. A script file cannot be templated, so every input arrives as an env var instead,
    and the same file is then runnable in both modes.

    `HARNESSED_PROJECT_DIR` is mode-invariant for free: _build_mount_args bind-mounts the project at
    its own host path (`-v {mount_path}:{mount_path}`, MNT2-02), so the absolute path is the same
    string on both sides. The repo-identity values are NOT recomputable in the container (the git
    common dir — `.bare/` — is outside the mount), so they are computed host-side and injected.
    """
    env: dict[str, str] = {
        **harnessed_env(stack, project_path, harness=harness, mode=mode, recipe=recipe,
                        sockets=False),
        "HARNESSED_MODE": mode,
        "HARNESSED_STACK": stack,
        "HARNESSED_PROJECT_DIR": str(project_path),
        "HARNESSED_HOST_HOME": str(Path.home()),
    }
    for key, val in values.items():
        if key.startswith("config."):
            env[f"HARNESSED_CFG_{key[len('config.'):].upper()}"] = val
        else:  # repo-identity primitives: repo, gcd_db, gcd_hash, project_hash
            env[f"HARNESSED_{key.upper()}"] = val
    if bin_dir is not None:
        # A script installs a tool and then immediately CONFIGURES it (the seam `provision:` cannot
        # express, e.g. serena's `uv tool install` + `serena init`). That only works if the freshly
        # installed executable is already resolvable, so bin_dir leads the script's own PATH.
        env["HARNESSED_BIN_DIR"] = str(bin_dir)
        env["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    return env


_CTR_SETUP_DIR = "/opt/harnessed/setup"
# Single-sourced so $HARNESSED_RECIPE_DIR names the same container path for both consumers — the
# install executor's bind-mount (_run_container_installs) and setup.script's (_setup_script_mounts).
# Both are runtime bind-mounts since bd harnessed-8px.21.4; install's used to be a build-time COPY.
_CTR_RECIPE_DIR = emit.CTR_RECIPE_DIR


def _setup_script_mounts(recipes) -> list[str]:
    """`-v …:ro` args placing each recipe's `setup.script` — and the recipe dir it came from —
    inside the container.

    A MOUNT, not a Dockerfile COPY, on purpose: the script is authorable catalog content, so editing
    it must not require an image rebuild — and the image stays untouched by this whole mechanism.
    The recipe dir rides along because a script does `cp` where a Dockerfile did `COPY`; it is the
    container-side value of $HARNESSED_RECIPE_DIR (see `harnessed_env`).
    """
    args: list[str] = []
    for recipe in recipes:
        if recipe.setup and recipe.setup.script:
            src = recipe.root / recipe.setup.script
            args += ["-v", f"{src}:{_CTR_SETUP_DIR}/{recipe.name}.sh:ro"]
            args += ["-v", f"{recipe.root}:{emit.CTR_RECIPE_DIR}/{recipe.name}:ro"]
    return args


def _pending_setup_scripts(project_path: Path, recipes) -> list:
    """Recipes carrying a `setup.script`.

    `setup.condition` is deliberately NOT consulted here. A condition is a FIRST-RUN gate written
    against the state a fresh project lacks (serena's `test ! -d .serena`), so gating a script on it
    makes the script fresh-project-only: an existing project whose state is present but WRONG can
    never be corrected, because the gate that would trigger the correction is already satisfied.
    Scripts are idempotent and self-gating by contract, so they run every launch and converge.
    `condition` keeps its original job — gating the user-facing notice (_prompt_setup_notices).
    """
    pending = []
    for recipe in recipes:
        setup = recipe.setup
        if not (setup and setup.script):
            continue
        pending.append(recipe)
    return pending


_MISE_MARKER = "# managed by harnessed"


def _write_project_tool_env(stack: str, project_path: Path) -> None:
    """Give the PROJECT the same tool env harnessed gives the agent, via mise.

    The gap this closes: harnessed configures the agent it launches and nothing else. Everything
    else in that repo — a `bd` you run in a terminal, a `claude` you started yourself, a hook — sees
    none of it. On 2026-07-27 that meant three live agents in one project with zero BEADS_
    variables, each falling back to bd's auto-start, each hitting the sidecar's exclusive lock.

    Two files, and which value lives in which is the whole design:

      * A dotenv OUTSIDE the repo ($XDG_STATE_HOME, 0600) holds the values, INCLUDING the service
        password. Credentials are referenced, never replicated — a secret copied into the source
        tree is one `git add -f`, one backup, one tree-walking tool away from leaving the machine,
        and `mise.local.toml` being gitignored is not the same guarantee as not being there.
      * `mise.local.toml` in the repo holds only a POINTER to it (`[env] _.file`). mise loads it for
        any process whose CWD is under the project, which is exactly the audience that was missing.

    Only ever CREATES `mise.local.toml`; an existing one is never rewritten. A user's mise config is
    theirs, TOML has no safe blind-append (a second `[env]` table is a parse error), and silently
    reformatting it would be a worse bug than the one this fixes. When it exists without our pointer
    we print the two lines to add and move on.

    Requires every value to be stable — a `publish: ephemeral` port would be written down and be
    wrong after the next container recreate, which is why beads-server is `publish: stable`.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    values = {
        **_recipe_env(recipes, project_path, mode="host"),
        **svc_client_env(stack, project_path, "host"),
    }
    if not values:
        return

    gcd = paths.git_common_dir(project_path)
    env_file = (
        paths.xdg_state_home() / "harnessed" / "project-env"
        / f"{paths.project_hash(gcd or project_path)}.env"
    )
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.parent.chmod(0o700)
    body = "".join(f"{k}={v}\n" for k, v in sorted(values.items()))
    env_file.write_text(f"# {_MISE_MARKER} — regenerated every launch. Do not edit.\n{body}", "utf-8")
    env_file.chmod(0o600)

    mise_local = project_path / "mise.local.toml"
    pointer = f'[env]\n_.file = "{env_file}"\n'
    if not mise_local.exists():
        mise_local.write_text(
            f"{_MISE_MARKER}: this file is NOT committed (see .gitignore). It points mise at the\n"
            f"# tool env for this project, so `bd` and friends work in a plain terminal too.\n"
            f"{pointer}",
            encoding="utf-8",
        )
        _say(f"[blue][INFO][/blue] wrote {mise_local.name} — `bd` now works in a plain shell here")
    elif str(env_file) not in mise_local.read_text(encoding="utf-8"):
        _say(
            f"[blue][INFO][/blue] {mise_local.name} exists and is yours to edit; to configure this "
            f"project's tools for a plain shell, add:\n    {pointer.rstrip()}"
        )
    _ensure_gitignore_entry(project_path, "mise.local.toml")


def _recipe_env(recipes, project_path: Path, *, mode: str) -> dict[str, str]:
    """Every recipe's `env:` resolved for one mode — the SINGLE declaration behind all three
    consumers (build-time install step, setup script, and the agent process itself).

    Later recipes win on a clash, matching the Dockerfile layering this replaces (a later `ENV` for
    the same name overrides an earlier one), so stack recipe order stays the tie-breaker.
    """
    env: dict[str, str] = {}
    for recipe in recipes:
        env.update(resolve_recipe_env(recipe, mode=mode, project_path=project_path))
    return env


def _container_setup_env(stack: str, project_path: Path, pending, *, harness: str) -> dict[str, str]:
    """The setup env for a container launch, resolved HOST-side (a `setup.config` item may PROMPT,
    which has to happen before the container starts) and set as REAL CONTAINER ENV.

    Deliberately not `podman exec -e`: same reasoning as `socket_env` above — a var that exists only
    on one exec is invisible to hooks and to every other process in the container. Setting it on the
    container makes the whole box agree, so a hook or a later `podman exec` sees the same values the
    setup script did.
    """
    if not pending:
        return {}
    primitives = _repo_primitives(project_path)
    env: dict[str, str] = {}
    for recipe in pending:
        values = _resolve_setup_config(recipe.setup, primitives, interactive=sys.stdin.isatty())
        env.update(_script_env(
            stack, project_path, values, mode="container", harness=harness, recipe=recipe
        ))
    return env


def _run_container_setups(
    rt: str, inst: str, pending, stack: str, project_path: Path, *, harness: str
) -> None:
    """Execute each pending `setup.script` inside the running container.

    The env it needs is already ON the container (_container_setup_env → `podman run -e`), so this
    exec passes none. Runs BEFORE the egress firewall closes, since a first-run setup is exactly the
    step that downloads things (serena's language servers, etc.).
    """
    for recipe in pending:
        if not _confirm_setup(recipe, stack, project_path, harness=harness):
            continue
        _err.print(f"[blue][INFO][/blue] setup ({recipe.name}): {recipe.setup.script} (container)")
        proc = _run([rt, "exec", inst, "bash", f"{_CTR_SETUP_DIR}/{recipe.name}.sh"], check=False)
        if proc.returncode != 0:
            _err.print(f"[bold red]error:[/bold red] setup for '{recipe.name}' failed in container")
            raise typer.Exit(1)


def _confirm_setup(recipe, stack: str, project_path: Path, *, harness: str) -> bool:
    """Gate a recipe's executable setup behind `setup.confirm`. True = run it.

    Executable setup normally runs unattended on every launch whose `condition` is unsatisfied,
    which is right for a tool that writes to its own dirs and wrong for one that writes to the
    USER'S repo. `bd init` in team placement creates and COMMITS 18 files into a shared checkout —
    the reason that step stayed manual, and the reason a plain `run:` was not the answer.

    So: no `confirm` → unchanged, run it. With `confirm` → print the text and require an explicit
    yes. Declining skips only this launch; `condition` is still unsatisfied, so the offer returns
    next time rather than being silently dismissed forever.

    No TTY → SKIP, never run. A headless launch (CI, the capability test, a scripted run) cannot
    answer, and "nobody objected" is not consent for a commit into someone's repo. Same guard as
    `_prompt_setup_notices`, opposite default — that one proceeds without prompting because it only
    prints; this one would write.
    """
    setup = getattr(recipe, "setup", None)
    if setup is None or not setup.confirm:
        return True
    # `condition` is consulted HERE even though `_pending_setup_scripts` refuses to consult it. That
    # refusal is about scripts converging state every launch, which is right — but a script behind a
    # `confirm` cannot run unattended anyway, so without this gate the user would be asked to
    # authorize a repo-changing step on EVERY launch, including the ones where it is already done.
    # A prompt that fires when there is nothing to do is how people learn to answer without reading.
    # Same host-side evaluation, same env contract, as _collect_setup_notices.
    if setup.condition and subprocess.run(
        ["bash", "-lc", setup.condition],
        cwd=str(project_path), capture_output=True,
        env={**os.environ, **harnessed_env(
            stack, project_path, harness=harness, mode="host", recipe=recipe
        )},
    ).returncode != 0:
        return False
    if not sys.stdin.isatty():
        _err.print(
            f"[yellow]warning:[/yellow] skipping setup for '{recipe.name}' — it needs confirmation "
            "and there is no terminal to ask. Run this launch interactively to complete it."
        )
        return False
    # escape() for the same reason _prompt_setup_notices escapes its summary: this is author-written
    # prose, and rich silently DROPS any `[word]` in it as an unknown style tag.
    _out.print(f"\n[bold yellow]Setup for {recipe.name} will change this repository:[/bold yellow]")
    _out.print(f"  {escape(setup.confirm)}")
    try:
        return typer.confirm("Proceed?", default=False)
    except (EOFError, KeyboardInterrupt):
        raise typer.Exit(0) from None


def _host_tool_shims_dir(stack: str) -> Path:
    """Where a host launch's `tools:` binaries become resolvable (bd harnessed-1t4.3).

    mise's shims dir under the STACK's own data dir — not `~/.local/share/mise/shims`, which belongs
    to the user. `_launch_host` puts this on PATH next to the stack bin dir.
    """
    return _stack_tools_dirs(stack)[0] / "mise" / "shims"


def _host_mise_env(stack: str) -> dict[str, str]:
    """The redirect that points mise at the STACK's own instance instead of the user's.

    Needed in TWO places, and shipping it to only one is the bug this exists to prevent: a mise
    shim is a symlink to the mise binary, so it re-resolves the tool by argv[0] against mise's
    data dir AT RUN TIME. Install-time redirection alone puts the binary somewhere the shim can
    never find it again — `mise ERROR <tool> is not a valid shim`, because mise fell back to
    ~/.local/share/mise where the stack installed nothing.

    So _launch_host exports this alongside the PATH entry for `_host_tool_shims_dir`: a shims dir
    on PATH without this env is a dir of guaranteed-broken symlinks.
    """
    mise_root = _stack_tools_dirs(stack)[0] / "mise"
    return {
        "MISE_DATA_DIR": str(mise_root),
        "MISE_CONFIG_DIR": str(mise_root / "config"),
        "MISE_STATE_DIR": str(mise_root / "state"),
    }


def _host_install_tools(stack: str, recipes) -> None:
    """Install the stack's declarative `tools:` HOST-side — the host half of the derived image's
    merged `RUN mise use -g … && mise install` layer (bd harnessed-1t4.3).

    Without this, `tools:` was honoured in exactly ONE place (emit.write_derived_dockerfile), so
    moving a recipe's tool install out of its `install.sh` and into `tools:` would have deleted that
    binary from every `launch --host` — silently, which is the harnessed-8px.1 failure shape.

    Everything mise touches is redirected into the stack's own tools tree. That redirection is the
    whole reason this is possible at all: rtk's install.sh refused to use mise on a host launch
    precisely because mise's global config and data dir belong to the user, and harnessed does not
    write there. Same tool specs, same sorted order, same pins as the container layer.

    mise absent on the host is announced with the tools it could not deliver, never silent.
    """
    specs = sorted({t for recipe in recipes for t in recipe.tools})
    if not specs:
        return
    if not shutil.which("mise"):
        _err.print(
            "[bold yellow]WARNING[/bold yellow] tools: mise is not on PATH, so these pinned tools "
            f"are NOT installed for this host launch: {', '.join(specs)}. Install mise "
            "(https://mise.jdx.dev) or run this stack in a container."
        )
        return
    mise_root = _stack_tools_dirs(stack)[0] / "mise"
    mise_root.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        **_host_mise_env(stack),
        # NOT redirected: the download cache is a cache. Sharing the user's means a host launch and a
        # container build (which mounts the same kind of cache) both stop re-downloading.
        #
        # Same override, same reason, as the container `tools:` layer — see the long note in
        # emit.write_derived_dockerfile. mise's default `npm:` backend (`aube`) vetoes an install
        # when ANY transitive dep lacks publisher-trust evidence, which kills correctly-pinned
        # packages that have no newer release to move to. pnpm keeps the pin and the installer and
        # drops the tree-wide veto. Placed AFTER the `**os.environ` splat so it wins, but it is a
        # default a user cannot usefully countermand: with `auto` the install simply fails.
        "MISE_NPM_PACKAGE_MANAGER": "pnpm",
    }
    _err.print(f"[blue][INFO][/blue] tools: mise use -g {' '.join(specs)} (host)")
    if subprocess.run(
        ["mise", "use", "-g", *specs], env=env, cwd=str(mise_root)
    ).returncode != 0 or subprocess.run(
        ["mise", "install"], env=env, cwd=str(mise_root)
    ).returncode != 0:
        _err.print("[bold red]error:[/bold red] installing the stack's `tools:` failed")
        raise typer.Exit(1)


# Each harness's OWN config-dir variable. An upstream installer that honours one of these beats
# both `$HARNESSED_CONFIG_DIR` and the `$HOME` shim, because an explicit config-dir env var wins
# over a relocated home. Inherited from the launching process it silently redirects an install into
# whatever config dir the PARENT had — which is exactly what happens when a stack is launched from
# inside another stack's host session, since `_launch_host` exports CLAUDE_CONFIG_DIR for the agent.
#
# Demonstrated (bd harnessed-8px.26): gsd-core's install.sh, run with an inherited CLAUDE_CONFIG_DIR,
# wrote 69 skills and four top-level artifacts into an UNRELATED stack's home, ignoring the shim it
# was given.
#
# Pinned rather than unset, deliberately: unsetting makes such an installer fall back to
# `$HOME/.claude`, the user's REAL config dir, which is a worse landing spot than the parent stack's.
# Only claude is listed because `_HOST_HARNESS` scopes the host backend to claude today; add the
# others (omp's PI_*, codex, opencode, antigravity) as each gains host support.
_HARNESS_CONFIG_DIR_ENV: dict[str, tuple[str, ...]] = {
    "claude": ("CLAUDE_CONFIG_DIR",),
}


def _harness_config_env(harness: str, home: Path) -> dict[str, str]:
    """Pin the harness's own config-dir variable at this stack's home (bd harnessed-8px.26).

    Applied wherever catalog-authored content runs host-side — installs, setup scripts, and the
    `setup.condition` eval — alongside the UV_TOOL_DIR / npm_config_prefix redirection those sites
    already do. Same intent: keep what a recipe writes inside the stack's own tree.
    """
    return {var: str(home) for var in _HARNESS_CONFIG_DIR_ENV.get(harness, ())}


def _host_run_installs(stack: str, project_path: Path, *, harness: str, home: Path) -> None:
    """Run each recipe's `install.script` HOST-side — the host half of `RUN bash install.sh`.

    ORDERING IS LOAD-BEARING and the caller must not move it: this runs AFTER
    `_materialize_host_home`, which `shutil.rmtree`s `home` on EVERY launch so a removed recipe's
    files never linger. Run installs before that and their output is deleted milliseconds later —
    silently, which is precisely the failure mode of harnessed-8px.1. It also runs BEFORE
    `_host_run_setups`: install bakes content, setup configures against it.

    That per-launch wipe also rules out a "first launch only" gate: the home is new every time, so
    the install is needed every time. `install.cache` is what makes that affordable — the OUTPUT
    cannot persist but the pinned SOURCE can (see paths.install_cache_dir).

    A recipe declaring `install.system` has a component only a container build can perform (root /
    apt-get). harnessed does not sudo and does not mutate the user's system, so that component is
    skipped here — but announced, verbatim, with the recipe named. Never silently.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    installs = [r for r in recipes if r.install]
    if not installs:
        return
    _, bin_dir, uv_tool_dir = _stack_tools_dirs(stack)
    # The `$HOME` shim an installer that only writes "globally" runs under. Created once and RELINKED
    # each launch: `home` is rmtree'd and rebuilt every time, so the symlink must be re-pointed at the
    # new inode even though the path string is unchanged.
    home_shim = paths.host_home_shim(home)
    home_shim.mkdir(parents=True, exist_ok=True)
    _relink(home_shim / ".claude", home)
    recipe_env = _recipe_env(installs, project_path, mode="host")
    for recipe in installs:
        inst = recipe.install
        if inst.system:
            _err.print(
                f"[bold yellow]WARNING[/bold yellow] install ({recipe.name}): container-only step "
                f"SKIPPED on a host launch — {inst.system}. harnessed will not sudo or otherwise "
                "write outside its own directories; run this stack in a container to get it."
            )
        if inst.script is None:
            # ROOT-ONLY install (`system:` with no script): the warning above IS the whole host-side
            # behaviour. Schema guarantees a script-less install carries a reason, so this is never
            # a silent skip.
            continue
        cache = paths.install_cache_dir(recipe.name, inst.cache) if inst.cache else None
        if cache is not None:
            # Create the PARENT only. The cache dir's own existence is the script's hit/miss test.
            cache.parent.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
        home.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(recipe_env)   # recipe `env:` beats the inherited environment …
        env.update(emit.install_env(  # … and the harnessed-owned contract beats BOTH. Same
            recipe, mode="host", harness=harness,  # winner as container mode, where the inline
            config_dir=str(home),                  # RUN assignments beat the preceding ENV lines.
            cache_dir=str(cache) if cache else "",
            bin_dir=str(bin_dir),
            home_shim=str(home_shim),
        ))
        # Host-only, mirroring _host_run_setups: keep any tool an install lands in the stack tree
        # rather than the user's global one.
        env["UV_TOOL_DIR"] = str(uv_tool_dir)
        env["UV_TOOL_BIN_DIR"] = str(bin_dir)
        env["npm_config_prefix"] = str(bin_dir.parent)
        env["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
        # LAST, so an inherited CLAUDE_CONFIG_DIR cannot survive into the script (bd 8px.26).
        env.update(_harness_config_env(harness, home))
        _err.print(f"[blue][INFO][/blue] install ({recipe.name}): {inst.script} (host)")
        if subprocess.run(
            ["bash", str(recipe.root / inst.script)], cwd=str(project_path), env=env
        ).returncode != 0:
            _err.print(f"[bold red]error:[/bold red] install for '{recipe.name}' failed")
            raise typer.Exit(1)


# Shell bookkeeping, not anything a recipe meant to export. `_` and OLDPWD change on their own; PWD
# is the init shell's cwd (the project) and would silently relocate the agent.
_INIT_ENV_IGNORE = frozenset({"_", "SHLVL", "PWD", "OLDPWD", "__harnessed_rc"})


def _parse_env0(path: Path) -> dict[str, str]:
    """`env -0` output → dict. NUL-separated, so a value containing a newline survives intact."""
    out: dict[str, str] = {}
    for entry in path.read_bytes().decode("utf-8", "replace").split("\0"):
        key, sep, value = entry.partition("=")
        if sep and key:
            out[key] = value
    return out


def _propagate_init_env(before: Path, after: Path) -> None:
    """Apply what a recipe's `init.run` exported to `os.environ`, so the host agent inherits it.

    PATH is merged, never replaced. The launcher composed the agent's PATH deliberately (the stack's
    own tools dir leads it), while the init shell's PATH also carries whatever the user's profile
    added — assigning that wholesale would hand the agent a different toolchain than the one the
    stack installed. So only the entries init ADDED are taken, in order, and prepended.
    """
    b, a = _parse_env0(before), _parse_env0(after)
    for key, value in a.items():
        if key in _INIT_ENV_IGNORE or b.get(key) == value:
            continue
        if key == "PATH":
            seen = set(b.get("PATH", "").split(os.pathsep))
            current = os.environ.get("PATH", "")
            seen.update(current.split(os.pathsep))
            added = [p for p in value.split(os.pathsep) if p and p not in seen]
            if added:
                os.environ["PATH"] = os.pathsep.join([*added, current]) if current else \
                    os.pathsep.join(added)
        else:
            os.environ[key] = value


def _host_run_inits(stack: str, project_path: Path, *, harness: str) -> None:
    """Run each recipe's `init.run` host-side — the host half of what the attach shell does.

    Model A: init runs on EVERY launch and the command self-gates, so this needs no marker. It was
    wired only into `_init_shell_prologue`, i.e. the container attach shell, which made an `init:`
    declaration a silent no-op under `host-run` — the same container-only wiring that produced
    harnessed-2sm/-162/-5ek.

    Fail-fast, matching the container path: an agent must not start against a half-initialized tool.
    Runs AFTER `_host_run_setups`, because a setup script may be what installs the binary init calls.

    AND IT PROPAGATES THE ENV THE INIT EXPORTS. That is the whole point of Model A — the container
    path runs `init.run` as a brace group in the SAME shell that then execs the harness, precisely so
    that `export BEADS_DIR=…` reaches the agent. Host-side there is no attach shell: the agent is
    exec'd from `os.environ` (see `_launch_host`), and running init in a subprocess threw every
    export away with the subprocess. `init: run: export …` therefore did nothing at all under
    `host-run` — silently, because an export cannot fail. Observed 2026-07-26 on beads' `bd-shim`
    PATH line (installed, never on PATH); `pulumi`'s `PULUMI_HOME` had the same silent no-op.

    The delta is captured INSIDE the init shell (`env -0` before and after), not by diffing against
    what we passed in: `bash -lc` sources the user's profile first, and a profile-added variable is
    not something a recipe asked to export into the agent.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    for recipe in recipes:
        if recipe.init is None:
            continue
        _say(f"[blue][INFO][/blue] init ({recipe.name}): host")
        with tempfile.TemporaryDirectory() as td:
            before, after = Path(td) / "before", Path(td) / "after"
            # `{ …; }` (not a subshell) for the same reason the container prologue uses one, and the
            # exit status is preserved across the second capture so fail-fast still sees it.
            script = (
                f"env -0 > {shlex.quote(str(before))}\n"
                f"{{ {recipe.init.run}; }}\n"
                "__harnessed_rc=$?\n"
                f"env -0 > {shlex.quote(str(after))}\n"
                "exit $__harnessed_rc\n"
            )
            result = subprocess.run(
                ["bash", "-lc", script],
                cwd=str(project_path),
                env={**os.environ, **harnessed_env(
                    stack, project_path, harness=harness, mode="host", recipe=recipe
                )},
            )
            if result.returncode == 0:
                _propagate_init_env(before, after)
        if result.returncode != 0:
            _err.print(
                f"[bold red]error:[/bold red] recipe '{recipe.name}' init failed "
                f"(exit {result.returncode})"
            )
            raise typer.Exit(result.returncode)


def _host_run_setups(stack: str, project_path: Path, *, harness: str) -> None:
    """Run each recipe's executable setup (host-native) whose `condition` is satisfied — either the
    both-mode `setup.script` (preferred) or the legacy host-only `setup.run`.

    This REPLACES per-launch daemon management: for beads, `run` is `bd init --shared-server …` and
    bd itself auto-manages the shared dolt server — harnessed only supplies the project identity
    (unique database, chosen prefix)."""
    _, recipes = load_stack_with_recipes(None, stack)
    _, bin_dir, uv_tool_dir = _stack_tools_dirs(stack)
    # Same containment as the install path (bd harnessed-8px.26): a setup script is catalog-authored
    # content too, so an inherited CLAUDE_CONFIG_DIR would redirect its writes just as readily.
    cfg_env = _harness_config_env(harness, paths.host_home(stack, harness))
    primitives: dict[str, str] | None = None
    for recipe in recipes:
        setup = recipe.setup
        if not (setup and (setup.run or setup.script)):
            continue
        # condition gates first-run for `run` ONLY: exit 0 == still needed; non-zero == already done.
        # A `setup.script` ignores it and runs every launch — see _pending_setup_scripts for why
        # (a first-run gate can never correct state that exists but is wrong).
        if setup.run and setup.condition and subprocess.run(
            ["bash", "-lc", setup.condition], cwd=str(project_path), capture_output=True,
            env={**os.environ, **harnessed_env(
                stack, project_path, harness=harness, mode="host", recipe=recipe
            ), **cfg_env},
        ).returncode != 0:
            continue
        # Before `config` resolution, which may prompt: asking for values the user is about to
        # decline to use is backwards.
        if not _confirm_setup(recipe, stack, project_path, harness=harness):
            continue
        if primitives is None:
            primitives = _repo_primitives(project_path)
        values = _resolve_setup_config(setup, primitives, interactive=sys.stdin.isatty())
        if setup.script:
            script = recipe.root / setup.script
            bin_dir.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env.update(_script_env(stack, project_path, values, mode="host",
                                   harness=harness, recipe=recipe, bin_dir=bin_dir))
            # Host-only: point uv/npm at the stack-scoped tree so a script's install lands in
            # bin_dir rather than the user's global tool dir. In-container these stay unset — the
            # image already baked the tool via its Dockerfile.
            env["UV_TOOL_DIR"] = str(uv_tool_dir)
            env["UV_TOOL_BIN_DIR"] = str(bin_dir)
            env["npm_config_prefix"] = str(bin_dir.parent)
            env.update(cfg_env)
            argv, label = ["bash", str(script)], f"{setup.script} (host)"
        else:
            cmd = _subst(setup.run, values)
            env = {**os.environ, **harnessed_env(
                stack, project_path, harness=harness, mode="host", recipe=recipe
            ), **cfg_env}
            argv, label = ["bash", "-lc", cmd], cmd
        _err.print(f"[blue][INFO][/blue] setup ({recipe.name}): {label}")
        if subprocess.run(argv, cwd=str(project_path), env=env).returncode != 0:
            _err.print(f"[bold red]error:[/bold red] setup for '{recipe.name}' failed")
            raise typer.Exit(1)


def _host_native_mcp(stack: str) -> Optional[dict]:
    """Resolve the stack's MCP servers into a NATIVE claude `.mcp.json` `mcpServers` dict — no hatago
    hub. claude spawns the stdio servers itself (cwd=project, so `--project-from-cwd` resolves) and
    connects url servers directly. Returns None when the stack declares no MCP servers.

    hatago is DEFERRED: it returns later as an opt-in curation layer (per-server tool filtering via
    @drmikecrowe/hatago-mcp-hub), fronted by a `harnessed mcp curate` utility — not a required bus.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    servers = _merge_servers(recipes)
    if not servers:
        return None
    out: dict = {}
    for s in servers:
        if s.is_stdio_child:
            cmd = s.command
            if cmd and shutil.which(cmd) is None:
                _err.print(
                    f"[yellow]warn:[/yellow] MCP server '{s.name}' needs '{cmd}' on PATH — "
                    "claude will fail to start it until it's installed (add an install.sh to the recipe)"
                )
            entry: dict = {"command": cmd, "args": list(s.args)}
            if s.env:
                entry["env"] = dict(s.env)
            out[s.name] = entry
        elif s.url or s.url_env:
            # ${VAR} — claude expands env vars in .mcp.json; the value stays off disk.
            entry = {"type": s.transport, "url": f"${{{s.url_env}}}" if s.url_env else s.url}
            if s.headers:
                entry["headers"] = dict(s.headers)
            out[s.name] = entry
        else:
            _err.print(
                f"[yellow]warn:[/yellow] MCP server '{s.name}' is service-backed — not supported "
                "host-native yet (skipped)"
            )
    return out or None


def _aoe_register(verb: str, stack: str, harness: str, project_path: Path, *, only: bool) -> None:
    """Mirror this launch into Agent of Empires, and stop here under `--create-aoe-only`.

    Two different contracts share one call. On a normal launch the mirror is passive: fire the
    write detached (`aoe add` takes ~12s) and carry on regardless of outcome — a dashboard is not
    worth blocking or failing a launch for. Under `--create-aoe-only` registering IS the command,
    so it blocks, reports, and propagates an exit status the user can script against.
    """
    registered = aoe.sync_session(verb, stack, harness, project_path, background=not only)
    if not only:
        return
    if not registered:
        _err.print(
            "[bold red]error:[/bold red] --create-aoe-only: could not register the session. "
            "Is Agent of Empires (`aoe`) installed and initialized "
            f"({paths.xdg_config_home() / 'agent-of-empires'})?"
        )
        raise typer.Exit(1)
    _out.print(
        f"[bold green]Registered[/bold green] aoe session "
        f"[bold]{aoe.title_for(verb, stack, harness, project_path)}[/bold]\n"
        f"  profile:  {aoe.PROFILE}\n"
        f"  group:    {aoe._group_for(project_path)}\n"
        f"  command:  {aoe.command_for(verb, stack, harness, project_path)}\n"
        f"  [dim]not launched (--create-aoe-only); start it with `aoe` or `aoe session start`[/dim]",
        highlight=False,
    )
    raise typer.Exit(0)


def _launch_host(
    stack: str, harness: str, path: Optional[str], *, rm: bool = False,
    extra: Optional[list[str]] = None, create_aoe_only: bool = False,
) -> None:
    """Host-native launch: no podman. Materialize the assembled profile into a host CLAUDE_CONFIG_DIR,
    start any host daemons (beads-server, hatago MCP hub), and exec the harness on the host so it sees
    the host's own auth.

    `rm` switches from exec (persist the daemons, clean TTY handoff) to supervise (fork claude, wait,
    then stop the daemons THIS launch started)."""
    if harness != _HOST_HARNESS:
        _err.print(
            f"[bold red]error:[/bold red] host-run currently supports only '{_HOST_HARNESS}' "
            f"(got '{harness}')"
        )
        raise typer.Exit(1)

    project_path = Path(path).resolve() if path else Path.cwd()
    if not project_path.is_dir():
        _err.print(f"[bold red]error:[/bold red] project directory does not exist: {project_path}")
        raise typer.Exit(1)

    stack_dir = paths.find_in_catalog("stacks", stack)
    if not (stack_dir / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_dir / 'stack.yaml'})")
        raise typer.Exit(1)

    # Assemble IN-PROCESS every launch — host-native, emit-only, NO podman and NO image build. This is
    # what keeps host-run container-free end to end: unlike `harnessed build` (which also builds a
    # multi-GB image), we only need the profile's content layer. Assembly is sub-second, so a
    # rebuild-per-launch also sidesteps staleness bookkeeping entirely. `build_root` is the dir that
    # CONTAINS profiles/ (assemble emits to <build_root>/profiles/<stack>/<harness>).
    _err.print(f"[blue][INFO][/blue] Assembling '{stack}' ({harness}) host-native (no container) ...")
    try:
        assemble(None, stack, paths.profiles_root().parent, harness, strict=True)
    except (SchemaError, CollisionError) as exc:
        _err.print(f"[bold red]error:[/bold red] assembling stack '{stack}' failed: {exc}")
        raise typer.Exit(1)

    # Same mirror as the container path, recorded under this verb so the two never collide: a
    # host-native session and a containerized one for the same stack+harness+folder are different
    # things to run. No-op when aoe is absent; never raises.
    #
    # AFTER assembly, not before. Assembly is this backend's real validation gate — the analogue of
    # `launch`'s is_built/staleness checks — so registering ahead of it would leave a row behind for
    # a launch that then died on a renamed recipe, and that row would fail identically every time it
    # was started from the dashboard. It costs `--create-aoe-only` one assembly, which is
    # sub-second, emit-only and container-free on this path.
    _aoe_register("host-run", stack, harness, project_path, only=create_aoe_only)

    # Launch-time secrets — the host half of the container path's `--env-file` (see
    # _resolve_launch_secrets). Set on THIS process for the same reason as the recipe env below:
    # os.environ is the host's box, and `env = dict(os.environ)` at the exec is what delivers them
    # to the agent. Nothing is written to disk on this path.
    #
    # Two precedence calls, both deliberate (bd harnessed-36l):
    #   - applied BEFORE _recipe_env, so a recipe declaration still wins — mirroring container mode,
    #     where `podman run -e` beats `--env-file`.
    #   - overrides an inherited shell value of the same name. The schema is the declared source of
    #     truth; letting a stale export in the invoking shell silently beat it is the failure mode
    #     that is hardest to see from inside a session.
    os.environ.update(_resolve_launch_env(project_path))

    # Sidecars — the SAME ones `launch` ensures (bd harnessed-2sm). A `services:` entry is a property
    # of the STACK, not of the backend: host mode makes the AGENT host-native, it does not remove the
    # service the stack says it needs. Omitting this left every beads stack under `host-run` with no
    # server, no socket and no data dir, and an agent that reported "no beads database" — with
    # nothing in the launch output saying a declared service had been skipped.
    #
    # A socket-backed sidecar composes with a host agent for free: the socket is a filesystem object
    # inside the persist dir the service bind-mounts, so the host process dials exactly the path the
    # container serves it on. No port, no netns to bridge, nothing mode-specific.
    #
    # Ahead of the recipe env and setup scripts below, which is what needs the socket to already
    # exist. Guarded on the stack actually declaring services, so a host launch of a service-less
    # stack still needs no container runtime at all.
    if _service_refs(stack):
        # _resolve_mount_path, not project_path (bd harnessed-wnf): the sidecar must get the same
        # git surface whichever entry point starts it. Otherwise the create-time config — and so the
        # `harnessed.svc-config-hash` label — differs by entry point, and alternating host-run with
        # a container launch would flag drift and recreate the container every single time.
        _ensure_services(
            _runtime(), stack, project_path=project_path,
            mount_path=_resolve_mount_path(project_path, None),
        )

    # Hand the PROJECT the same tool env we are about to hand the agent, so a plain `bd` in this
    # repo is configured too. After services, because the client env includes their connection.
    _write_project_tool_env(stack, project_path)

    # Recipe `env:` — the host half of what the derived image's ENV does for a container launch.
    # Set on THIS process (same reasoning as the PATH mutation below: the process is dedicated to
    # this launch), so all three consumers get it from one place: any install/setup script spawned
    # from here inherits it, and so does claude itself — `env = dict(os.environ)` at the exec below
    # is what actually delivers it to the running agent, the row that was broken before.
    # Recipe declarations win over an inherited value, mirroring `podman run -e` in container mode.
    host_stk, host_recipes = load_stack_with_recipes(None, stack)
    os.environ.update(_recipe_env(host_recipes, project_path, mode="host"))

    # Put the stack bin dir on PATH BEFORE recipe setups + native MCP check. install.sh may put tools
    # there (via UV_TOOL_BIN_DIR / PNPM_HOME redirect), and _host_native_mcp's presence check runs
    # after that — it needs them resolvable. Mutating this process's PATH is fine: it's dedicated to
    # this launch, and claude (env built from os.environ below) inherits it.
    # The stack's mise shims dir joins it (bd harnessed-1t4.3): `tools:` installs land there, and a
    # binary the agent cannot resolve is the same as one that was never installed.
    _, stack_bin, _ = _stack_tools_dirs(stack)
    os.environ["PATH"] = os.pathsep.join(
        [str(stack_bin), str(_host_tool_shims_dir(stack)), os.environ.get("PATH", "")]
    )
    # The shims dir is USELESS without this. Each shim re-execs mise, which resolves the tool by
    # argv[0] against MISE_DATA_DIR — unset, it reads the user's ~/.local/share/mise, where the
    # stack installed nothing, and every shim on the PATH entry above fails with "not a valid
    # shim". Set on os.environ (not a private dict) for the same reason as PATH: installs, setups,
    # the agent, and everything the agent spawns all need it, and os.environ IS the host's box.
    os.environ.update(_host_mise_env(stack))
    # Folder-env contract into THIS process's env, for the same reason (and with the same precedent)
    # as the PATH mutation above: a container launch sets the contract box-wide (`podman run -e`) so
    # every process agrees, and the host has no box — os.environ IS the box. Without this the agent
    # exec'd below inherits nothing, because subprocess.run(env=…) in _host_run_setups is a private
    # copy that dies with the setup. Set BEFORE the setups so they see it too.
    os.environ.update(harnessed_env(stack, project_path, harness=harness, mode="host"))

    # Materialize the host home FIRST, then install, then setup. This order is required, not
    # stylistic: _materialize_host_home rmtree's the home on every launch, so an install that ran
    # before it would have its output deleted — silently (harnessed-8px.1). Setup follows install
    # because install bakes the content setup then configures. _host_launch_plan is pure
    # materialization (its returned argv is rebuilt below), so hoisting it above the scripts costs
    # nothing and is what lets a script write into the home at all.
    #
    # Resolve settings into the PROFILE first: _materialize_host_home (inside the plan) copies
    # prof/settings.json into the host config dir verbatim, so anything not applied here never
    # reaches the agent. This is the host half of the container path's merge (see the
    # _merge_host_claude_settings call in `launch`) — without it a host session ran on the bare
    # assemble-time FLOOR, so the host's own ~/.claude defaultMode never crossed over and a user
    # running `auto` silently got `acceptEdits` (bd harnessed-8px.8). merge_settings applies
    # required.defaultMode with setdefault — a floor, not an override — so the host's mode wins.
    if harness in ("claude", "omp", "opencode"):
        _merge_host_claude_settings(
            profile_dir(stack, harness),
            emit.required_settings(
                _resolve_service_servers(_merge_servers(host_recipes), None),
                host_recipes, host_stk.permissions, harness,
            ),
            harness,
        )
    # Lock spans the rebuild AND the installs — see _host_home_lock for why releasing earlier would
    # let a second launch skip installs that are still running.
    with _host_home_lock(paths.host_home(stack, harness)):
        home, argv, cwd, rebuilt = _host_launch_plan(
            stack, harness, project_path, recipes=host_recipes
        )
    # `install:` — the host half of the derived image's `RUN bash install.sh`, i.e. the content a
    # Dockerfile RUN used to deliver to containers only.
    #
    # SKIPPED when the home was not rebuilt (bd harnessed-8px.12). An install is logically once per
    # STACK, not once per launch: it only ever ran every time because the materialize wiped its
    # output every time. With the wipe gated on the stack fingerprint, the output is still there, so
    # re-running would re-download and re-extract to produce the bytes already on disk.
        if rebuilt:
            # `tools:` BEFORE `install:` — the same order as the derived image, and load-bearing:
            # an install.sh now configures a binary that tools: provides (serena init -b LSP).
            _host_install_tools(stack, host_recipes)
            _host_run_installs(stack, project_path, harness=harness, home=home)
            # ONLY now is the build complete. _host_run_installs exits non-zero on failure, so a
            # failed install never reaches this line and the next launch rebuilds and retries
            # instead of trusting a stamp that certifies content which was never finished.
            _stamp_host_home(home, _host_stack_fingerprint(stack, host_recipes))
        else:
            _say(f"[blue][INFO][/blue] Stack unchanged — reusing {home} (installs skipped)")
    # Run each recipe's executable first-run setup (e.g. beads `bd init --shared-server …`). bd owns
    # the shared-server daemon lifecycle — harnessed no longer manages any beads process itself.
    _host_run_setups(stack, project_path, harness=harness)
    # Recipe `init:` — the host half of the attach shell's init prologue. After setups, since a
    # setup script may install the very binary init invokes.
    _host_run_inits(stack, project_path, harness=harness)

    # Pending `setup:` notices, and BLOCK on them — the host half of what `launch` does at its own
    # line. This was container-only too, so a host launch printed nothing and started the agent
    # anyway: a fresh `beads/team` checkout came up with no workspace, and the agent discovered it
    # rather than the user. Runs after init, so a recipe that self-initializes (beads/stealth) has
    # already satisfied its own condition and stays silent. `allow_terminal=False` — there is no
    # container to drop a shell into here.
    _prompt_setup_notices(host_recipes, project_path, stack, harness, allow_terminal=False)
    # Native MCP (hatago deferred): resolve after PATH is set so the stdio-command presence check
    # sees just-provisioned tools AND anything an install/setup script put in the stack bin dir.
    mcp_servers = _host_native_mcp(stack)

    # ALWAYS write .mcp.json + --strict-mcp-config, even with no servers: strict makes claude load
    # ONLY this file, so the copied .claude.json's global mcpServers never leak into an isolated
    # stack (content-only included). With servers → the stack's set; without → an empty set.
    mcp_path = home / ".mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": mcp_servers or {}}, indent=2), encoding="utf-8")
    argv = ["claude", "--mcp-config", str(mcp_path), "--strict-mcp-config", *(extra or [])]

    _err.print(
        f"[green]host-native[/green]: CLAUDE_CONFIG_DIR=[cyan]{home}[/cyan] cwd=[cyan]{cwd}[/cyan] "
        "— no container"
    )
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(home)
    os.chdir(cwd)

    if not rm:
        # Last chance to be read: past the exec, the agent owns the screen.
        _acknowledge_warnings()
        # execvpe REPLACES this process — clean TTY handoff to claude on the host.
        os.execvpe(argv[0], argv, env)  # never returns
    # --rm: supervise (fork claude, wait). No host daemons to tear down — bd owns its shared server.
    subprocess.run(argv, env=env)


def _require_supported_harness(harness: str) -> None:
    """Shared by `launch` and `host-run` so the two entry points cannot drift apart."""
    if harness not in HARNESS_CONFIG_DIR:
        _err.print(
            f"[bold red]error:[/bold red] unsupported harness '{harness}' "
            f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
        raise typer.Exit(1)


def _resolve_stack(
    stack: Optional[str], recipe: list[str], extends: str, no_extends: bool, service: list[str]
) -> tuple[str, Optional[Path]]:
    """The stack to run — named via `--stack`, or composed from a `--recipe` set. Shared by both
    run verbs, which differ in BACKEND and not in how a stack is chosen (bd harnessed-s84).

    Returns `(name, minted_dir)`. `minted_dir` is non-None only when THIS call created the
    manifest, making it the caller's to remove if a later build fails. An authored stack and a
    dynamic one whose manifest already existed both yield None — neither is ours to delete.
    """
    if stack and recipe:
        _err.print("[bold red]error:[/bold red] provide either --stack or --recipe, not both")
        raise typer.Exit(1)
    if not stack and not recipe:
        _err.print("[bold red]error:[/bold red] provide --stack or at least one --recipe")
        raise typer.Exit(1)
    if stack:
        return stack, None

    base = None if no_extends else extends
    try:
        # services MUST be passed to BOTH calls — they are part of the identity, so deriving
        # without them would compute a different name than mint() does and the preexisting check
        # would inspect the wrong path.
        derived = dynstack.derive_name(list(recipe), base, services=list(service))
        preexisting = (paths.generated_catalog_root() / "stacks" / derived / "stack.yaml").is_file()
        name, stack_dir = dynstack.mint(list(recipe), base, services=list(service))
    except ValueError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    return name, None if preexisting else stack_dir


# Shared by both run verbs so the two grammars cannot drift apart.
_STACK_OPT = typer.Option(
    None, "--stack", "-s",
    help="Authored stack to run (stacks/<name>/stack.yaml). Mutually exclusive with --recipe.",
)
_RECIPE_OPT = typer.Option(
    [], "--recipe", "-r",
    help="Recipe to include; repeat for each. Order is irrelevant — the set is sorted. "
         "Mutually exclusive with --stack.",
)
_EXTENDS_OPT = typer.Option(
    "default", "--extends",
    help="Stack to inherit from (baseline recipes, permissions, credential forwarding).",
)
_NO_EXTENDS_OPT = typer.Option(
    False, "--no-extends", help="Inherit from nothing — the recipe list stands alone.",
)
_SERVICE_OPT = typer.Option(
    [], "--service",
    help="Extra service sidecar. Rarely needed: a recipe declares the services it requires.",
)


@app.command("host-run")
def host_run(
    harness: str = typer.Argument(..., help="Harness to use (host-native: claude)"),
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
    stack: Optional[str] = _STACK_OPT,
    recipe: list[str] = _RECIPE_OPT,
    extends: str = _EXTENDS_OPT,
    no_extends: bool = _NO_EXTENDS_OPT,
    service: list[str] = _SERVICE_OPT,
    rm: bool = typer.Option(
        False, "--rm", help="Stop host daemons this launch started when the session exits"
    ),
    create_aoe_only: bool = typer.Option(
        False, "--create-aoe-only",
        help="Register the Agent of Empires session for this stack and exit without launching. "
             "Requires aoe; runs no assembly.",
    ),
) -> None:
    """Run a stack HOST-NATIVELY — no podman, no container.

    The host backend's own verb (bd harnessed-ltj), separate from `container-run` because the two
    share no flags but `--rm`. `--fresh`, `--no-firewall`, `--mount-folder`, `--agent-start-folder`
    and `--shell` all describe a pod that does not exist here, so a combined verb could only accept
    them and do nothing.

        harnessed host-run <harness> [path] --stack <name>
        harnessed host-run <harness> [path] --recipe r1 --recipe r2

    ONE grammar for both stack sources, and the harness leads. An earlier design put the stack in
    the first positional slot, which made it indistinguishable from the project path under
    `--recipe` — Typer binds positionals by DECLARATION order, not by meaning. That cost a
    rejects-positionals rule and still let `host-run my-stack --recipe serena` launch the GENERATED
    stack with the authored name silently demoted to a project path, exit 0. Naming the stack with
    a flag removes the ambiguity at the source rather than policing it.

    Args after a standalone `--` are appended verbatim to the harness command
    (`harnessed host-run claude -s S -- --resume` runs `claude … --resume`).

    What host mode isolates is CONFIGURATION, not the filesystem: the stack's assembled profile is
    materialized into a per-stack CLAUDE_CONFIG_DIR and the harness is exec'd against your real
    machine, in your real project, with your real credentials. Use `container-run` when you want the
    container boundary too.

    No image build on this path even for a minted recipe set: `_launch_host` assembles in-process on
    every launch.
    """
    _require_supported_harness(harness)
    stack_name, minted_dir = _resolve_stack(stack, recipe, extends, no_extends, service)
    try:
        _launch_host(
            stack_name, harness, path, rm=rm, extra=_passthrough, create_aoe_only=create_aoe_only
        )
    except typer.Exit as exc:
        # typer.Exit(0) is a SUCCESS that unwinds like a failure, and it must not clean up:
        # `_aoe_register` ends `--create-aoe-only` that way, having just written a row whose
        # recorded command names THIS manifest. Deleting it would manufacture precisely the
        # dead-on-arrival row the container path builds ahead of registering to avoid.
        # A NON-zero Exit is a real failure and still cleans up — `_launch_host` rejects a
        # non-claude harness that way, and it does so after the mint.
        if exc.exit_code != 0 and minted_dir is not None:
            shutil.rmtree(minted_dir, ignore_errors=True)
        raise
    except Exception:
        # Same ownership rule as `container_run`: a manifest THIS invocation minted is ours to
        # remove when the launch never gets off the ground. Host mode has no build to fail, but
        # `_launch_host` assembles in-process and a SchemaError/CollisionError from a bad recipe
        # set lands here — leaving an orphan that `harnessed list` shows and no GC reclaims, since
        # volume-gc keys on volumes and a stack that never launched owns none. A PRE-EXISTING
        # manifest (minted_dir is None) is left alone; it may be a working stack that today's
        # recipe edit merely broke. Never reached on a real launch: `_launch_host` ends in execvp.
        if minted_dir is not None:
            shutil.rmtree(minted_dir, ignore_errors=True)
        raise


@app.command("container-run")
def container_run(
    harness: str = typer.Argument(..., help="Harness to use (claude|omp|opencode|antigravity|codex)"),
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
    stack: Optional[str] = _STACK_OPT,
    recipe: list[str] = _RECIPE_OPT,
    extends: str = _EXTENDS_OPT,
    no_extends: bool = _NO_EXTENDS_OPT,
    service: list[str] = _SERVICE_OPT,
    fresh: bool = typer.Option(False, "--fresh", help="Tear down any existing pod/instance first"),
    rm: bool = typer.Option(False, "--rm", help="Ephemeral: tear the pod down when the interactive session exits"),
    no_firewall: bool = typer.Option(False, "--no-firewall", help="Skip egress firewall"),
    agent_start_folder: Optional[str] = typer.Option(
        None, "--agent-start-folder",
        help="Start the agent in this subfolder of the project (root is still mounted in full)",
    ),
    mount_folder: Optional[str] = typer.Option(
        None, "--mount-folder",
        help="Mount this folder (must contain the project) instead of the project itself; the agent "
             "still starts in the project. Exposes a parent dir (e.g. a linked-worktree root) while "
             "you work in a subfolder.",
    ),
    shell: bool = typer.Option(
        False, "--shell",
        help="Open an interactive bash shell in the container instead of starting the agent",
    ),
    create_aoe_only: bool = typer.Option(
        False, "--create-aoe-only",
        help="Register the Agent of Empires session for this stack and exit without launching. "
             "Requires aoe; validates the stack first, so the row is only created for a launch "
             "that would have worked.",
    ),
) -> None:
    """Run a stack in an isolated container against a project directory (container backend).

        harnessed container-run <harness> [path] --stack <name>
        harnessed container-run <harness> [path] --recipe r1 --recipe r2

    Same grammar as `host-run`; the verb picks the backend and nothing else. The recipe form is
    content-named and mints a real manifest under the generated catalog root, which is what lets
    `harnessed list`, the staleness check and both GCs treat it like any other stack. An identical
    set in another repo resolves to the same stack and shares its image and volumes — that is what
    collapses proliferation rather than relocating it.
    """
    _require_supported_harness(harness)
    stack, minted_dir = _resolve_stack(stack, recipe, extends, no_extends, service)

    if recipe:
        # A freshly minted stack has no assembled profile, and everything below hard-errors without
        # one. Unconditional because _build_stack is fingerprint-gated downstream, so an unchanged
        # set is cheap — and deliberately NOT skipped under --create-aoe-only, since the command the
        # registered row replays would be dead on arrival against an unbuilt stack.
        #
        # On failure, remove a manifest THIS invocation created. Otherwise a stack that never built
        # lingers in the catalog, appears in `harnessed list`, and no GC reclaims it — volume-gc
        # keys on volumes, and a stack that never built owns none. A PRE-EXISTING manifest is left
        # alone: it may be a working stack that today's recipe edit merely broke, and deleting it
        # would be collateral.
        try:
            _build_stack(_runtime(), stack, harness)
        except Exception:
            if minted_dir is not None:
                shutil.rmtree(minted_dir, ignore_errors=True)
            raise

    if no_firewall:
        os.environ["NO_FIREWALL"] = "true"

    rt = _runtime()
    anchor_path = Path(path).resolve() if path else Path.cwd()

    if not anchor_path.is_dir():
        _err.print(f"[bold red]error:[/bold red] project directory does not exist: {anchor_path}")
        raise typer.Exit(1)

    # Not inside any git worktree at all (e.g. launching from a bare-repo's parent dir instead of
    # one of its worktrees) — confirm before mounting/persisting against a directory that has no
    # git identity to key off of. Skipped outside a tty (headless/scripted), matching the
    # stale-image confirm below.
    if paths.git_common_dir(anchor_path) is None and sys.stdin.isatty():
        if not typer.confirm(
            f"{anchor_path} doesn't look like a git repository or worktree. Continue anyway?",
            default=False,
        ):
            raise typer.Exit(1)

    # The "project" is wherever the agent starts, not wherever you invoked `launch` from — so
    # --agent-start-folder is resolved first, and everything downstream (instance identity, persist
    # keys, relpath, container -w) is keyed on the resolved start_dir. This makes `launch main
    # --agent-start-folder sub` and `(cd main/sub && launch main)` equivalent: same effective
    # project, same instance, regardless of which directory you happened to launch from.
    start_dir = _resolve_start_dir(anchor_path, agent_start_folder)
    project_path = start_dir

    # The folder path-mirrored into the container. Defaults to anchor_path (cwd / --path) always —
    # not to start_dir — so --agent-start-folder never shrinks the mount. --mount-folder widens it
    # further (must contain project_path).
    mount_path = _resolve_mount_path(anchor_path, mount_folder)

    # Resolve overlay-first (user catalog wins) so we also know the stack's SOURCE: private-key
    # forwarding is trusted only from the user's own overlay, never a shared repo-catalog stack.
    stack_dir = paths.find_in_catalog("stacks", stack)
    stack_yaml = stack_dir / "stack.yaml"
    if not stack_yaml.is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_yaml})")
        raise typer.Exit(1)

    if not is_built(stack, harness):
        _err.print(f"[bold red]error:[/bold red] stack '{stack}' ({harness}) has no assembled profile (run: harnessed build {stack} {harness})")
        raise typer.Exit(1)

    # Guard against a stale profile: a recipe referenced by this stack may have been renamed/removed
    # (SchemaError) or edited (StaleProfileError) since the profile was built. is_built() only checks
    # presence, so without this a launch would silently run an orphaned/outdated image.
    try:
        staleness.check_profile_fresh(None, stack, harness)
    except SchemaError as exc:
        _err.print(
            f"[bold red]error:[/bold red] stack '{stack}' ({harness}) references a recipe that no longer "
            f"resolves ({exc}) — run: harnessed build {stack} {harness}"
        )
        raise typer.Exit(1)
    except staleness.StaleProfileError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc} — run: harnessed build {stack} {harness}")
        raise typer.Exit(1)

    # Mirror into Agent of Empires if the user runs it. Placed after every validation above so a
    # launch that is about to fail never leaves a row behind, and before the podman work so the row
    # exists even if the container half goes wrong. No-op when aoe is absent; never raises.
    _aoe_register("container-run", stack, harness, project_path, only=create_aoe_only)

    try:
        stk = load_stack(stack_dir)
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1)

    stack_from_overlay = stack_dir.resolve().is_relative_to(paths.user_catalog().resolve())

    # Prefer the derived per-stack image (recipe Dockerfile layers); fall back to the plain agent.
    derived = _derived_image(stack, harness)
    harness_image = derived if _image_exists(rt, derived) else _agent_image(harness)
    prof = profile_dir(stack, harness)
    relpath = project_relpath(project_path)
    inst = instance_name(stack, harness, project_path)
    pod = inst

    # Ensure harness image exists (lazy-build for non-claude harnesses). hatago is baked into it now
    # (hatago-consolidation), so there is no separate hatago image to check for.
    _ensure_harness_image(rt, harness)

    # User-facing recipe `setup:` notices — shown host-side here (never baked into an agent identity
    # file), before ANY attach path (reuse/reattach/create) so they surface on every launch. Gating
    # and the [O]k/[T]erminal/[D]ismiss/[Q]uit prompt live in _prompt_setup_notices; reuse
    # launch_recipes below. [T]erminal is equivalent to having passed --shell on this launch.
    _, launch_recipes = load_stack_with_recipes(None, stack)
    shell = _prompt_setup_notices(launch_recipes, project_path, stack, harness) or shell

    # --fresh: tear down existing pod.
    if fresh:
        _out.print(f"[blue][INFO][/blue] --fresh: tearing down existing pod/instance for {inst}")
        _pod_teardown(rt, inst, pod)
        # Also wipe the persisted agy keyring (antigravity only) so --fresh forces a re-login — the
        # keyring dir deliberately survives a normal recreate, so this is the one place it is cleared.
        _keyring_fresh_wipe(harness, inst)

    # Start any service sidecars this stack's recipes reference. Idempotent — skips services already
    # running. Global services are host-published (reached from the pod via
    # host.containers.internal:<port>); project-scoped ones bind-mount this project's persist dir and
    # are reached through a unix socket inside it, so they need the project/mount context.
    #
    # BEFORE the re-attach branch below, deliberately: a long-lived agent container outlives its
    # sidecars. This used to sit after the create path only, so once an instance was running, every
    # subsequent launch took the attach branch and never looked at services again — a sidecar that
    # died stayed dead for the life of the container, long after whatever killed it was gone
    # (observed 2026-07-21: a sidecar dead for 3h, revived by nothing, while `bd` failed every
    # session). Reviving it is exactly what "idempotent" already promised.
    _ensure_services(rt, stack, project_path=project_path, mount_path=mount_path)

    # Same as the host path: the project gets a config of its own, not just the agent we launch.
    _write_project_tool_env(stack, project_path)

    # Re-attach to a running instance (interactive only) — but if it was built from an older image
    # (rebuilt since it started), a re-attach would silently run the stale build. Offer to recreate.
    headless = os.environ.get("HARNESSED_HEADLESS", "false").lower() == "true"
    if not headless and _container_running(rt, inst):
        if _container_stale(rt, inst, harness_image):
            if sys.stdin.isatty() and typer.confirm(
                f"'{inst}' is running on an older build of {harness_image}. "
                "Recreate it with the new build?",
                default=True,
            ):
                _out.print(f"[blue][INFO][/blue] Recreating {inst} on the rebuilt image …")
                _pod_teardown(rt, inst, pod)  # fall through to a fresh create below
            else:
                _out.print(
                    "[yellow]note:[/yellow] attaching to the existing (older-build) instance — "
                    "run with --fresh to update."
                )
                _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough)
                return
        else:
            _out.print(f"[blue][INFO][/blue] Attaching to running instance: {inst}")
            _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough)
            return
    # Stopped leftover: a previous non-ephemeral session exited without tearing down its pod (only
    # --rm cleans up). A same-name `pod create` would fail "name already in use", so remove the
    # stopped instance and recreate. A running instance is re-attached via the guard above.
    if _stopped_leftover(rt, inst, pod):
        _out.print(f"[blue][INFO][/blue] Recreating stopped instance '{inst}' from a prior session …")
        _pod_teardown(rt, inst, pod)

    # Recipe init (Model A) now runs inside the attach shell (_attach → _init_shell_prologue), not a
    # transient container — so init-derived env reaches the agent. Nothing to do here at pod-create.

    _out.print(f"[blue][INFO][/blue] Creating isolated pod: {pod} (harness + hatago)")
    _out.print(f"[blue][INFO][/blue] Project: {project_path} -> {CONTAINER_HOME / relpath}")
    if mount_path != project_path:
        _out.print(f"[blue][INFO][/blue] Mounting folder: {mount_path} (project lives under it)")
    if anchor_path != project_path:
        _out.print(f"[blue][INFO][/blue] Agent start folder: {project_path} (launched from {anchor_path})")

    launch_servers = _resolve_service_servers(_merge_servers(launch_recipes), None)
    required = emit.required_settings(launch_servers, launch_recipes, stk.permissions, harness)
    if harness in ("claude", "omp", "opencode"):
        _merge_host_claude_settings(prof, required, harness)

    # Compose the agent-config volume BEFORE the mounts reference it (bd harnessed-8px.21.2). Uses
    # `harness_image` — the derived image when one exists, else the plain agent image — because
    # podman's copy-up is what lifts that image's `~/.claude` into the volume in the first place.
    # Fingerprint-gated, so an unchanged stack pays nothing: the install output is still in the
    # volume from last time. A CHANGED stack reinstalls here with no podman build at all, which is
    # the point of harnessed-8px.21 — a one-line recipe edit used to cost a 307s layer rebuild.
    config_volume, tools_volume = _ensure_stack_volumes(
        rt, stack, harness, prof, harness_image, launch_recipes
    )

    # Build mount args.
    mount_args = _build_mount_args(harness, prof, mount_path, config_volume, tools_volume)
    # Seed a token-free ~/.claude.json stub so Claude skips onboarding (auth = the token/credential).
    mount_args += _claude_config_seed_mount(harness, inst)
    # NB: the Claude credential fallback mount is appended AFTER secrets resolve (below) — whether
    # it is needed at all depends on a CLAUDE_CODE_OAUTH_TOKEN that may arrive via --env-file.
    # Persist agy's in-pod keyring store (rw) so its Google-OAuth token survives recreates (antigravity).
    mount_args += _keyring_state_mount(harness, inst)
    # Share omp's state with the host (auth + usage + sessions) via a bind mount of ~/.omp/agent.
    mount_args += _omp_agent_mount(harness)
    # Point omp at the in-container hatago hub (nested ro mount shadowing the agent dir's mcp.json),
    # so a stack's assembled MCP servers reach omp — mirrors claude's --mcp-config wiring.
    mount_args += _omp_mcp_seed_mount(harness, inst)
    # Forward the host's ccstatusline config (ro) so the baked statusLine matches the host layout.
    mount_args += _ccstatusline_settings_mount()
    # Bind-mount the corporate proxy CA (ro) so _install_corp_proxy_ca_in_container can register it.
    mount_args += _corp_proxy_ca_mount_args()
    # Persist recipe-declared project-scoped folders (rw) so their state survives --fresh.
    mount_args += _persist_mounts(stack, project_path)
    # Forward the host's git signing + push credentials (1Password/GPG/YubiKey agent, git config,
    # ssh config/known_hosts/pubkeys + opt-in private keys) so the agent can push and sign — no
    # secret baked into an image. Private keys (ssh_keys) are honored ONLY from the user's own overlay
    # catalog — a shared repo-catalog stack must not mount your private key.
    if stk.forward_git_credentials:
        trusted_keys = _trusted_ssh_keys(stk.ssh_keys, stack_from_overlay, stack)
        mount_args += _credential_forward_args(ssh_keys=trusted_keys, rt=rt)
    else:
        # Even without the full opt-in, auto-forward the SSH signing/auth agent (1Password/gpg) +
        # ro git config whenever the agent socket is live on the host: "1Password available → wired
        # up". The agent gates every use behind a host approval/touch and exposes no key material, so
        # this is safe as a default; the secret-bearing surface (gh oauth token, private keys) still
        # requires forward_git_credentials.
        mount_args += _ssh_agent_auto_forward_args(rt=rt)

    # Forward host AWS credentials via the aws-sso ECS server (opt-in per stack). Injects the AWS SDK's
    # ECS-task-role endpoint + bearer token as env only — no aws-sso binary/store/token enters the
    # container. No-op unless the host token file exists (written by `harnessed aws-sso serve`).
    if stk.forward_aws_sso:
        aws_args = _aws_sso_ecs_forward_args()
        if aws_args and not _aws_sso_server_reachable():
            # This host has a bearer token, so the operator uses AWS SSO — but the server isn't live
            # (never started this session, or no role loaded). Wiring the dead endpoint would fail
            # only when the SDK first calls AWS, a silent trap. Surface it now, and don't inject the
            # dead endpoint if they choose to proceed. (Token ABSENT → this host never set AWS SSO
            # up; stay a silent no-op so `forward_aws_sso` is safe to commit in a shared catalog.)
            _err.print(
                "[bold yellow]warning:[/bold yellow] this stack sets [bold]forward_aws_sso[/bold] but "
                "the aws-sso ECS server isn't reachable (not running, or no role loaded).\n"
                "  Start it:   [cyan]harnessed aws-sso serve[/cyan]   (leave running)\n"
                "  Load role:  [cyan]aws-sso ecs load[/cyan]\n"
                "Without it, AWS calls inside the container will fail to find credentials."
            )
            if headless or not sys.stdin.isatty() or not typer.confirm(
                "Continue launching without AWS credentials?", default=False
            ):
                raise typer.Exit(1)
        elif aws_args:
            mount_args += aws_args

    # Resolve launch-time secrets, layered global → project (project wins on conflict). Returns the
    # ordered --env-file list and the subset of temp files to unlink after launch. Stays AFTER the
    # aborting checks above so an early exit can't strand resolved secrets on disk.
    secrets_env_files, secrets_temp_files = _resolve_launch_secrets(project_path)

    # Claude auth, last of the mounts: a long-lived CLAUDE_CODE_OAUTH_TOKEN (host env, varlock, or
    # plain .env) supersedes the credential file, so nothing is mounted in that case.
    mount_args += _claude_creds_seed_mount(
        harness, inst, _claude_oauth_token_configured(harness, project_path)
    )

    # Pod network.
    net = os.environ.get("HARNESSED_NET", "")

    # Create pod.
    if _rt_uses_pods(rt):
        # --hostname explicitly: without it podman uses the pod NAME, which crun rejects past
        # HOST_NAME_MAX (see paths.container_hostname). Set on the POD, not the member — pod members
        # share the pod's UTS namespace, so this is the one that governs.
        pod_cmd = [
            rt, "pod", "create", "--name", pod,
            "--hostname", paths.container_hostname(pod), "--userns=keep-id",
        ]
        if net:
            pod_cmd += ["--network", net]
        _run(pod_cmd, capture_output=True)

    # Regenerate hatago.config.json with each stdio child's cwd pinned to the mirrored project path
    # (bd main-u5d). The committed profile config is project-agnostic (built before any project is
    # known — path mirroring makes the container project path per-launch), so serena/repowise would
    # otherwise resolve the container home instead of the project root. Written per-instance so two
    # projects on the same stack never race on one shared cwd.
    inst_cfg_dir = prof / ".instances" / inst
    inst_cfg_dir.mkdir(parents=True, exist_ok=True)
    hatago_cfg_host = emit.write_hatago_config(inst_cfg_dir, launch_servers, project_path)
    hatago_cfg_ctr = str(paths.hatago_config_container())

    # Filter out --userns=keep-id from member (pod-level property). Mount the hatago config (ro) into
    # the HARNESS container — after the hatago-consolidation, hatago runs IN this container (not a
    # separate pod member), so the hub and the stdio children it spawns share this container's home
    # and see the project bind-mount.
    member_mounts = [a for a in mount_args if a != "--userns=keep-id"]
    member_mounts += ["-v", f"{hatago_cfg_host}:{hatago_cfg_ctr}:ro"]
    member_mounts += _setup_script_mounts(launch_recipes)
    # Socket-backed project services (beads-server) as REAL container env, not only an attach-shell
    # export: `_init_shell_prologue` reaches the interactive shell and nothing else, so a `podman
    # exec`, a hook, or any subprocess saw $HARNESSED_BEADS_SERVER_SOCKET unset — and bd silently
    # accepts an EMPTY --server-socket, falling back to its old TCP config instead of failing. Set it
    # on the container so every process in it agrees.
    # (Now the whole folder-env contract, not just the sockets — `_init_shell_prologue` still
    # exports it for the attach shell, but a hook or a `podman exec` never sees that shell.)
    socket_env = [arg for var, val in harnessed_env(
        stack, project_path, harness=harness, mode="container", mount_path=mount_path
    ).items() for arg in ("-e", f"{var}={val}")]
    # Same rationale as socket_env: a recipe's setup env belongs to the CONTAINER, not to one exec,
    # so hooks and later execs see what the setup script saw. Resolved here because a `setup.config`
    # item may prompt, which must happen before the container starts.
    pending_setups = _pending_setup_scripts(project_path, launch_recipes)
    setup_env = [arg for var, val in _container_setup_env(
                     stack, project_path, pending_setups, harness=harness).items()
                 for arg in ("-e", f"{var}={val}")]
    # Recipe `env:` — set on the CONTAINER for the third time and the same reason. The image already
    # carries the build-resolvable subset as real ENV (emit.write_derived_dockerfile), but that is
    # not sufficient: a value templated on the PROJECT (`{project_dir}`, an in_repo persist dir) is
    # unknowable at build. Setting the resolved values here makes the running agent's env complete
    # and identical to what the host mode gives it.
    recipe_env = [arg for var, val in _recipe_env(launch_recipes, project_path, mode="container").items()
                  for arg in ("-e", f"{var}={val}")]
    # bd harnessed-8px.27. `_write_project_tool_env` puts a `mise.local.toml` in EVERY project, and
    # mise refuses an untrusted config file. The image trusts configs via `mise trust -a` in
    # ~/.bashrc and /etc/profile.d — both of which only run for a LOGIN or interactive shell. Setup
    # scripts run as `podman exec … bash <script>`, which is neither, so any setup invoking a mise
    # shim died with "Config files in …/mise.local.toml are not trusted". serena hit this: its
    # binary IS a mise shim (`tools: pipx:serena-agent`), so merely running it loads the project
    # config.
    #
    # Set on the CONTAINER, not the exec, for the same reason as socket_env above: hooks and later
    # execs must agree with what the setup script saw. Preferred over `bash -lc`, which would fix
    # the trust as a side effect of sourcing profile.d while also re-ordering PATH and pulling in
    # every other login-shell behaviour — a much wider change than the bug warrants.
    mise_trust_env = ["-e", f"MISE_TRUSTED_CONFIG_PATHS={mount_path}"]
    harness_run = [
        rt, "run", "-d",
        # No --hostname in the pod branch: a member inherits the pod's UTS namespace, and the pod
        # create above already set it. The pod-less runtime has no infra container to inherit from,
        # so it needs its own bound (same EINVAL, from the container's own name).
        *(["--pod", pod] if _rt_uses_pods(rt)
          else [f"--network=container:{pod}", "--hostname", paths.container_hostname(inst)]),
        "--name", inst,
        *[arg for f in secrets_env_files for arg in ("--env-file", str(f))],
        # ORDER IS PRECEDENCE: podman applies `-e` left-to-right, so the LAST wins. Recipe `env:` goes
        # FIRST — it is catalog-authored and must not be able to clobber harnessed-owned values. That
        # matches host mode, where _launch_host applies _recipe_env to os.environ and THEN overwrites
        # with harnessed_env. Reversing these two silently inverts precedence between modes (caught
        # merging harnessed-0tk.7 and harnessed-8px.2, each of which was self-consistent alone).
        *recipe_env,
        # Long-lived subscription token from the host env (bare `-e NAME` → podman reads the value
        # from its own env, keeping the secret off the command line). No-op when unset or supplied
        # via --env-file above.
        *_claude_oauth_token_args(harness),
        *socket_env,
        *setup_env,
        *mise_trust_env,
        *member_mounts,
        # Use harnessed-start (baked into base since hatago-consolidation) when present; fall back
        # to plain `sleep infinity` on older images so the launch degrades gracefully rather than
        # hard-failing on a missing binary. Once the base image is rebuilt, the entrypoint runs
        # hatago automatically and this shell one-liner is a no-op (exec replaces it immediately).
        harness_image, "bash", "-c",
        "exec /usr/local/bin/harnessed-start 2>/dev/null || exec sleep infinity",
    ]
    try:
        _run(harness_run, capture_output=True)
    finally:
        # Unlink the temp env-files as soon as podman has ingested them into the container's env —
        # resolved secret values must not linger on disk (T-05-06). Always runs (success or failure).
        # Every env-file is a generated temp (the user's own .env is copied, never handed to podman).
        for f in secrets_temp_files:
            try:
                f.unlink()
            except OSError:
                pass
        secrets_temp_files = []

    # Install the corp proxy CA into the container's trust store (no-op when cert absent).
    # Runs before the egress firewall: update-ca-certificates is local-only and needs no network,
    # but placing it here keeps all post-start container setup before the firewall guard.
    _install_corp_proxy_ca_in_container(rt, inst)

    # Recipe-declared egress: union the extra allowlist hosts across this stack's recipes so the
    # Recipe setup scripts run here: after the CA is trusted, before the firewall closes egress —
    # a first-run setup is the step most likely to need the network.
    _run_container_setups(rt, inst, pending_setups, stack, project_path, harness=harness)

    # firewall opens them ONLY when a recipe that needs them is present (default-DROP otherwise).
    egress_domains = sorted({d for r in launch_recipes for d in r.egress})
    _apply_firewall(rt, inst, egress_domains)

    # hatago starts automatically via /usr/local/bin/harnessed-start (the container entrypoint).
    # No exec -d needed — the entrypoint script starts it in the background before exec-ing sleep.
    hatago_up = _wait_hatago(rt, inst)

    if headless:
        if rm:
            _out.print("[yellow]note:[/yellow] --rm has no effect in headless mode (no interactive session to exit)")
        if not hatago_up:
            # Headless callers (CI / capability tests) have no terminal to notice a degraded hub, so
            # a dead hatago must be a hard failure here, not a green SUCCESS line.
            raise typer.Exit(1)
        _out.print(f"[green][SUCCESS][/green] Isolated pod running headless: {inst} (hatago in-container)")
        return

    _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough)


def _attach(
    rt: str,
    harness: str,
    inst: str,
    project_path: Path,
    *,
    stack: str,
    mount_path: Path,
    ephemeral: bool = False,
    pod: Optional[str] = None,
    start_dir: Optional[Path] = None,
    shell: bool = False,
    extra: Optional[list[str]] = None,
) -> None:
    """Exec into the running instance with the harness command.

    Default: os.execvp hands the TTY to the container natively (clean attach, no post-exit hook).
    ephemeral (--rm): run the exec as a child so the pod can be torn down when the session exits.
    start_dir: working directory for the agent (defaults to project_path; --agent-start-folder).
    shell (--shell): drop into an interactive bash instead of starting the harness.
    extra: passthrough args (from `launch … -- <suffix>`) appended verbatim to the harness command;
    ignored under --shell, which starts no harness.

    Recipe init (Model A): the attach shell exports the path contract and runs each recipe's
    `init.run` inline (fail-fast) BEFORE exec-ing the harness, so init-derived env reaches the agent.
    """
    mise_init = "source ~/.bashrc && mise trust -a 2>/dev/null"
    init_prologue = _init_shell_prologue(stack, project_path, mount_path, harness=harness)

    if shell:
        tail = "exec bash -l"
    elif harness == "opencode":
        # Stack-conditional (bd main-rlw): `opencode --agent <name>` when a persona was baked,
        # else the fixed `opencode` command.
        tail = _opencode_attach_cmd(profile_dir(stack, harness), stack)
    elif harness == "omp":
        # Pin omp's session dir to the host's key so host/pod share one per-folder history.
        tail = _omp_attach_cmd(start_dir or project_path)
    else:
        mcp_cfg = str(paths.container_mcp_config())
        harness_cmd_tpl = _HARNESS_ATTACH_CMD.get(harness, "claude")
        tail = harness_cmd_tpl.format(mcp_cfg=mcp_cfg, instance=inst)
    # Passthrough suffix (`launch … -- <suffix>`): append to the harness command, shell-quoted since
    # `tail` is run via `bash -l -c`. Skipped under --shell (no harness command to extend).
    if extra and not shell:
        tail = tail + " " + " ".join(shlex.quote(a) for a in extra)
    # Antigravity only: start dbus + gnome-keyring in THIS shell before exec-ing agy, so agy inherits
    # the keyring env (bd main-ec5). Empty for every other harness → their shell_cmd is unchanged.
    keyring_init = _keyring_init(harness)
    parts = [mise_init, init_prologue]
    if keyring_init:
        parts.append(keyring_init)
    parts.append(tail)
    shell_cmd = " && ".join(parts)

    _touch_attach_marker(inst)
    exec_argv = [
        rt, "exec", "-it",
        "-e", "TERM=xterm-256color",
        "-w", str(start_dir or project_path),
        inst,
        "bash", "-l", "-c", shell_cmd,
    ]

    if not ephemeral:
        # Last chance to be read: past the exec, the agent owns the screen.
        _acknowledge_warnings()
        # os.execvp replaces this process — hands the TTY to the container natively.
        os.execvp(rt, exec_argv)

    # Keep this process alive so we can reap the pod once the interactive session exits.
    try:
        subprocess.run(exec_argv)
    finally:
        _out.print(f"[blue][INFO][/blue] --rm: tearing down pod {pod or inst}")
        _pod_teardown(rt, inst, pod or inst)
        _attach_marker(inst).unlink(missing_ok=True)


@app.command("build")
def build(
    stack: Optional[str] = typer.Argument(
        None, help="Stack to assemble; omit to rebuild base images and reconcile every declared/previously-built stack"
    ),
    harness: Optional[str] = typer.Argument(
        None,
        help="Harness to build for; omit to build every harness in the stack's `harnesses:` list",
    ),
    root: Optional[str] = typer.Option(None, "--root", help="Alternate stacks/recipes root"),
    no_scans: bool = typer.Option(False, "--no-security-scans", help="Skip credentialed scans"),
    no_strict: bool = typer.Option(
        False, "--no-strict",
        help="Allow unknown recipe-manifest fields (disables the typo guardrail)",
    ),
    force: bool = typer.Option(False, "--force", help="Force rebuild of base images"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable podman layer cache for image builds"),
    jobs: int = typer.Option(
        _DEFAULT_JOBS, "--jobs", "-j", min=1,
        help=(
            "Stacks to build concurrently on a bare `harnessed build` (default: "
            f"{_DEFAULT_JOBS} on this machine). Each build's log is prefixed with its own "
            "coloured stack(harness) tag. Use -j1 for one build at a time with plain output."
        ),
    ),
    corp_proxy_ca_crt: Optional[Path] = typer.Option(
        None,
        "--corp-proxy-ca-crt",
        help=(
            "Path to a corporate proxy CA bundle to persist at $XDG_CONFIG_HOME/harnessed/"
            "corp-proxy-ca.crt and inject into the base image trust store. Optional; once set, "
            "later builds auto-use the persisted file."
        ),
    ),
) -> None:
    """Assemble a stack (emit + build hatago), or rebuild base/claude/hatago images.

    Three forms, driven by the stack's optional `harnesses:` list:

    * `build <stack> <harness>` — build that one pair.
    * `build <stack>`           — build every harness in the stack's `harnesses:` list (errors when
                                  the stack declares none: the harness is then still required).
    * `build`                   — rebuild the base/claude/hatago images, then reconcile every
                                  DECLARED (stack, harness) pair across the catalog plus every pair
                                  that has been built before — comparing each stack's recipe-closure
                                  content hash (`compute_recipe_hash`) against the
                                  `harnessed.recipe-hash` label baked into its built image, and
                                  rebuilding any that are missing or stale. This is how editing a
                                  shared recipe propagates to every stack that uses it without
                                  having to name them one by one. Stale stacks build CONCURRENTLY
                                  (`--jobs`, default half the cores capped at 4); each build's log
                                  is prefixed with its own coloured stack(harness) tag.

    The --corp-proxy-ca-crt flag is a one-time setup for SSL-inspecting corporate proxies: it
    persists the CA bundle at $XDG_CONFIG_HOME/harnessed/corp-proxy-ca.crt and subsequent builds
    automatically inject it into the base image trust store via a build secret.
    """
    from .paths import corp_proxy_ca_path

    if corp_proxy_ca_crt is not None:
        dest = corp_proxy_ca_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(corp_proxy_ca_crt.read_text())
        _out.print(
            f"[blue][INFO][/blue] Persisted corporate proxy CA bundle to {dest} "
            "(will be used for future base-image builds)"
        )

    if no_scans:
        os.environ["HARNESSED_NO_SCANS"] = "true"
    _ensure_local_catalog_links()
    _ensure_docs_wiki_clone()
    rt = _runtime()

    # Optional cache disable: when --no-cache is set, bypass podman layer cache for image builds.
    if no_cache:
        os.environ["HARNESSED_PODMAN_NO_CACHE"] = "true"

    root_path = Path(root).resolve() if root else None
    if stack:
        if harness:
            if harness not in HARNESS_CONFIG_DIR:
                _err.print(
                    f"[bold red]error:[/bold red] unsupported harness '{harness}' "
                    f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
                )
                raise typer.Exit(1)
            targets = [harness]
        else:
            # No harness argument: fan out to the stack's declared `harnesses:` list.
            targets = _declared_harnesses(stack, root_path)
            if not targets:
                _err.print(
                    "[bold red]error:[/bold red] harness is required when a stack is specified "
                    "(e.g.: harnessed build my-stack claude) — or declare `harnesses: [claude, omp]` "
                    f"in the '{stack}' stack.yaml to build several at once"
                )
                raise typer.Exit(1)
            _out.print(
                f"[blue][INFO][/blue] Stack '{stack}' declares harnesses: {', '.join(targets)}"
            )
        for target in targets:
            _build_stack(rt, stack, target, root_path, strict=not no_strict)
    else:
        _build_images_cmd(rt, force=force)
        _reconcile_stacks(rt, root_path, strict=not no_strict, jobs=jobs)


@app.command("list")
def list_stacks() -> None:
    """List authored stacks and harnessed instances (running and stopped)."""
    rt = _runtime()
    _out.print("[bold]Authored stacks:[/bold]")
    for name in paths.list_catalog_stacks():
        built_harnesses = [h for h in HARNESS_CONFIG_DIR if is_built(name, h)]
        if built_harnesses:
            status = "[green]built[/green] (" + ", ".join(built_harnesses) + ")"
        else:
            status = "[yellow]not built[/yellow]"
        _out.print(f"  {name}  ({status})")
    # `-a` lists all harnessed containers, not just running ones, so stopped/exited instances stay
    # visible (they linger until `prune` reaps them). The Status column shows the real state — do not
    # label this "Running", or exited containers read as live.
    _out.print("[bold]Instances (Status column shows running vs stopped):[/bold]")
    subprocess.run([
        rt, "ps", "-a", "--filter", "name=harnessed-",
        "--format", "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}",
    ])


@app.command("stop")
def stop(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Stop every running instance of a stack (all harnesses)."""
    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    # Match harnessed-<harness>-<stack>-<hash> — filter for this stack across all harnesses.
    all_names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    names = [n for n in all_names if re.search(rf"-{re.escape(stack)}-[0-9a-f]{{8}}$", n)]
    for name in names:
        _out.print(f"[blue][INFO][/blue] Stopping {name}")
        subprocess.run([rt, "stop", name], capture_output=True)
    if not names:
        _out.print(f"No running instances for stack '{stack}'")


@app.command("rm")
def remove(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Remove every instance (stopped or running) of a stack (all harnesses)."""
    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    # Match harnessed-<harness>-<stack>-<hash> — filter for this stack across all harnesses.
    all_names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    names = [n for n in all_names if re.search(rf"-{re.escape(stack)}-[0-9a-f]{{8}}$", n)]
    for name in names:
        _out.print(f"[blue][INFO][/blue] Removing {name}")
        subprocess.run([rt, "rm", "-f", name], capture_output=True)
    if not names:
        _out.print(f"No instances found for stack '{stack}'")

    # The containers are gone, so the aoe rows pointing at them are stale. Container verb only —
    # `rm` never touches host-native sessions, which own no container. No-op without aoe.
    aoe.forget_stack("container-run", stack)


@app.command("prune")
def prune(
    idle: int = typer.Option(120, "--idle", help="Prune instances detached at least this many minutes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be pruned without tearing down"),
) -> None:
    """Tear down instances whose interactive session exited and stayed idle.

    An instance is prunable when no session is attached and its last attach was at least --idle
    minutes ago. After hatago-consolidation an idle instance is not just its PID-1 `sleep infinity`:
    it also runs the in-container hatago hub and the stdio MCP children it spawned, so attachment is
    detected positively by a controlling terminal (see `_session_active`), not by process count.

    `-a` also surfaces non-running containers (exited/crashed, e.g. after a host reboot). Those have
    no session by definition, so they skip the tty check and are reaped once idle for --idle minutes
    too — otherwise they accumulate forever, since a plain `podman ps` never lists them.
    Instances never interactively attached (headless / externally driven) are left untouched.
    """
    import time

    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}\t{{.State}}"],
        capture_output=True, text=True,
    )
    # hatago no longer runs as a separate `{inst}-hatago` member (hatago-consolidation), so every
    # `harnessed-` container listed here is a prunable instance. Carry each container's State so
    # non-running ones can be reaped without the (running-only) tty probe.
    members = []
    for line in result.stdout.splitlines():
        name, _, state = line.strip().partition("\t")
        if name.strip():
            members.append((name.strip(), state.strip()))

    pruned = 0
    for inst, state in members:
        marker = _attach_marker(inst)
        if not marker.exists():
            continue  # never interactively attached — leave it alone
        # A running container may still own a live attached session: prune ONLY on a confirmed-idle
        # reading. `_session_active` returns None when `top` failed (transient runtime hiccup); treat
        # unknown as "leave it alone" so a momentary error never tears down a live session — the next
        # prune run retries. A non-running container (exited/crashed) has no session, so skip the
        # probe entirely and fall straight through to the idle check.
        if state == "running" and _session_active(rt, inst) is not False:
            continue
        idle_min = (time.time() - marker.stat().st_mtime) / 60
        if idle_min < idle:
            continue
        pruned += 1
        if dry_run:
            _out.print(f"[yellow]would prune[/yellow] {inst} (idle {idle_min:.0f}m)")
            continue
        _out.print(f"[blue][INFO][/blue] Pruning {inst} (idle {idle_min:.0f}m)")
        _pod_teardown(rt, inst, inst)
        marker.unlink(missing_ok=True)

    if pruned == 0:
        _out.print(f"No idle instances to prune (threshold: {idle}m)")
    elif not dry_run:
        _out.print(f"[green][SUCCESS][/green] Pruned {pruned} idle instance(s)")


@app.command("clean")
def clean_profiles() -> None:
    """Purge the XDG profile cache (all assembled profiles under $XDG_DATA_HOME/harnessed/)."""
    prof_root = paths.profiles_root()
    if not prof_root.exists():
        _out.print(f"Profile cache is empty: {prof_root}")
        return
    import shutil as _shutil
    _out.print(f"[blue][INFO][/blue] Purging profile cache: {prof_root}")
    _shutil.rmtree(prof_root)
    _out.print("[green][SUCCESS][/green] Profile cache purged")


def _update_recipe_dirs() -> list[Path]:
    """Every recipe dir across the active catalog roots (user overlay + repo), deduped by ref.

    Enumerated by walking for `recipe.yaml` rather than via `list_catalog`, because a recipe FAMILY
    (`beads/stealth`) nests one level down and `update` wants every manifest, family member or not.
    """
    seen: set[str] = set()
    dirs: list[Path] = []
    for root in paths.catalog_roots():
        recipes = root / "recipes"
        if not recipes.is_dir():
            continue
        for manifest in sorted(recipes.rglob("recipe.yaml")):
            ref = str(manifest.parent.relative_to(recipes))
            if ref in seen:        # user overlay wins, exactly as everywhere else
                continue
            seen.add(ref)
            dirs.append(manifest.parent)
    return dirs


def _print_update_report(report) -> None:
    """Render the buckets. Held and unresolved print even in `--check`, because the whole point of
    this command is that nothing a human should know about stays invisible."""
    def where(f) -> str:
        return f"{f.pin.recipe} ({f.pin.file.name})"

    if report.stale:
        _out.print("[bold]Outdated pins:[/bold]")
        for f in report.stale:
            _out.print(
                f"  {where(f)}  {f.pin.spec}\n"
                f"      [yellow]{f.pin.current}[/yellow] -> [green]{f.latest}[/green]"
            )
            if f.skipped_newer:
                # Offering 1.6.0 while 1.6.1 exists looks like a bug unless we say why.
                age = (
                    f"{f.skipped_newer_age_days:.1f} days old"
                    if f.skipped_newer_age_days is not None else "too new"
                )
                _out.print(
                    f"      [dim]({f.skipped_newer} exists but is {age} — "
                    "below the minimum release age)[/dim]"
                )
    if report.cooling:
        # Shown, not dropped: the user is entitled to know a newer release exists and is being
        # waited out. Naming the age is what makes "wait" a decision rather than a mystery.
        _out.print("[bold]Held back by the release-age cooldown:[/bold]")
        for f in report.cooling:
            age = f"{f.age_days:.1f}" if f.age_days is not None else "?"
            _out.print(
                f"  {where(f)}  {f.pin.spec}\n"
                f"      {f.pin.current} -> {f.latest}  "
                f"[yellow]published {age} days ago — too new to offer[/yellow]"
            )
    if report.held:
        _out.print("[bold]Held (manual-upgrade-only — not offered):[/bold]")
        for f in report.held:
            newer = f" (newer available: {f.latest})" if f.latest else ""
            _out.print(f"  {where(f)}  {f.pin.spec}{newer}\n      hold: {f.pin.hold}")
    if report.unresolved:
        # Loud on purpose. A pin we could not check is the one case where silence would read as
        # "fine", and that false confidence is what this command exists to remove.
        _out.print("[bold]Unresolved (could NOT be checked — review by hand):[/bold]")
        for f in report.unresolved:
            _out.print(f"  {where(f)}  {f.pin.spec}\n      [yellow]{f.error}[/yellow]")


@app.command("update")
def update_pins(
    check: bool = typer.Option(
        False, "--check",
        help="CI mode: report and exit non-zero if any pin is outdated. Writes nothing.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept every offered bump without prompting.",
    ),
    minimum_release_age: float = typer.Option(
        None, "--minimum-release-age",
        help="Minutes a release must have existed before it is offered (default 10080 = 7 days, "
             "pnpm's `minimumReleaseAge` unit). 0 disables the gate.",
    ),
) -> None:
    """Find outdated pins across the catalog and offer to bump them.

    `tools:` entries resolve against their backend (npm / PyPI / GitHub releases / mise). Pins
    buried in install scripts and Dockerfiles cannot be resolved automatically and are REPORTED as
    unresolved rather than skipped. Pins marked `hold` (recipe.yaml `install.hold`, or a `tools:`
    entry's `hold`) are listed for information only and never bumped — see bd harnessed-c5t.

    Modelled on pnpm's `minimumReleaseAge`: a release younger than the window (default 7 days) is
    not offered, because a compromised or broken publish is usually yanked within days. As in pnpm,
    that does not mean "no update" — the newest version that IS old enough is offered instead, and
    the newer one it passed over is named.
    """
    from . import update as pinupdate

    dirs = _update_recipe_dirs()
    if not dirs:
        _err.print("[yellow]warning:[/yellow] no recipes found in the active catalog")
        raise typer.Exit(0)

    # Resolve THROUGH the module attribute rather than importing the function, so a test (or a
    # future offline mode) can swap `update.resolve_latest` and have it take effect here.
    report = pinupdate.build_report(
        dirs,
        resolve=lambda backend, name: pinupdate.resolve_releases(backend, name),
        minimum_release_age_minutes=(
            pinupdate.DEFAULT_MINIMUM_RELEASE_AGE_MINUTES
            if minimum_release_age is None else minimum_release_age
        ),
    )
    _print_update_report(report)

    if check:
        if report.stale:
            _err.print(
                f"[bold red]error:[/bold red] {len(report.stale)} outdated pin(s) — "
                "run `harnessed update` to bump them"
            )
        raise typer.Exit(report.check_exit_code())

    if not report.stale:
        _out.print("[green]All resolvable pins are up to date.[/green]")
        raise typer.Exit(0)

    accepted = []
    for f in report.stale:
        if yes or typer.confirm(
            f"Bump {f.pin.recipe} {f.pin.spec}: {f.pin.current} -> {f.latest}?", default=True
        ):
            accepted.append(f)

    written = pinupdate.apply(accepted)
    for f in written:
        _out.print(f"[green][SUCCESS][/green] {f.pin.recipe}: {f.pin.current} -> {f.latest}")
    skipped = len(report.stale) - len(written)
    if skipped:
        _out.print(f"Left {skipped} pin(s) unchanged.")
    if written:
        # The repo catalog is under the worktree -> tests -> PR rule; a bumped pin is a code change
        # like any other, and an unverified bump is worse than a stale one. Naming the stacks and
        # printing the literal commands is the difference between a reminder and a task the user
        # has to go research (bd harnessed-czo).
        bumped = sorted({f.pin.recipe for f in written})
        stacks = pinupdate.affected_stacks(bumped)
        _out.print(f"[blue][INFO][/blue] Bumped: {', '.join(bumped)}")
        if stacks:
            _out.print(f"       Affected stacks: {', '.join(sorted(stacks))}")
            _out.print("       Verify before committing:")
            for line in pinupdate.verify_commands(stacks):
                _out.print(f"         {line}")
        else:
            _out.print(
                "       No stack in the active catalog uses these recipes — nothing to rebuild."
            )


@app.command("test")
def test_stack(
    stack: str = typer.Argument(..., help="Stack name"),
    harness: str = typer.Argument(..., help="Harness to test against (claude|omp|opencode|antigravity|codex)"),
    project: Optional[str] = typer.Option(None, "--project", help="Scratch project path"),
    keep: bool = typer.Option(False, "--keep", help="Keep instance after test"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON result"),
) -> None:
    """Capability test: launch --fresh headless + assert declared capabilities."""
    if harness not in HARNESS_CONFIG_DIR:
        _err.print(
            f"[bold red]error:[/bold red] unsupported harness '{harness}' "
            f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
        raise typer.Exit(1)

    rt = _runtime()
    root = _harnessed_dir()

    reason = None
    if not is_built(stack, harness):
        reason = "not built"
    else:
        try:
            staleness.check_profile_fresh(None, stack, harness)
        except (SchemaError, staleness.StaleProfileError) as exc:
            reason = f"stale ({exc})"
    if reason:
        _out.print(f"[blue][INFO][/blue] Stack '{stack}' ({harness}) {reason} — assembling first")
        _build_stack(rt, stack, harness)

    # Delegate to the capability test (the harnessed.cli `test` entrypoint).
    run_env = {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "CONTAINER_RUNTIME": rt,
        "HARNESSED_DIR": str(root),
    }
    cmd: list[str] = []
    if shutil.which("uv"):
        cmd = ["uv", "run", "--no-project", "--quiet", "--with", "ruamel.yaml", "--with", "rich",
               "python", "-m", "harnessed.cli", "test", stack, harness, "--root", str(root)]
    elif shutil.which("python3"):
        cmd = ["python3", "-m", "harnessed.cli", "test", stack, harness, "--root", str(root)]
    else:
        _err.print("[bold red]error:[/bold red] 'uv' or 'python3' required for capability test")
        raise typer.Exit(1)

    if project:
        cmd += ["--project", project]
    if keep:
        cmd.append("--keep")
    if as_json:
        cmd.append("--json")

    result = subprocess.run(cmd, env=run_env)
    raise typer.Exit(result.returncode)


@app.command("new")
def new_stack(
    stack: str = typer.Argument(..., help="Stack name"),
    recipes: str = typer.Option("", "--recipes", help="Comma-joined recipe names"),
) -> None:
    """Scaffold a stack manifest in stacks/<name>/stack.yaml."""
    if stack in HARNESS_CONFIG_DIR:
        _err.print(f"[bold red]error:[/bold red] stack name '{stack}' conflicts with a harness name — choose a different name")
        raise typer.Exit(1)

    stacks_d = _stacks_dir()
    stack_dir = stacks_d / stack
    if (stack_dir / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] stack '{stack}' already exists ({stack_dir / 'stack.yaml'})")
        raise typer.Exit(1)

    stack_dir.mkdir(parents=True, exist_ok=True)
    recipe_list = [r.strip() for r in recipes.split(",") if r.strip()] if recipes else []
    lines = [
        f"name: {stack}",
        "recipes:",
    ]
    for r in recipe_list:
        lines.append(f"  - {r}")
    if not recipe_list:
        lines.append("  []")
    lines.append("services: []")
    (stack_dir / "stack.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _out.print(f"[green][SUCCESS][/green] Scaffolded stack '{stack}' at {stack_dir / 'stack.yaml'}")


@app.command("install")
def install_stack(
    stack: str = typer.Argument(..., help="Stack name"),
) -> None:
    """Write a ~/.local/bin/<stack> launcher shim that runs `harnessed container-run`."""
    import shlex
    import stat

    if not (paths.find_in_catalog("stacks", stack) / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] no such stack '{stack}' (see `harnessed list`)")
        raise typer.Exit(1)

    # Bake in the absolute path to THIS `harnessed` binary so the shim works even when
    # `harnessed` itself is not on PATH (e.g. a dev .venv). Prefer the PATH-resolved
    # location (stable across shells), fall back to the running interpreter's script.
    harnessed_bin = shutil.which("harnessed") or str(Path(sys.argv[0]).resolve())

    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / stack
    # `--stack` goes BEFORE "$@", and the ordering is load-bearing. The stack can no longer be a
    # bare leading token — that slot is the harness — so the shim names it with the flag; but put
    # the flag last and a passthrough invocation swallows it. `mystack claude . -- --resume` would
    # expand to `… claude . -- --resume --stack mystack`, and `_extract_passthrough` splits at the
    # FIRST `--`, sending `--stack mystack` to the agent and leaving the CLI with no stack at all.
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {shlex.quote(harnessed_bin)} container-run --stack {shlex.quote(stack)} \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    _out.print(
        f"[green][SUCCESS][/green] Installed shim: {shim} -> harnessed container-run --stack {stack}"
    )
    if str(bin_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        _out.print(f"[yellow]note:[/yellow] {bin_dir} is not on your PATH — add it to run `{stack}` directly.")


@app.command("uninstall")
def uninstall_stack(
    stack: str = typer.Argument(..., help="Stack name"),
) -> None:
    """Remove the ~/.local/bin/<stack> launcher shim."""
    shim = Path.home() / ".local" / "bin" / stack
    if shim.is_file():
        shim.unlink()
        _out.print(f"[green][SUCCESS][/green] Removed shim: {shim}")
    else:
        _out.print(f"No shim found at {shim}")


# Backstop for the whole scan container. Deliberately much larger than harnessed-scan's own
# per-scanner bound: several scanners run in sequence and a thorough scan must not be cut off.
_SCAN_CONTAINER_TIMEOUT = 900


def _scan_image_in_container(
    rt: str, image: str, *, report_dest: "Path | None" = None, extra_args: list[str] | None = None
) -> bool:
    """Run the image's own baked `harnessed-scan` inside a throwaway container, with scanner tokens
    injected as env.

    THIS IS THE ONLY PATH ON WHICH snyk AND socket ACTUALLY RUN. The build-time scan layer is
    deliberately credential-free (`_build_derived_image` never passes a secret), so both token-gated
    scanners sit out every build and only osv-scanner + pip-audit contribute there.

    Tokens are resolved on the HOST (`_resolve_launch_secrets(None)` → user-global
    ~/.config/harnessed/.env.schema via varlock, else a bare .env) and handed to podman as a
    mode-0600 temp --env-file, which is unlinked afterwards. varlock never runs in-container: 1Password
    app-auth binds the grant to the calling host application and cannot work from inside a container
    (docs/guides/secrets.md). Project env is deliberately NOT layered in — a rescan is about the
    image, not about whichever directory you happen to be standing in.

    Advisory: `harnessed-scan` always exits 0, so this reports posture and never gates.
    """
    env_files, temp_files = _resolve_launch_secrets(project_path=None)
    if not env_files:
        _out.print(
            "[yellow]note:[/yellow] no ~/.config/harnessed/.env.schema or .env — snyk and socket "
            "have no tokens and will be skipped (osv-scanner + pip-audit still run)"
        )
    # NOT `--rm`: this scan's report is the only one that ever contains snyk/socket findings, and a
    # removed container takes it with it. That is exactly how bd harnessed-de7 happened — the
    # credentialed findings were printed, discarded, and then the weaker build-time report was
    # surfaced in their place under a green "no high/critical" verdict. Keep the container just long
    # enough to `cp` the report out, then remove it in the `finally`.
    #
    # `cp` rather than a bind-mount on purpose: the image runs as the unprivileged `harnessed` user,
    # and writing to a host dir from a rootless container needs userns mapping that this call site
    # does not otherwise require. Copying out has no such dependency.
    cid = ""
    try:
        with tempfile.TemporaryDirectory() as td:
            cidfile = Path(td) / "cid"  # must NOT pre-exist — podman refuses to overwrite it
            argv = [
                rt, "run", "--cidfile", str(cidfile),
                *[arg for f in env_files for arg in ("--env-file", str(f))],
                # The stack volumes (bd harnessed-8px.21.5). Once `tools:`/`install:` stopped being
                # image layers, an image-only scan still PASSES and still prints "no high/critical"
                # while silently covering less — a narrower scan that reports green is worse than a
                # failing one. Mounting the volumes keeps the report about the whole stack.
                *(extra_args or []),
                image, "harnessed-scan",
            ]
            # OUTER bound (bd harnessed-8px.28). harnessed-scan now bounds each scanner itself, so
            # this is the backstop for the script wedging somewhere else entirely — and it is not
            # hypothetical: a scan container ran for 71 HOURS at 0% CPU with no timeout anywhere
            # above it, which would have hung `harnessed build` indefinitely and silently.
            #
            # Generous relative to the inner per-call bound, because a legitimate scan runs several
            # scanners in sequence and must not be cut off just for being thorough.
            try:
                res = subprocess.run(argv, timeout=_SCAN_CONTAINER_TIMEOUT)
            except subprocess.TimeoutExpired:
                # Read the cid HERE too: the assignment below never ran, and without it the
                # `finally` has nothing to remove — which is exactly how the 71-hour container was
                # left behind. `rm -f` there escalates to SIGKILL, which that one needed.
                cid = cidfile.read_text().strip() if cidfile.is_file() else ""
                _out.print(
                    f"[yellow]⚠ supply-chain:[/yellow] scan timed out after "
                    f"{_SCAN_CONTAINER_TIMEOUT}s and was killed — posture NOT verified. "
                    "Advisory only, so the build continues."
                )
                return False
            cid = cidfile.read_text().strip() if cidfile.is_file() else ""
        if report_dest is not None and cid:
            report_dest.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json",
                 str(report_dest)],
                capture_output=True,
            )
        # Return means "the scan ran cleanly" — NOT "a report was persisted". `_scan_image` calls
        # this without a report_dest and needs that original meaning; whether a report landed is a
        # separate question the caller answers by looking for the file.
        return res.returncode == 0
    finally:
        if cid:
            subprocess.run([rt, "rm", "-f", cid], capture_output=True)
        for f in temp_files:
            Path(f).unlink(missing_ok=True)


def _scan_image(rt: str, run_env: dict, image: str) -> bool:
    """Full re-scan of an already-built image — the two passes are complementary:

    1. Credentialed in-image scan (`_scan_image_in_container`): snyk + socket + osv-scanner +
       pip-audit over what the build actually installed. ADVISORY.
    2. Online archive scan (`scan-image-online`): osv-scanner against a `podman save` tarball with
       the offline DB flags dropped, so it sees advisories disclosed SINCE the build. GATES on HIGH+.

    Returns True on a clean run (no HIGH+ finding), False otherwise.
    """
    scanned = _scan_image_in_container(rt, image)

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tf:
        tar_path = tf.name
    try:
        _run([rt, "save", image, "-o", tar_path])
        res = subprocess.run(
            ["uv", "run", "--no-project", "--quiet", "--with", "ruamel.yaml",
             "python", "-m", "harnessed.cli", "scan-image-online", tar_path],
            env=run_env,
        )
        return scanned and res.returncode == 0
    finally:
        Path(tar_path).unlink(missing_ok=True)


@app.command("scan")
def scan(
    stack: str = typer.Argument(..., help="Stack name (stacks/<name>/stack.yaml)"),
    harness: Optional[str] = typer.Argument(
        None,
        help="Harness to scan; omit to scan every built harness for the stack "
        "(claude|omp|opencode|antigravity|codex)",
    ),
) -> None:
    """Re-scan a stack's already-built image(s) online (post-build CVE catch — see `rescan`),
    scoped to a single stack.

    * `scan <stack> <harness>` — re-scan that one (stack, harness) image; errors if it isn't
                                 built yet.
    * `scan <stack>`           — re-scan every supported harness's image for the stack
                                 (antigravity, claude, codex, omp, opencode), skipping any that
                                 haven't been built.
    """
    if not (paths.find_in_catalog("stacks", stack) / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] no such stack '{stack}' (see `harnessed list`)")
        raise typer.Exit(1)

    if harness is not None and harness not in HARNESS_CONFIG_DIR:
        _err.print(
            f"[bold red]error:[/bold red] unsupported harness '{harness}' "
            f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
        raise typer.Exit(1)

    targets = [harness] if harness else sorted(HARNESS_CONFIG_DIR)
    to_scan = []
    for target in targets:
        if is_built(stack, target):
            to_scan.append(target)
        elif harness:
            _err.print(
                f"[bold red]error:[/bold red] stack '{stack}' ({target}) has no assembled profile "
                f"(run: harnessed build {stack} {target})"
            )
            raise typer.Exit(1)
    if not to_scan:
        _out.print(f"[yellow]note:[/yellow] stack '{stack}' has no built harnesses — nothing to scan.")
        return

    rt = _runtime()
    root = _harnessed_dir()
    run_env = {**os.environ, "PYTHONPATH": str(root / "src"), "CONTAINER_RUNTIME": rt}
    _out.print(f"[blue][INFO][/blue] Scanning stack '{stack}' — harness(es): {', '.join(to_scan)}")
    has_errors = False
    for target in to_scan:
        if not _scan_image(rt, run_env, _derived_image(stack, target)):
            has_errors = True
    if has_errors:
        raise typer.Exit(1)


@app.command("rescan")
def rescan(
    image: Optional[str] = typer.Argument(
        None,
        help="Image to re-scan (repo:tag); omit to re-scan every harnessed-labelled image",
    ),
) -> None:
    """Re-scan built harnessed image(s) WITH credentials — the credentialed counterpart to `build`.

    Resolves scanner tokens from the user-global ~/.config/harnessed/.env.schema (via varlock) or
    .env, injects them into a throwaway container from the image, and runs the baked `harnessed-scan`
    there. This is where snyk and socket actually run: `harnessed build` is deliberately
    credential-free, so a build only ever gets osv-scanner + pip-audit. Also runs the online archive
    scan, which catches CVEs disclosed since the image was built.

    * `rescan <image>` — re-scan that one image (errors if it isn't built).
    * `rescan`         — re-scan every harnessed-labelled image.
    """
    rt = _runtime()
    if image:
        exists = subprocess.run([rt, "image", "exists", image], capture_output=True)
        if exists.returncode != 0:
            _err.print(
                f"[bold red]error:[/bold red] no such image '{image}' "
                "(build it first, or run `harnessed rescan` to scan every built image)"
            )
            raise typer.Exit(1)
        images = [image]
    else:
        result = subprocess.run(
            [rt, "images", "--filter", "label=harnessed=true", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True, text=True,
        )
        images = [i.strip() for i in result.stdout.splitlines() if i.strip()]
        if not images:
            _out.print("No harnessed-labelled images found to rescan")
            return
    root = _harnessed_dir()
    run_env = {**os.environ, "PYTHONPATH": str(root / "src"), "CONTAINER_RUNTIME": rt}
    has_errors = False
    for image in images:
        if not _scan_image(rt, run_env, image):
            has_errors = True
    if has_errors:
        raise typer.Exit(1)


# Subcommand names — anything else in the first position is treated as a stack name and routed
# to `launch` (the `harnessed <stack> [project] [--fresh]` shorthand the README documents and the
# capability test relies on).
@app.command("host-gc")
def host_gc(
    prune: bool = typer.Option(False, "--prune", help="Remove orphan dirs whose project path no longer exists"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be removed without removing it"),
) -> None:
    """List host config dirs; optionally remove orphans and scrub stranded credentials.

    Default (no flags): list every host config dir with stack/harness/hash, project path, age,
    size, and credential status (symlink vs. real file vs. absent).

    --prune: remove dirs whose project path no longer exists on disk. A dir whose project path
    is present is NEVER removed — a path can be absent because a volume is unmounted, and silently
    deleting that config would be data loss. Inspect the listing first.

    --dry-run: combine with --prune to see what would be removed without touching anything.

    Credential scrubbing: real .credentials.json files (written by Claude on token refresh,
    replacing the symlink) are overwritten with null bytes and fsync'd before the dir is removed.
    On SSDs with wear-leveling firmware the controller may have already remapped the underlying
    blocks, so overwrite reduces but does not guarantee physical erasure. It is better than a bare
    unlink and is the level of assurance a software tool can provide without raw device access.

    Interaction with harnessed-8px.12 (re-keying to per-stack dirs): that migration orphans every
    existing per-project dir at once. Run `host-gc --dry-run --prune` AFTER the migration to
    review, then `host-gc --prune` to scrub. The _scrub_host_home helper is reusable by the
    migration path for exactly this purpose.
    """
    import time as _time

    root = paths.host_homes_root()
    if not root.exists():
        _out.print("No host config dirs found.")
        return

    # Enumerate root/<stack>/<harness> — the config dir IS the stack identity (bd harnessed-8px.12),
    # so a dir is an orphan when its STACK no longer resolves in the catalog. That is a far better
    # signal than the old per-project breadcrumb: a stack name is right there in the path, where a
    # project_hash was a one-way sha1 that could not be resolved back to anything.
    entries: list[tuple[str, str, bool, float, float, str, list[str], Path]] = []
    for stack_dir in sorted(root.iterdir()):
        if not stack_dir.is_dir():
            continue
        stack_gone = not (paths.find_in_catalog("stacks", stack_dir.name) / "stack.yaml").is_file()
        for home in sorted(stack_dir.iterdir()):
            # `<harness>.home` is the $HOME shim (paths.host_home_shim), a sibling of the config dir
            # — not a config dir itself, and removing it out from under a stack would break installs.
            if not home.is_dir() or home.name.endswith(".home"):
                continue
            age_days = (_time.time() - home.stat().st_mtime) / 86400
            size_kb = sum(f.stat().st_size for f in home.rglob("*") if f.is_file()) / 1024
            cred = home / ".credentials.json"
            cred_status = "symlink" if cred.is_symlink() else ("REAL-FILE" if cred.is_file() else "none")
            # Pre-8px.12 per-project dirs, now nested inside. The next launch scrubs them; surfacing
            # them here means a user who never relaunches that stack can still see they exist.
            legacy = [
                c.name for c in sorted(home.iterdir())
                if c.is_dir() and not c.is_symlink() and _LEGACY_PROJECT_DIR_RE.match(c.name)
            ]
            entries.append(
                (stack_dir.name, home.name, stack_gone, age_days, size_kb, cred_status, legacy, home)
            )

    if not entries:
        _out.print("No host config dirs found.")
        return

    for stack, harness, is_orphan, age_days, size_kb, cred_status, legacy, home in entries:
        status = "[red]ORPHAN[/red]" if is_orphan else "[green]ok[/green]"
        cred_tag = f"  cred:[yellow]{cred_status}[/yellow]" if cred_status != "none" else ""
        legacy_tag = (
            f"  [yellow]{len(legacy)} legacy per-project dir(s)[/yellow]" if legacy else ""
        )
        reason = " (stack no longer in catalog)" if is_orphan else ""
        _out.print(
            f"{status}  {stack}/{harness}  "
            f"age={age_days:.0f}d  {size_kb:.0f}KB{cred_tag}{legacy_tag}{reason}"
        )

    if not prune:
        orphan_count = sum(1 for e in entries if e[2])
        if orphan_count:
            _out.print(f"\n[dim]{orphan_count} orphan(s). Run with --prune to remove.[/dim]")
        return

    orphans = [e for e in entries if e[2]]  # stack no longer in the catalog
    if not orphans:
        _out.print("\nNo orphans to remove.")
        return

    removed = 0
    for stack, harness, _is_orphan, _age, _size, _cred, _legacy, home in orphans:
        label = f"{stack}/{harness} (stack no longer in catalog)"
        proj_dir = home
        if dry_run:
            _out.print(f"[yellow]would remove[/yellow] {label}")
            removed += 1
            continue
        _out.print(f"[blue][INFO][/blue] Removing {label}")
        _scrub_host_home(proj_dir)
        removed += 1

    if dry_run:
        _out.print(f"\n[dim]{removed} orphan(s) would be removed (--dry-run, nothing deleted).[/dim]")
    else:
        _out.print(f"\n[green][SUCCESS][/green] Removed {removed} orphan(s).")


def _svc_migrate(
    svc_def: "ServiceDef", stack: str, project_path: Path, from_path: str, assume_yes: bool
) -> None:
    """Move an existing database INTO this service's data dir, with the user's confirmation.

    The gap this fills: the sidecar re-asserts socket mode in `metadata.json` on every startup, but
    re-pointing the metadata does not move the bytes. A workspace that bd adopted onto its own
    multi-project server therefore comes up correctly configured and still empty, and every client
    fails with errno 1049 — which `_assert_named_database_present` now catches at launch and sends
    here.

    Deliberately a separate, explicit command rather than something `launch` does for you: it copies
    a database between directories, and the recipes already hold the line that first-time beads setup
    is a deliberate user action rather than a side effect of launching.

    Copies, never moves. A failed or half-finished migration must leave the source exactly as it was,
    so the old location stays usable as a fallback until the user removes it themselves.
    """
    if svc_def.exclusive_lock != "dolt":
        _err.print(f"[bold red]error:[/bold red] service '{svc_def.name}' defines no migration")
        raise typer.Exit(1)
    host_dir, _, _ = _service_data_dir(svc_def, stack, project_path)
    meta = _beads_metadata(host_dir)
    db = str((meta or {}).get("dolt_database") or "")
    if not db:
        _err.print(
            f"[bold red]error:[/bold red] no workspace to migrate: {host_dir / 'metadata.json'} "
            "does not name a database"
        )
        raise typer.Exit(1)

    dest = host_dir / "dolt" / db
    if dest.is_dir():
        _out.print(f"[blue][INFO][/blue] '{db}' is already in {host_dir / 'dolt'} — nothing to do")
        return

    # Copying into a data dir that an engine has open risks a torn copy, and the flock makes the
    # result unusable anyway. Same check the launch path runs before starting the sidecar.
    holder = _host_process_in_dir("dolt", host_dir.resolve())
    if holder is not None:
        pid, cmdline = holder
        _err.print(f"[bold red]error:[/bold red] a host 'dolt' holds {host_dir} — stop it first")
        _err.print(f"  PID {pid}: {cmdline}")
        raise typer.Exit(1)

    if from_path:
        src = Path(from_path).expanduser().resolve()
        if not (src / ".dolt" / "repo_state.json").is_file():
            _err.print(f"[bold red]error:[/bold red] {src} is not a Dolt database (no .dolt/repo_state.json)")
            raise typer.Exit(1)
        sources = [src]
    else:
        sources = _dolt_migration_sources(host_dir, db)

    if not sources:
        _err.print(f"[bold red]error:[/bold red] found no database '{db}' to migrate")
        _err.print("  Looked in ~/.beads/shared-server/dolt/ and any quarantined <data>/dolt.*/")
        _err.print("  Point at it explicitly with --from <dir>, or run 'bd bootstrap' if the Dolt")
        _err.print("  remote has data.")
        raise typer.Exit(1)
    if len(sources) > 1:
        _err.print(f"[bold red]error:[/bold red] more than one database '{db}' found — pick one with --from:")
        for cand in sources:
            _err.print(f"    --from {cand}")
        raise typer.Exit(1)

    src = sources[0]
    # persist_gc's formatter, not a hardcoded MiB: a small database rounds to "0.0 MiB", which reads
    # as "there is nothing here" in the one prompt whose job is to tell the user what they are about
    # to copy (a real 40 KiB database printed exactly that in the 2026-07-25 end-to-end run).
    size = _fmt_size(_dir_size(src))
    mtime = datetime.fromtimestamp((src / ".dolt").stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    _out.print(f"[blue][INFO][/blue] migrate database '{db}'")
    _out.print(f"           from  {src}  ({size}, last written {mtime})")
    _out.print(f"           into  {dest}")
    _out.print("           the source is COPIED, not moved — it stays where it is")
    if not assume_yes:
        if not sys.stdin.isatty():
            _err.print("[bold red]error:[/bold red] not a terminal — re-run with --yes to confirm")
            raise typer.Exit(1)
        if not typer.confirm("Proceed?"):
            _out.print("[blue][INFO][/blue] aborted, nothing was written")
            raise typer.Exit(1)

    # Stage beside the destination and rename, so an interrupted copy never leaves a partial
    # database where the server would find one and serve it.
    staging = dest.with_name(dest.name + ".migrating")
    shutil.rmtree(staging, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, staging, symlinks=True)
    staging.rename(dest)
    if not (dest / ".dolt" / "repo_state.json").is_file():
        _err.print(f"[bold red]error:[/bold red] migration landed at {dest} but is not a Dolt database")
        raise typer.Exit(1)
    _out.print(f"[green][SUCCESS][/green] '{db}' migrated into {host_dir / 'dolt'}")


@app.command("volume-gc")
def volume_gc(
    prune: bool = typer.Option(False, "--prune", help="Remove volumes whose stack no longer resolves"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be removed without removing it"),
) -> None:
    """List the per-stack volumes; optionally reclaim ones whose stack is gone.

    The volume counterpart of `host-gc` (bd harnessed-8px.21.8). Since bd harnessed-8px.21.3 a
    container launch persists each stack's installed content in `harnessed-cfg-*` (~/.claude) and
    `harnessed-tools-*` (~/.local). Nothing else reclaims them: `rm` and `prune` tear down pods and
    containers, which by design leave NAMED volumes alone, and `clean` purges the profile cache
    rather than the volumes.

    ORPHAN = its stack no longer resolves in the catalog. The same signal `host-gc` uses, and for
    the same reason: the stack name is right there in the volume's labels, so an orphan can be
    named rather than inferred.

    Volumes are matched by LABEL, never by parsing their name — a stack name may contain the same
    hyphens the name format uses, so the name alone is ambiguous.

    NOT removed by --prune: the shared download cache (`harnessed-dl-cache`), which belongs to no
    single stack and is pure cache — deleting it only costs a re-download. Remove it by hand if you
    want the space back.

    A volume whose stack still resolves is NEVER removed. Reinstalling it is expensive, and a stack
    can be temporarily unresolvable because a catalog overlay is not mounted.
    """
    rt = _runtime()
    out = subprocess.run(
        [rt, "volume", "ls", "--filter", f"label={_VOL_LABEL}",
         "--format", "{{.Name}}\t{{.Labels}}"],
        capture_output=True, text=True,
    )
    rows: list[tuple[str, str, str, str, bool]] = []
    for line in out.stdout.splitlines():
        name, _, labels = line.strip().partition("\t")
        if not name:
            continue
        parsed = dict(
            kv.split("=", 1) for kv in labels.split(",") if "=" in kv
        )
        role = parsed.get(_VOL_LABEL, "?")
        stack = parsed.get(_VOL_STACK_LABEL, "")
        harness = parsed.get(_VOL_HARNESS_LABEL, "")
        if role == "shared":
            rows.append((name, role, "-", "-", False))
            continue
        # `find_in_catalog` NEVER raises — it returns the highest-precedence candidate path even
        # when nothing exists there, so the manifest has to be probed. The same test `host-gc` uses.
        orphan = not stack or not (
            paths.find_in_catalog("stacks", stack) / "stack.yaml"
        ).is_file()
        rows.append((name, role, stack, harness, orphan))

    if not rows:
        _out.print("No harnessed volumes found.")
        return

    for name, role, stack, harness, orphan in sorted(rows):
        tag = "[yellow]ORPHAN[/yellow]" if orphan else "[green]in use[/green]"
        _out.print(f"{tag}  {name}  role={role} stack={stack} harness={harness}")

    orphans = [r for r in rows if r[4]]
    if not prune:
        if orphans:
            _out.print(
                f"\n{len(orphans)} orphan(s). Re-run with --prune to remove "
                "(or --dry-run --prune to preview)."
            )
        return
    if not orphans:
        _out.print("\nNothing to prune.")
        return
    for name, _role, stack, _harness, _o in orphans:
        if dry_run:
            _out.print(f"[yellow]would remove[/yellow] {name} (stack '{stack}' no longer resolves)")
            continue
        _out.print(f"[blue][INFO][/blue] Removing {name} (stack '{stack}' no longer resolves)")
        subprocess.run([rt, "volume", "rm", "-f", name], capture_output=True)
    if not dry_run:
        _out.print(f"[green][SUCCESS][/green] Removed {len(orphans)} orphan volume(s)")


@app.command("svc")
def svc(
    action: str = typer.Argument(..., help="up | down | recreate | sync | migrate"),
    name: str = typer.Argument(..., help="Service name (services/<name>/service.yaml)"),
    stack: str = typer.Option(
        "", "--stack",
        help="Stack context (required for scope: project; recreate reads it off the container)",
    ),
    from_: str = typer.Option("", "--from", help="migrate: source database dir (skips discovery)"),
    assume_yes: bool = typer.Option(False, "--yes", help="migrate: skip the confirmation prompt"),
) -> None:
    """Manage a service sidecar (build+start, stop+remove, recreate, sync, or migrate its data in).

    `up`/`down`/`recreate` on a `scope: project` service act on THIS project's container
    (git-common-dir keyed), so they need `--stack` to resolve which persist entry holds the data.
    `recreate` is the exception: it rebuilds the container that is already here, and reads the stack
    back off that container (`harnessed.svc-stack`), so from inside the project it takes no flags at
    all. Pass `--stack` only to override, or when there is no container to read.

    `recreate` TEARS DOWN and REBUILDS the container — it is not `podman restart`, and deliberately
    is not named that. Mounts, published ports and env are fixed when a container is CREATED, so a
    restart reuses the existing one and reports success while changing nothing. Recreating is the
    only way a running sidecar picks up a change to how harnessed builds it. Data (the bind-mounted
    or named-volume /data) is untouched.

    `sync` execs the service's own sync command in its container. It exists because a `dolt
    sql-server`'s git sync (`bd dolt push` → refs/dolt/data) shells out to the dolt CLI, which only
    routes to a server on its OWN loopback — so the push can only run inside the service container,
    never in an agent container. Sync pushes to your git remote, so it is explicit, never automatic.

    `migrate` copies an existing database INTO this service's data dir — the half that re-asserting
    socket mode cannot do, since re-pointing `metadata.json` does not move the bytes. It is what the
    launch-time "names database X, which is not in ..." abort tells you to run.
    """
    rt = _runtime()
    project_path = Path.cwd().resolve()
    svc_def = load_service(None, name)
    key = _svc_project_key(svc_def, project_path)
    cname = _svc_container(name, key)

    if svc_def.scope == "project" and not stack and action == "recreate":
        # Recreating rebuilds the sidecar THAT IS HERE, and that container already records the stack
        # it was built from (_SVC_STACK_LABEL). Making the user re-supply it would be asking for
        # something the machine knows — and inviting a typo that silently rebuilds against a
        # different persist entry, i.e. a different data dir.
        stack = _svc_container_stack(rt, cname) or ""
    if svc_def.scope == "project" and not stack:
        _err.print(
            f"[bold red]error:[/bold red] service '{name}' is scope: project — pass --stack so its "
            f"data dir can be resolved (e.g. harnessed svc {action} {name} --stack my-stack)"
        )
        if action == "recreate":
            # The only way to reach here on a recreate: nothing to read the stack off of.
            _err.print(
                f"  ({cname} is not present, or predates the {_SVC_STACK_LABEL} label — after one "
                "run with --stack, recreate needs no flag here again.)"
            )
        raise typer.Exit(1)

    if action in ("up", "recreate"):
        # The SAME mount a launch computes (bd harnessed-wnf). `launch` widens the path-mirrored
        # folder to the parent of a bare repo so sibling worktrees are visible; passing the raw
        # project_path here gave a service started via `svc up` a git surface that excluded the
        # `.bare` parent — the very directory an `in_repo` .beads lives beside in that layout. With
        # `recreate` routing through this same call, the un-widened mount would have been baked into
        # every recreated container.
        # Only a scope: project service mirrors the workspace at all, and _resolve_mount_path
        # announces the widening — resolving it for a global sidecar would print advice about a
        # mount that service never gets.
        mount_path = (
            _resolve_mount_path(project_path, None) if svc_def.scope == "project" else project_path
        )
        _ensure_service(
            rt, name, stack=stack, project_path=project_path, mount_path=mount_path,
            force_recreate=(action == "recreate"),
        )
        verb = "recreated" if action == "recreate" else "is up"
        _out.print(f"[green][SUCCESS][/green] Service '{name}' {verb} ({cname})")
    elif action == "down":
        subprocess.run([rt, "rm", "-f", cname], capture_output=True)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' is down ({cname})")
    elif action == "sync":
        sync_cmd = (svc_def.raw.get("sync") or "").strip()
        if not sync_cmd:
            _err.print(f"[bold red]error:[/bold red] service '{name}' declares no `sync:` command")
            raise typer.Exit(1)
        if not _container_running(rt, cname):
            _err.print(f"[bold red]error:[/bold red] service '{name}' is not running ({cname})")
            raise typer.Exit(1)
        result = subprocess.run([rt, "exec", cname, "bash", "-lc", sync_cmd])
        if result.returncode != 0:
            _err.print(f"[bold red]error:[/bold red] sync failed for service '{name}'")
            raise typer.Exit(result.returncode)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' synced")
    elif action == "migrate":
        _svc_migrate(svc_def, stack, project_path, from_, assume_yes)
    else:
        _err.print(
            f"[bold red]error:[/bold red] unknown svc action '{action}' "
            "(use: up | down | recreate | sync | migrate)"
        )
        raise typer.Exit(1)


@app.command("aws-sso")
def aws_sso(
    action: str = typer.Argument("serve", help="serve — run the aws-sso ECS credential server for containers"),
    port: int = typer.Option(AWS_SSO_ECS_PORT, "--port", help="port the ECS server listens on"),
    bind_ip: str = typer.Option(
        "0.0.0.0",
        "--bind-ip",
        help="host IP to bind. 0.0.0.0 (default) is reachable from containers via "
        "host.containers.internal and gated by the bearer token; use 127.0.0.1 to keep it host-only "
        "(then containers can't reach it).",
    ),
) -> None:
    """Run the host aws-sso ECS credential server that stacks with `forward_aws_sso: true` consume.

    Walks host setup: verifies aws-sso is installed, ensures a bearer token exists (generating one on
    first run, loading it into the aws-sso secure store, and recording it for the launcher), then
    starts `aws-sso ecs server` in the foreground. In another terminal, load a role for containers to
    use with `aws-sso ecs load`. See docs/guides/aws-sso.md.
    """
    import secrets as _secrets
    import stat

    if action != "serve":
        _err.print(f"[bold red]error:[/bold red] unknown aws-sso action '{action}' (use: serve)")
        raise typer.Exit(1)

    if not shutil.which("aws-sso"):
        _err.print(
            "[bold red]error:[/bold red] `aws-sso` not found on PATH. Install aws-sso-cli first: "
            "https://synfinatic.github.io/aws-sso-cli/latest/"
        )
        raise typer.Exit(1)

    # Bearer token: single source of truth shared with the launcher. Generate + store on first run.
    token_file = paths.aws_sso_ecs_token_file()
    existing = ""
    try:
        existing = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass

    if existing:
        _out.print(f"[dim]Reusing bearer token from {token_file}.[/dim]")
    else:
        token = _secrets.token_hex(32)
        _out.print("Generating a new ECS-server bearer token and loading it into the aws-sso secure store…")
        res = subprocess.run(["aws-sso", "setup", "ecs", "auth", "--bearer-token", token])
        if res.returncode != 0:
            _err.print("[bold red]error:[/bold red] `aws-sso setup ecs auth` failed — see output above.")
            raise typer.Exit(1)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        _out.print(f"[green][SUCCESS][/green] Stored bearer token at {token_file} (0600).")

    if bind_ip not in ("127.0.0.1", "localhost"):
        _out.print(
            f"[yellow]note:[/yellow] binding {bind_ip}:{port} — reachable from containers "
            "(and any host on the network); access is gated by the bearer token above."
        )

    _out.print(
        "\n[bold]Container wiring[/bold] (injected automatically for stacks with "
        "[bold]forward_aws_sso: true[/bold]):\n"
        f"  AWS_CONTAINER_CREDENTIALS_FULL_URI = http://host.containers.internal:{port}/\n"
        "  AWS_CONTAINER_AUTHORIZATION_TOKEN  = Bearer <token>\n\n"
        "[bold]Next[/bold] — in another terminal, load the role containers should use:\n"
        "  [cyan]aws-sso ecs load[/cyan]   (interactive; fills the default slot)\n\n"
        f"Starting `aws-sso ecs server` on {bind_ip}:{port} — leave this running. Ctrl-C to stop.\n"
    )

    try:
        subprocess.run(["aws-sso", "ecs", "server", "--bind-ip", bind_ip, "--port", str(port)])
    except KeyboardInterrupt:
        _out.print("\n[dim]aws-sso ecs server stopped.[/dim]")


# Args after a standalone `--` are passthrough: appended verbatim to the launched harness command
# (e.g. `harnessed container-run claude -s S -- --chrome` runs `claude … --chrome`). Click treats
# `--` only as end-of-options and would bind the first suffix token to the `path` positional, so we
# split it off argv before Typer parses. Set by main(); read by both run verbs.
_passthrough: list[str] = []


def _extract_passthrough(argv: list[str]) -> list[str]:
    """Split argv at the first standalone `--`, stashing everything after it in `_passthrough` and
    returning the head. With no `--`, clears `_passthrough` and returns argv unchanged."""
    global _passthrough
    if "--" in argv:
        i = argv.index("--")
        _passthrough = argv[i + 1 :]
        return argv[:i]
    _passthrough = []
    return argv


def main() -> None:
    # No bare-stack shortcut: the leading token is a subcommand, full stop. It used to be "a stack
    # name unless it matches a registered command", which meant every new @app.command had to be
    # added to a hand-maintained `_COMMANDS` set or it silently became unreachable — `harnessed
    # update` parsing as `harnessed launch update` and failing with "Missing argument 'HARNESS'",
    # which reads like a usage error rather than a missing registration. With the stack named by
    # `--stack`, a bare leading token is a harness and there is nothing left to disambiguate.
    sys.argv = [sys.argv[0], *_extract_passthrough(sys.argv[1:])]
    app()


if __name__ == "__main__":
    main()
