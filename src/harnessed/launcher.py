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
import os
import re
import shlex
import shutil
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

from . import emit
from . import paths
from . import persist
from . import staleness
from .paths import CONTAINER_HOME, instance_name, is_built, profile_dir, project_relpath
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
)

app = typer.Typer(
    name="harnessed",
    help="Launch composable harness stacks (claude/omp/opencode/antigravity/codex + hatago MCP hub).",
    add_completion=False,
)

_out = Console()
_err = Console(stderr=True)

# --- shared image names (base; agent images come from catalog/agents/<h>/agent.yaml) ---
# hatago is no longer a separate image — it is baked into harnessed-base and runs in-container
# (hatago-consolidation), so there is no _HATAGO_IMAGE.
_BASE_IMAGE = "harnessed-base:latest"
_CLAUDE_IMAGE = "harnessed-claude:latest"
_CONTAINER_HOME_STR = str(CONTAINER_HOME)

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
    if os.environ.get("HARNESSED_NO_SCANS") != "true":
        _say(f"[blue][INFO][/blue] Credentialed re-scan of {derived} (snyk + socket) ...")
        _scan_image_in_container(rt, derived)
    # Merge image-baked ~/.claude extensions into the profile only when a recipe actually baked some.
    if any((r.root / "Dockerfile").is_file() for r in result.recipes):
        _merge_baked_extensions(rt, derived, prof)

    # Replace the assemble-time settings.json FLOOR with the image's installer-written
    # settings.json (merged with harnessed's required grant). UNCONDITIONAL — a settings.json can
    # be baked by the agent BASE image, not only by a recipe Dockerfile, so this must NOT hide
    # behind the recipe-bake gate above.
    _merge_baked_settings(rt, derived, prof)

    # opencode identity (bd main-rlw): when the stack ships `instructions:`, read the image-baked
    # opencode.json, add a custom persona agent + a rules-file glob, and write the merged config
    # into the profile (mounted over the image path by _build_mount_args). Gated on the harness so
    # non-opencode stacks skip the (opencode-only) image read entirely.
    if harness == "opencode":
        _merge_baked_opencode(rt, derived, prof, result.stack)

    # Surface the advisory supply-chain report (baked by the derived image's final scan layer).
    _surface_scan_report(rt, derived, prof)

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


def _varlock_resolve_env_file(schema_dir: Path) -> Path | None:
    """Run `varlock load --format json` in schema_dir, writing a mode-0600 temp env-file of clean
    `KEY=VALUE` lines and returning its path. The caller MUST unlink the file after launch.

    Uses `--format json` (not `--format env`): varlock's `env` format double-quotes every value
    (`KEY="val"`), but podman `--env-file` does NOT strip quotes — it takes everything after `=`
    literally, so the quoted format lands `KEY='"val"'` in the container. JSON gives the raw
    unquoted values, which we write verbatim (podman reads the value to end-of-line, so no quoting
    or escaping is needed for single-line values like API keys/tokens).

    Assumes a `.env.schema` in schema_dir and `varlock` on PATH (checked by the caller).
    `OP_SERVICE_ACCOUNT_TOKEN` is appended when already set in the host env (headless / CI
    path — service-account bearer auth, no desktop app required). Returns None on varlock
    failure so the launch degrades gracefully rather than hard-failing.
    """
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
        return None

    try:
        resolved = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        _err.print(f"[bold red]error:[/bold red] varlock load returned invalid JSON: {e}")
        return None

    def _fmt(v: object) -> str:
        # podman env-file is KEY=VALUE with the value literal to end-of-line — no quoting needed.
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    lines = "".join(
        f"{k}={_fmt(v)}\n" for k, v in resolved.items() if v is not None
    )
    op_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if op_token:
        lines += f"OP_SERVICE_ACCOUNT_TOKEN={op_token}\n"

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
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        key, _, val = stripped.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out.append(f"{key}={val}")

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


def _build_derived_image(rt: str, derived: str, dockerfile: Path, ctx: str, recipe_hash: str) -> None:
    """Build the derived image. NEVER touches secrets or varlock — building must always succeed
    without credentials, so recipe install / skill / command / rule verification never depends on
    a secret resolving.

    The Dockerfile's scan layer (if present — `write_derived_dockerfile`'s `with_scan`) declares
    `RUN --mount=type=secret,id=snyk_token,required=false,...`, so it runs fine with no token at
    all (snyk warn-skips; osv-scanner + pip-audit advisory output still runs). A real, credentialed
    scan is a deliberately SEPARATE, explicit step — see `harnessed rescan`, which re-scans already
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


# Extension dirs an agent reads out of the Claude-canonical ~/.claude tree.
_EXT_SUBDIRS = ("skills", "commands", "plugins", "agents", "hooks", "rules")

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


def _merge_baked_extensions(rt: str, image: str, prof: Path) -> None:
    """Copy ~/.claude/{skills,commands,plugins,…} baked into `image` INTO the profile tree.

    A Dockerfile recipe delivers skills/commands/plugins by writing them into the image's
    ~/.claude. The launcher bind-mounts the profile's .claude over the container's, which would
    hide those image-baked files — so we extract them into the profile here, unifying
    recipe-fanned (profile) and image-baked (Dockerfile) extensions before launch.
    """
    def _copy(cid: str) -> None:
        claude = prof / ".claude"
        for sub in _EXT_SUBDIRS:
            dest = claude / sub
            dest.mkdir(parents=True, exist_ok=True)
            # `.` suffix copies directory CONTENTS (merge), not the dir itself. Missing source in
            # the image is fine (not every agent bakes every subdir).
            subprocess.run(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.claude/{sub}/.", str(dest)],
                capture_output=True,
            )

    _with_image_container(rt, image, _copy)


def _merge_baked_settings(rt: str, image: str, prof: Path) -> None:
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
    baked_text = _with_image_container(rt, image, _copy)

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ settings:[/yellow] {msg}")

    baked = emit.read_baked_settings(baked_text, warn=_warn)
    if baked is None:
        return  # nothing usable baked; the floor stub already on disk is correct.
    merged = emit.merge_settings(baked, required, warn=_warn)
    stub.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


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


def _merge_host_claude_settings(prof: Path, required: dict) -> None:
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


def _surface_scan_report(rt: str, image: str, prof: Path) -> None:
    """Copy the in-image supply-chain report (harnessed-scan, the derived image's final layer) to the
    profile dir and print a one-line advisory summary. The scan is advisory — this surfaces its posture
    host-side so the user sees it without digging into the image or scrolling the build log."""
    dest = prof / "scan-report.json"

    def _copy(cid: str) -> bool:
        subprocess.run(
            [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json", str(dest)],
            capture_output=True,
        )
        return True

    # create-fail (None) mirrors the old `if not cid: return` — leave any stale report untouched.
    if not _with_image_container(rt, image, _copy):
        return
    if not dest.is_file():
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


def _build_mount_args(
    harness: str,
    prof: Path,
    mount_path: Path,
) -> list[str]:
    """Assemble -v mount arguments for the harness container.

    `mount_path` is the host folder path-mirrored into the container (the project itself by default,
    or a parent dir via --mount-folder). The agent's cwd (start_dir) lives at or under it.
    """
    args: list[str] = []
    ctr_home = _CONTAINER_HOME_STR

    # .mcp.json → $CONTAINER_HOME/.mcp.json (claude only; --mcp-config points here)
    mcp_src = prof / ".mcp.json"
    if mcp_src.is_file() and harness == "claude":
        args += ["-v", f"{mcp_src}:{ctr_home}/.mcp.json:ro"]

    # settings.json → $CONTAINER_HOME/.claude/settings.json
    settings_src = prof / "settings.json"
    if settings_src.is_file() and harness in ("claude", "omp", "opencode"):
        args += ["-v", f"{settings_src}:{ctr_home}/.claude/settings.json:ro"]

    # claude/ profile tree (skills, commands, agents, hooks, rules)
    claude_src = prof / ".claude"
    if claude_src.is_dir() and harness in ("claude", "omp", "opencode"):
        for subdir in ("skills", "commands", "agents", "hooks", "rules"):
            d = claude_src / subdir
            if d.is_dir():
                args += ["-v", f"{d}:{ctr_home}/.claude/{subdir}:ro"]

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


def _claude_creds_seed_mount(harness: str, inst: str) -> list[str]:
    """Seed a per-instance copy of ~/.claude/.credentials.json, mounted rw.

    Claude Code periodically refreshes its OAuth access token by rewriting this file. A plain
    ro bind-mount of the host file (the old behavior) blocks that write: the in-container token
    goes stale once it expires mid-session, and the agent silently gets logged out with no way
    to recover short of recreating the container.

    Instead, copy the host's current credentials into a per-instance state file the FIRST time
    this instance launches (so the container starts with the host's latest token) and mount THAT
    copy rw. The container can then refresh its own copy freely without ever touching the host
    file — mirrors _claude_config_seed_mount's per-instance state-dir pattern.

    Only seeds once: a stopped container gets recreated (e.g. next morning, or after --fresh —
    neither tears down this state dir), and re-copying the host file on every launch would
    clobber whatever refreshed token the container itself wrote, reintroducing the exact
    "silently logged out" bug this mount exists to fix (the host copy only refreshes if Claude
    Code is run directly on the host, so it goes stale independently of the container's copy).
    """
    if harness not in ("claude", "omp"):
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    state_dir = state_root / "harnessed" / inst
    state_dir.mkdir(parents=True, exist_ok=True)
    stub = state_dir / "credentials.json"

    if not stub.is_file():
        host_creds = Path.home() / ".claude" / ".credentials.json"
        if not host_creds.is_file():
            return []
        stub.write_bytes(host_creds.read_bytes())
        stub.chmod(0o600)

    return ["-v", f"{stub}:{_CONTAINER_HOME_STR}/.claude/.credentials.json:rw"]


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


def _init_shell_prologue(stack: str, project_path: Path, mount_path: Path) -> str:
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
    main_repo = paths.git_common_dir(project_path) or project_path
    parts = [
        # Rootless podman on macOS maps host UIDs through the VM; git refuses to operate in mounted
        # dirs ("dubious ownership") — breaking mise templates that shell out to git. Use git's
        # env-var config mechanism (git 2.32+, Ubuntu 24.04 ships 2.43) instead of writing to
        # ~/.gitconfig: the launcher mounts the host's ~/.gitconfig :ro, so any write attempt
        # fails with "Device or resource busy". These env vars are inherited by mise and all
        # subprocesses it spawns, including the git invocations inside mise templates.
        "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0='safe.directory' GIT_CONFIG_VALUE_0='*'",
        "export "
        f"PROJECT_DIR={shlex.quote(str(project_path))} "
        f"MAIN_REPO_DIR={shlex.quote(str(main_repo))} "
        f"CONTAINER_WORKSPACE_DIR={shlex.quote(str(mount_path))} "
        f"HOST_WORKSPACE_DIR={shlex.quote(str(mount_path))} "
        # The host $HOME, which is NOT the container's ($HOME is /home/harnessed in the pod). A
        # `scope: global` persist entry is mounted path-preserving, so a recipe whose tool reads a
        # dotdir under the host home (e.g. pulumi's ~/.pulumi) must point the tool at the mirrored
        # path — `$HOST_HOME/.pulumi`, not `~/.pulumi`. This export is that handle.
        f"HOST_HOME={shlex.quote(str(Path.home()))}",
    ]
    # Socket-backed project-scoped services (e.g. beads-server): export the container-side socket
    # path so a recipe's `setup:` can reference it verbatim instead of recomputing path arithmetic.
    for var, sock in svc_socket_env(stack, project_path).items():
        parts.append(f"export {var}={shlex.quote(sock)}")
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


def _service_data_dir(svc: "ServiceDef", stack: str, project_path: Path) -> tuple[Path, str, str]:
    """Resolve a project-scoped service's data dir → (host_dir, agent_container_path, location).

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
            return host_dir, f"{_CONTAINER_HOME_STR}/{entry.name}", "host"

    raise SchemaError(
        f"service '{svc.name}' declares data.persist: '{svc.data_persist}', but no recipe in stack "
        f"'{stack}' declares a persist entry with that name"
    )


def svc_socket_env(stack: str, project_path: Path) -> dict[str, str]:
    """Container-side socket path for each socket-backed project-scoped service in the stack.

    Exported into the attach shell (see _init_shell_prologue) as HARNESSED_<NAME>_SOCKET so a
    recipe's `setup:` can reference the socket without recomputing the launcher's path arithmetic —
    e.g. `bd init --server --external --server-socket "$HARNESSED_BEADS_SERVER_SOCKET"`.
    """
    env: dict[str, str] = {}
    for name in _service_refs(stack):
        svc = load_service(None, name)
        if not (svc.scope == "project" and svc.is_socket_only):
            continue
        _, agent_dir, _ = _service_data_dir(svc, stack, project_path)
        var = "HARNESSED_" + svc.name.upper().replace("-", "_") + "_SOCKET"
        env[var] = f"{agent_dir}/{svc.socket}"
    return env


def _service_refs(stack: str) -> list[str]:
    """Distinct service names a stack requires as host-published sidecars.

    Two sources, unioned (first-seen order, de-duped): (1) recipe `service:` MCP-server refs
    (the assembler proxies these by URL), and (2) the stack's own `services:` list — sidecars a
    stack attaches by reference that have NO MCP surface (e.g. a shared `dolt sql-server`, whose
    wire protocol is MySQL, not MCP, so it cannot be a `service:` MCP ref). Both feed
    `_ensure_services`, which starts each one idempotently at launch.
    """
    stk, recipes = load_stack_with_recipes(None, stack)
    names: list[str] = []
    for recipe in recipes:
        for server in recipe.servers:
            if server.service and server.service not in names:
                names.append(server.service)
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


def _ensure_service(
    rt: str,
    name: str,
    stack: str = "",
    project_path: Path | None = None,
    mount_path: Path | None = None,
) -> None:
    """Build (if missing) and start (if not running) one service sidecar.

    `scope: global` → the original shape: one container, `-p <port>:<port>`, named volume at /data.

    `scope: project` → one container per project (git-common-dir keyed), whose /data is a BIND MOUNT
    of the persist dir the owning recipe declared (see _service_data_dir), and which publishes no
    port when socket-backed. For an `in_repo` data dir the workspace is also mounted
    path-preserving, because the service needs the git repo itself: bd's `dolt push` (the
    refs/dolt/data sync) shells out to the dolt CLI, which only routes to a server on ITS OWN
    loopback — so the sync can only ever run inside this container, not in an agent container.

    If the running container is stale (image rebuilt since it started), prompts the user to
    confirm recreation before the harness launches. Data (named volume or bind mount) is always
    preserved. In headless mode the recreation proceeds automatically.
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
    if _container_running(rt, cname):
        if _container_stale(rt, cname, svc.image):
            headless = os.environ.get("HARNESSED_HEADLESS", "false").lower() == "true"
            _err.print(
                f"[yellow]warning:[/yellow] service '{name}' is running on a stale build of "
                f"{svc.image} — the image was rebuilt since this container started."
            )
            _err.print(f"  Will run: {rt} rm -f {cname}  (named-volume data is preserved)")
            if not headless and sys.stdin.isatty():
                if not typer.confirm("Recreate now to continue?", default=True):
                    _err.print(
                        f"[bold red]error:[/bold red] cannot launch with stale service '{name}'. "
                        f"Fix manually: harnessed svc down {name} && harnessed svc up {name}"
                    )
                    raise typer.Exit(1)
            subprocess.run([rt, "rm", "-f", cname], capture_output=True)
            # fall through to start below
        else:
            return
    # Remove any stopped leftover with the same name before (re)starting.
    subprocess.run([rt, "rm", "-f", cname], capture_output=True)
    where = f"socket {svc.socket}" if svc.is_socket_only else f":{svc.port}"
    _out.print(f"[blue][INFO][/blue] Starting service '{name}' on {where} ({cname})")
    run_cmd = [rt, "run", "-d", "--name", cname, *_corp_proxy_ca_mount_args()]
    if not svc.is_socket_only:
        run_cmd += ["-p", f"{svc.port}:{svc.port}"]

    if svc.scope == "project":
        assert project_path is not None  # guarded above
        host_dir, agent_dir, location = _service_data_dir(svc, stack, project_path)
        persist.guard_ownership(host_dir)
        host_dir.mkdir(parents=True, exist_ok=True)
        # keep-id: the service writes as the invoking user, so bind-mounted bytes stay host-owned
        # (a dolt data dir written by a foreign uid would EACCES for every agent container).
        run_cmd += ["--userns=keep-id", "-v", f"{host_dir}:/data:rw"]
        if svc.is_socket_only:
            # The CLIENT-visible socket path — NOT this container's /data/run/... view of it. A
            # service that records a socket path for its clients (beads writes it into
            # .beads/metadata.json) must record the path THEY use, or every client dials a path that
            # does not exist in its mount namespace.
            run_cmd += ["-e", f"HARNESSED_SOCKET_PATH={agent_dir}/{svc.socket}"]
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
    _run(run_cmd, capture_output=True)
    _install_corp_proxy_ca_in_container(rt, cname, best_effort=True)
    _wait_service_healthy(rt, cname, svc)



def _wait_service_healthy(rt: str, cname: str, svc: "ServiceDef", timeout: int = 60) -> None:
    """Wait for the service to accept traffic, then exec svc.healthcheck until it passes.

    Two-phase for a published service: raw TCP first (fast, 30s), then the service's own
    healthcheck (full protocol, 60s). For dolt this means waiting for MySQL-level auth readiness,
    not just the listener. Services without a healthcheck fall back to TCP only.

    A socket-backed service publishes no port, so there is nothing to TCP-probe: its healthcheck
    (exec'd in the container, where the socket lives) IS the readiness signal.
    """
    import socket
    import time

    if not svc.is_socket_only:
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", svc.port), timeout=1):
                    break
            except OSError:
                time.sleep(1)

    if not svc.healthcheck:
        return

    for _ in range(timeout):
        result = subprocess.run(
            [rt, "exec", cname, "bash", "-c", svc.healthcheck],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)

    _err.print(f"[yellow][WARNING][/yellow] service '{svc.name}' healthcheck did not pass within {timeout}s")


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
    right state.
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                continue  # condition satisfied → suppress
        elif dismissed:
            continue
        out.append(recipe)
    return out


def _prompt_setup_notices(recipes: list[Recipe], project_path: Path, stack: str, harness: str) -> bool:
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
        _out.print(f"  • [bold]{recipe.name}[/bold]: {recipe.setup.summary}")
        _out.print(f"    see: {recipe.setup.reference}")
    choice = typer.prompt(
        "[O]k / [T]erminal (shell in the container) / [D]ismiss (don't show again) / [Q]uit",
        default="O",
    )
    choice = choice.strip().lower()
    if choice.startswith("q"):
        raise typer.Exit(0)
    if choice.startswith("d"):
        flag = paths.setup_dismissed_flag(stack, harness, project_path)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    return choice.startswith("t")


# --- Typer commands ------------------------------------------------------------

@app.command()
def launch(
    stack: str = typer.Argument(..., help="Stack name (stacks/<name>/stack.yaml)"),
    harness: str = typer.Argument(..., help="Harness to use (claude|omp|opencode|antigravity|codex)"),
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
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
) -> None:
    """Launch an isolated harness stack against a project directory."""
    if harness not in HARNESS_CONFIG_DIR:
        _err.print(
            f"[bold red]error:[/bold red] unsupported harness '{harness}' "
            f"(supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})"
        )
        raise typer.Exit(1)
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
                _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell)
                return
        else:
            _out.print(f"[blue][INFO][/blue] Attaching to running instance: {inst}")
            _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell)
            return
    # Stopped leftover: a previous non-ephemeral session exited without tearing down its pod (only
    # --rm cleans up). A same-name `pod create` would fail "name already in use", so remove the
    # stopped instance and recreate. A running instance is re-attached via the guard above.
    if _stopped_leftover(rt, inst, pod):
        _out.print(f"[blue][INFO][/blue] Recreating stopped instance '{inst}' from a prior session …")
        _pod_teardown(rt, inst, pod)

    # Recipe init (Model A) now runs inside the attach shell (_attach → _init_shell_prologue), not a
    # transient container — so init-derived env reaches the agent. Nothing to do here at pod-create.

    # Start any service sidecars this stack's recipes reference. Idempotent — skips services already
    # running. Global services are host-published (reached from the pod via
    # host.containers.internal:<port>); project-scoped ones bind-mount this project's persist dir and
    # are reached through a unix socket inside it, so they need the project/mount context.
    _ensure_services(rt, stack, project_path=project_path, mount_path=mount_path)

    _out.print(f"[blue][INFO][/blue] Creating isolated pod: {pod} (harness + hatago)")
    _out.print(f"[blue][INFO][/blue] Project: {project_path} -> {CONTAINER_HOME / relpath}")
    if mount_path != project_path:
        _out.print(f"[blue][INFO][/blue] Mounting folder: {mount_path} (project lives under it)")
    if anchor_path != project_path:
        _out.print(f"[blue][INFO][/blue] Agent start folder: {project_path} (launched from {anchor_path})")

    launch_servers = _resolve_service_servers(_merge_servers(launch_recipes), None)
    required = emit.required_settings(launch_servers, launch_recipes, stk.permissions, harness)
    if harness in ("claude", "omp", "opencode"):
        _merge_host_claude_settings(prof, required)

    # Build mount args.
    mount_args = _build_mount_args(harness, prof, mount_path)
    # Seed a token-free ~/.claude.json stub so Claude skips onboarding (auth = the rw credential).
    mount_args += _claude_config_seed_mount(harness, inst)
    # Seed + mount (rw) a per-instance copy of Claude's OAuth credentials so in-container token
    # refresh doesn't get blocked by a ro mount (was the "gets logged out" bug).
    mount_args += _claude_creds_seed_mount(harness, inst)
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
        mount_args += _aws_sso_ecs_forward_args()

    # Resolve launch-time secrets, layered global → project (project wins on conflict). Returns the
    # ordered --env-file list and the subset of temp files to unlink after launch.
    secrets_env_files, secrets_temp_files = _resolve_launch_secrets(project_path)

    # Pod network.
    net = os.environ.get("HARNESSED_NET", "")

    # Create pod.
    if _rt_uses_pods(rt):
        pod_cmd = [rt, "pod", "create", "--name", pod, "--userns=keep-id"]
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
    # Socket-backed project services (beads-server) as REAL container env, not only an attach-shell
    # export: `_init_shell_prologue` reaches the interactive shell and nothing else, so a `podman
    # exec`, a hook, or any subprocess saw $HARNESSED_BEADS_SERVER_SOCKET unset — and bd silently
    # accepts an EMPTY --server-socket, falling back to its old TCP config instead of failing. Set it
    # on the container so every process in it agrees.
    socket_env = [arg for var, sock in svc_socket_env(stack, project_path).items()
                  for arg in ("-e", f"{var}={sock}")]
    harness_run = [
        rt, "run", "-d",
        *(["--pod", pod] if _rt_uses_pods(rt) else [f"--network=container:{pod}"]),
        "--name", inst,
        *[arg for f in secrets_env_files for arg in ("--env-file", str(f))],
        *socket_env,
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

    _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell)


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
) -> None:
    """Exec into the running instance with the harness command.

    Default: os.execvp hands the TTY to the container natively (clean attach, no post-exit hook).
    ephemeral (--rm): run the exec as a child so the pod can be torn down when the session exits.
    start_dir: working directory for the agent (defaults to project_path; --agent-start-folder).
    shell (--shell): drop into an interactive bash instead of starting the harness.

    Recipe init (Model A): the attach shell exports the path contract and runs each recipe's
    `init.run` inline (fail-fast) BEFORE exec-ing the harness, so init-derived env reaches the agent.
    """
    mise_init = "source ~/.bashrc && mise trust -a 2>/dev/null"
    init_prologue = _init_shell_prologue(stack, project_path, mount_path)

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
    """Write a ~/.local/bin/<stack> launcher shim that runs `harnessed <stack>`."""
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
    shim.write_text(
        f"#!/usr/bin/env bash\nexec {shlex.quote(harnessed_bin)} {shlex.quote(stack)} \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    _out.print(f"[green][SUCCESS][/green] Installed shim: {shim} -> harnessed {stack}")
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


def _scan_image_in_container(rt: str, image: str) -> bool:
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
    try:
        res = subprocess.run([
            rt, "run", "--rm",
            *[arg for f in env_files for arg in ("--env-file", str(f))],
            image, "harnessed-scan",
        ])
        return res.returncode == 0
    finally:
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
_COMMANDS = {
    "launch", "init", "build", "list", "stop", "rm", "prune", "clean", "test", "new",
    "install", "uninstall", "scan", "rescan", "svc", "aws-sso",
}


@app.command("svc")
def svc(
    action: str = typer.Argument(..., help="up | down | sync"),
    name: str = typer.Argument(..., help="Service name (services/<name>/service.yaml)"),
    stack: str = typer.Option("", "--stack", help="Stack context (required for scope: project)"),
) -> None:
    """Manage a service sidecar (build+start, stop+remove, or sync).

    `up`/`down` on a `scope: project` service act on THIS project's container (git-common-dir keyed),
    so they need `--stack` to resolve which persist entry holds the data.

    `sync` execs the service's own sync command in its container. It exists because a `dolt
    sql-server`'s git sync (`bd dolt push` → refs/dolt/data) shells out to the dolt CLI, which only
    routes to a server on its OWN loopback — so the push can only run inside the service container,
    never in an agent container. Sync pushes to your git remote, so it is explicit, never automatic.
    """
    rt = _runtime()
    project_path = Path.cwd().resolve()
    svc_def = load_service(None, name)
    if svc_def.scope == "project" and not stack:
        _err.print(
            f"[bold red]error:[/bold red] service '{name}' is scope: project — pass --stack so its "
            "data dir can be resolved (e.g. harnessed svc up beads-server --stack my-stack)"
        )
        raise typer.Exit(1)
    key = _svc_project_key(svc_def, project_path)
    cname = _svc_container(name, key)

    if action == "up":
        _ensure_service(rt, name, stack=stack, project_path=project_path, mount_path=project_path)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' is up ({cname})")
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
    else:
        _err.print(f"[bold red]error:[/bold red] unknown svc action '{action}' (use: up | down | sync)")
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


def main() -> None:
    import sys

    argv = sys.argv[1:]
    # Find the first non-option token; if it is not a known subcommand, it is a stack name and we
    # prepend `launch` so `harnessed tracer-time …` == `harnessed launch tracer-time …`.
    for tok in argv:
        if tok.startswith("-"):
            continue
        if tok not in _COMMANDS:
            sys.argv = [sys.argv[0], "launch", *argv]
        break
    app()


if __name__ == "__main__":
    main()
