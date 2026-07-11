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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

import typer
from rich.console import Console
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
_yaml = YAML(typ="safe", pure=True)

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
    """The installed source root (honors HARNESSED_DIR). Build context + catalog live under it."""
    return paths.repo_root()


def _stacks_dir() -> Path:
    """Repo catalog stacks dir — where `new` scaffolds. Enumeration goes through
    `paths.list_catalog_stacks` (unifies the user overlay), not this repo-only dir."""
    return _harnessed_dir() / "catalog" / "stacks"


def _agent_image(harness: str) -> str:
    """Resolve the agent's container image from catalog/agents/<harness>/agent.yaml (+ :latest)."""
    img = load_agent(harness).image
    return img if ":" in img else f"{img}:latest"


def _ensure_profile_dir(stack: str) -> Path:
    """Ensure the XDG profile directory exists and return it."""
    p = profile_dir(stack)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_local_catalog_links() -> None:
    """Ensure user overlay catalog dirs exist; create catalog/<kind>.local symlinks when in a repo checkout."""
    user_catalog_root = paths.user_catalog()
    for kind in ("agents", "recipes", "services", "stacks"):
        (user_catalog_root / kind).mkdir(parents=True, exist_ok=True)

    cwd_catalog = Path.cwd() / "catalog"
    if not cwd_catalog.is_dir():
        return

    for kind in ("agents", "recipes", "services", "stacks"):
        target = cwd_catalog / f"{kind}.local"
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
    inside a harnessed repo checkout (catalog/ present); leaves an existing docs/ alone.
    """
    cwd = Path.cwd()
    if not (cwd / "catalog").is_dir():
        return
    docs_dir = cwd / "docs"
    if docs_dir.exists():
        return
    try:
        origin_url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return
    wiki_url = re.sub(r"\.git$", "", origin_url) + ".wiki.git"
    try:
        _run(["git", "clone", wiki_url, str(docs_dir)])
    except subprocess.CalledProcessError:
        _err.print(f"[yellow]warning:[/yellow] could not clone docs wiki ({wiki_url}); docs/ left missing")


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
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


def _catalog_base(rt_path: str) -> Path:
    return _harnessed_dir() / "catalog" / "base" / rt_path


def _ensure_extra_tools() -> None:
    """Resolve the user's extra-tools list and stage it into the build context for the base build.

    Source of truth is USER-owned: `~/.config/harnessed/extra-tools.txt` (paths.extra_tools_path).
    Dockerfile.harnessed-base COPYs `catalog/base/extra-tools.txt` — a gitignored build artifact — so:

      1. Seed the config file from `catalog/base/extra-tools.default.txt` when it is absent (migrating
         a pre-move repo-root `extra-tools.txt` if one is still lying around), so a fresh clone or git
         worktree builds without the user hand-copying anything.
      2. Stage the resolved content into `catalog/base/extra-tools.txt` so the Dockerfile COPY finds it
         in-context. Regenerated every build — the config file always wins over the staged mirror.
    """
    user_file = paths.extra_tools_path()
    if not user_file.exists():
        legacy = _harnessed_dir() / "extra-tools.txt"  # pre-move repo-root location
        seed = legacy if legacy.exists() else _catalog_base("extra-tools.default.txt")
        if seed.exists():
            user_file.parent.mkdir(parents=True, exist_ok=True)
            user_file.write_text(seed.read_text())
    if user_file.exists():
        _catalog_base("extra-tools.txt").write_text(user_file.read_text())


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


def _build_images_cmd(rt: str, force: bool = False) -> None:
    """(Re)build the shared base + agent images (stack images are built lazily per stack)."""
    _ensure_extra_tools()
    hdir = _harnessed_dir()
    no_cache = os.environ.get("HARNESSED_PODMAN_NO_CACHE") == "true"
    cache_arg = ["--no-cache"] if no_cache else []
    secret_args = _corp_proxy_ca_secret_args()

    pairs = [
        (_BASE_IMAGE, _catalog_base("Dockerfile.harnessed-base")),
        (_CLAUDE_IMAGE, _catalog_base("Dockerfile.harnessed-claude")),
    ]
    for image, dockerfile in pairs:
        if force or not _image_exists(rt, image):
            _out.print(f"[blue][INFO][/blue] Building {image} ...")
            _run([rt, "build", "-t", image, "-f", str(dockerfile), *cache_arg, *secret_args, str(hdir)])
    _out.print("[green][SUCCESS][/green] harnessed images ready")


def _build_base_image(rt: str) -> None:
    """Force-(re)build the parameterised base so edits to Dockerfile.harnessed-base (the supply-chain
    scan script, extra-tools, scanner installs) propagate into every FROM-derived agent / hatago /
    stack image. Layer-cached: a no-op when the base Dockerfile is unchanged."""
    _ensure_extra_tools()
    no_cache = os.environ.get("HARNESSED_PODMAN_NO_CACHE") == "true"
    cache_arg = ["--no-cache"] if no_cache else []
    secret_args = _corp_proxy_ca_secret_args()
    _out.print(f"[blue][INFO][/blue] Building {_BASE_IMAGE} ...")
    _run([
        rt,
        "build",
        "-t",
        _BASE_IMAGE,
        "-f",
        str(_catalog_base("Dockerfile.harnessed-base")),
        *cache_arg,
        *secret_args,
        str(_harnessed_dir()),
    ])


def _build_agent_image(rt: str, harness: str) -> None:
    """(Re)build the agent image from its agent.yaml Dockerfile (podman layer cache decides whether
    anything actually rebuilds). Build args from agent.yaml are the single source of truth for pinned
    tool versions (e.g. OMP_VERSION) — the agent Dockerfile's ARG carries no default and is supplied
    here, so changing the pin here cache-busts exactly the version layer and onward."""
    agent = load_agent(harness)
    image = _agent_image(harness)
    if not _image_exists(rt, _BASE_IMAGE):
        _out.print("[yellow][WARNING][/yellow] harnessed-base not found. Building base first…")
        _build_images_cmd(rt, force=False)
    hdir = _harnessed_dir()
    dockerfile = hdir / agent.dockerfile if agent.dockerfile else _catalog_base(
        f"Dockerfile.harnessed-{harness}")
    build_args: list[str] = []
    for key, val in agent.build_args.items():
        build_args += ["--build-arg", f"{key}={val}"]
    _out.print(f"[blue][INFO][/blue] Building {image} ...")
    _run([rt, "build", "-t", image, "-f", str(dockerfile), *build_args, str(hdir)])


def _ensure_harness_image(rt: str, harness: str) -> None:
    """Build the agent image only if it is not present (launch-time lazy build)."""
    if not _image_exists(rt, _agent_image(harness)):
        _build_agent_image(rt, harness)


def _build_stack(rt: str, stack: str, root: Path | None = None, *, strict: bool = True) -> None:
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

    prof = _ensure_profile_dir(stack)
    # assemble emits to <build-dir>/profiles/<stack>; pass the dir that *contains* profiles/.
    build_root = paths.profiles_root().parent
    hdir = _harnessed_dir()

    _out.print(f"[blue][INFO][/blue] Assembling stack '{stack}' ...")
    try:
        result = assemble(root, stack, build_root, strict=strict)
    except (SchemaError, CollisionError) as exc:
        # Clean rejection (raw npm/npx, floating pin, name collision, missing recipe/agent) — a
        # build that is *meant* to fail should read as a one-line error, not a Python traceback.
        _err.print(f"[bold red]error:[/bold red] assembling stack '{stack}' failed: {exc}")
        raise typer.Exit(1)

    # Always rebuild the parameterised base first: the agent image below is `FROM harnessed-base`
    # (which now also bakes hatago + the time server — hatago-consolidation), so a stale base (e.g.
    # after editing Dockerfile.harnessed-base) would silently propagate into every derived image.
    # Cache-backed — a no-op when the base Dockerfile is unchanged.
    _build_base_image(rt)

    # (Re)build the agent base image so a changed agent Dockerfile / build_args (e.g. OMP_VERSION)
    # actually propagates — the derived image is `FROM` it. Cache-backed: a no-op when unchanged,
    # but a changed pin cache-busts the version layer and, in turn, the derived image's FROM.
    _build_agent_image(rt, load_stack(stack_dir).harness)

    # Always build the derived per-stack image: its FINAL layer is the supply-chain scan (BLD-02,
    # emit.write_derived_dockerfile), so every stack — not just ones shipping a recipe Dockerfile —
    # gets scanned. The scan runs over the agent's mise globals + recipe installs under ~/.claude.
    derived = _derived_image(stack)
    dockerfile = prof / f"Dockerfile.harnessed-{stack}"
    recipe_hash = compute_recipe_hash(stack_dir / "stack.yaml", result.recipes)
    _out.print(f"[blue][INFO][/blue] Building derived image {derived} (incl. supply-chain scan) ...")
    _build_derived_image(rt, derived, dockerfile, hdir, recipe_hash)
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
    if result.stack.harness == "opencode":
        _merge_baked_opencode(rt, derived, prof, result.stack)

    # Surface the advisory supply-chain report (baked by the derived image's final scan layer).
    _surface_scan_report(rt, derived, prof)

    # Build all service images referenced by this stack so they are ready before first run.
    # Layer-cached: a no-op when each service Dockerfile is unchanged.
    for svc_name in _service_refs(stack):
        _build_service_image(rt, svc_name)

    _out.print(f"[green][SUCCESS][/green] Stack '{stack}' built — profile: {prof}")


def _built_image_hash(rt: str, stack: str) -> str | None:
    """The `harnessed.recipe-hash` label baked into stack's derived image, or None if the image
    doesn't exist yet or was built before this label existed."""
    result = subprocess.run(
        [
            rt, "inspect", "--format",
            '{{if .Config.Labels}}{{index .Config.Labels "harnessed.recipe-hash"}}{{end}}',
            _derived_image(stack),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _reconcile_stacks(rt: str, root: Path | None, *, strict: bool) -> None:
    """Rebuild every catalog stack whose recipe-closure hash no longer matches its built image's
    `harnessed.recipe-hash` label (see `compute_recipe_hash`) — the reconciliation half of a bare
    `harnessed build`, so editing a shared recipe rebuilds every stack that uses it without the
    caller having to know or name them."""
    if root is not None:
        stacks_dir = root / "stacks"
        names = (
            sorted(p.name for p in stacks_dir.iterdir() if (p / "stack.yaml").is_file())
            if stacks_dir.is_dir() else []
        )
    else:
        names = paths.list_catalog_stacks()
    if not names:
        return

    _out.print(f"[blue][INFO][/blue] Reconciling {len(names)} stack(s) against their recipe hash ...")
    for name in names:
        stack_dir = (root / "stacks" / name) if root else paths.find_in_catalog("stacks", name)
        try:
            _, recipes = load_stack_with_recipes(root, name, strict=strict)
            expected = compute_recipe_hash(stack_dir / "stack.yaml", recipes)
        except (SchemaError, CollisionError) as exc:
            _err.print(f"[yellow]warn:[/yellow] skipping '{name}' (failed to resolve recipes: {exc})")
            continue

        current = _built_image_hash(rt, name)
        if current == expected:
            continue
        reason = "no built image" if current is None else "recipe hash changed"
        _out.print(f"[blue][INFO][/blue] Rebuilding stale stack '{name}' ({reason}) ...")
        _build_stack(rt, name, root, strict=strict)


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
      1. ~/.config/harnessed/.env.schema — user-global, resolved via varlock (opt-in: needs
         the schema present and `varlock` on PATH).
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

    global_schema = Path.home() / ".config" / "harnessed" / ".env.schema"
    if global_schema.is_file() and have_varlock:
        p = _varlock_resolve_env_file(global_schema.parent)
        if p:
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


def _build_derived_image(rt: str, derived: str, dockerfile: Path, hdir: Path, recipe_hash: str) -> None:
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
        str(hdir),
    ])


def _derived_image(stack: str) -> str:
    return f"harnessed-{stack}:latest"


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
        data = _yaml.load(gh_hosts.read_text())
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
        f"HOST_WORKSPACE_DIR={shlex.quote(str(mount_path))}",
    ]
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

def _svc_container(name: str) -> str:
    return f"harnessed-svc-{name}"


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
    """
    svc = load_service(None, name)
    svc_dir = paths.find_in_catalog("services", name)
    orig_dockerfile = svc_dir / "Dockerfile"
    _out.print(f"[blue][INFO][/blue] Building service image {svc.image} ...")
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


def _ensure_service(rt: str, name: str) -> None:
    """Build (if missing) and start (if not running) one host-published service sidecar.

    If the running container is stale (image rebuilt since it started), prompts the user to
    confirm recreation before the harness launches. Named-volume data is always preserved.
    In headless mode the recreation proceeds automatically.
    """
    svc = load_service(None, name)
    if not _image_exists(rt, svc.image):
        _build_service_image(rt, name)
    cname = _svc_container(name)
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
    _out.print(f"[blue][INFO][/blue] Starting service '{name}' on :{svc.port} ({cname})")
    run_cmd = [rt, "run", "-d", "--name", cname, "-p", f"{svc.port}:{svc.port}",
               *_corp_proxy_ca_mount_args()]
    if svc.volume:
        run_cmd += ["-v", f"{svc.volume}:/data"]
    run_cmd.append(svc.image)
    _run(run_cmd, capture_output=True)
    _install_corp_proxy_ca_in_container(rt, cname, best_effort=True)
    _wait_service_healthy(rt, cname, svc)



def _wait_service_healthy(rt: str, cname: str, svc: "ServiceDef", timeout: int = 60) -> None:
    """Wait for TCP port open, then exec svc.healthcheck inside the container until it passes.

    Two-phase: raw TCP first (fast, 30s), then the service's own healthcheck (full protocol,
    60s). For dolt this means waiting for MySQL-level auth readiness, not just the listener.
    Services without a healthcheck fall back to TCP only.
    """
    import socket
    import time

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


def _ensure_services(rt: str, stack: str) -> None:
    for name in _service_refs(stack):
        _ensure_service(rt, name)


def _collect_setup_notices(
    recipes: list[Recipe], project_path: Path, stack: str
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
    dismissed = paths.setup_dismissed_flag(stack, project_path).exists()
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


def _prompt_setup_notices(recipes: list[Recipe], project_path: Path, stack: str) -> None:
    """Show aggregated user-facing `setup:` notices host-side at launch and act on the choice.

    No-op when nothing qualifies (`_collect_setup_notices`) or stdin is not a TTY (headless/CI
    cannot answer — never block a scripted launch). Otherwise prints one bullet per recipe and
    prompts: [O]k (default, just launch), [D]ismiss (silence this stack's unconditional notices
    for this project, then launch), [Q]uit (abort the launch, exit 0). Case-insensitive; ^C also
    aborts. Conditional notices keep reappearing until their condition is satisfied regardless of
    a prior dismiss.
    """
    notices = _collect_setup_notices(recipes, project_path, stack)
    if not notices or not sys.stdin.isatty():
        return
    _out.print("\n[bold]Setup needed for this stack:[/bold]")
    for recipe in notices:
        assert recipe.setup is not None  # guaranteed by _collect_setup_notices
        _out.print(f"  • [bold]{recipe.name}[/bold]: {recipe.setup.summary}")
        _out.print(f"    see: {recipe.setup.reference}")
    choice = typer.prompt("[O]k / [D]ismiss (don't show again) / [Q]uit", default="O")
    choice = choice.strip().lower()
    if choice.startswith("q"):
        raise typer.Exit(0)
    if choice.startswith("d"):
        flag = paths.setup_dismissed_flag(stack, project_path)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")


# --- Typer commands ------------------------------------------------------------

@app.command()
def launch(
    stack: str = typer.Argument(..., help="Stack name (stacks/<name>/stack.yaml)"),
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

    if not is_built(stack):
        _err.print(f"[bold red]error:[/bold red] stack '{stack}' has no assembled profile (run: harnessed build {stack})")
        raise typer.Exit(1)

    # Guard against a stale profile: a recipe referenced by this stack may have been renamed/removed
    # (SchemaError) or edited (StaleProfileError) since the profile was built. is_built() only checks
    # presence, so without this a launch would silently run an orphaned/outdated image.
    try:
        staleness.check_profile_fresh(None, stack)
    except SchemaError as exc:
        _err.print(
            f"[bold red]error:[/bold red] stack '{stack}' references a recipe that no longer "
            f"resolves ({exc}) — run: harnessed build {stack}"
        )
        raise typer.Exit(1)
    except staleness.StaleProfileError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc} — run: harnessed build {stack}")
        raise typer.Exit(1)

    try:
        stk = load_stack(stack_dir)
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1)

    stack_from_overlay = stack_dir.resolve().is_relative_to(paths.user_catalog().resolve())

    harness = stk.harness
    # Prefer the derived per-stack image (recipe Dockerfile layers); fall back to the plain agent.
    derived = _derived_image(stack)
    harness_image = derived if _image_exists(rt, derived) else _agent_image(harness)
    prof = profile_dir(stack)
    relpath = project_relpath(project_path)
    inst = instance_name(stack, project_path)
    pod = inst

    # Ensure harness image exists (lazy-build for non-claude harnesses). hatago is baked into it now
    # (hatago-consolidation), so there is no separate hatago image to check for.
    _ensure_harness_image(rt, harness)

    # User-facing recipe `setup:` notices — shown host-side here (never baked into an agent identity
    # file), before ANY attach path (reuse/reattach/create) so they surface on every launch. Gating
    # and the [O]k/[D]ismiss/[Q]uit prompt live in _prompt_setup_notices; reuse launch_recipes below.
    _, launch_recipes = load_stack_with_recipes(None, stack)
    _prompt_setup_notices(launch_recipes, project_path, stack)

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

    # Start any shared-service sidecars this stack's recipes reference (host-published; reached from
    # the pod via host.containers.internal:<port>). Idempotent — skips services already running.
    _ensure_services(rt, stack)

    _out.print(f"[blue][INFO][/blue] Creating isolated pod: {pod} (harness + hatago)")
    _out.print(f"[blue][INFO][/blue] Project: {project_path} -> {CONTAINER_HOME / relpath}")
    if mount_path != project_path:
        _out.print(f"[blue][INFO][/blue] Mounting folder: {mount_path} (project lives under it)")
    if anchor_path != project_path:
        _out.print(f"[blue][INFO][/blue] Agent start folder: {project_path} (launched from {anchor_path})")

    launch_servers = _resolve_service_servers(_merge_servers(launch_recipes), None)
    required = emit.required_settings(launch_servers, launch_recipes, stk.permissions)
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
    harness_run = [
        rt, "run", "-d",
        *(["--pod", pod] if _rt_uses_pods(rt) else [f"--network=container:{pod}"]),
        "--name", inst,
        *[arg for f in secrets_env_files for arg in ("--env-file", str(f))],
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
        tail = _opencode_attach_cmd(profile_dir(stack), stack)
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
        None, help="Stack to assemble; omit to rebuild base images and reconcile all catalog stacks"
    ),
    root: Optional[str] = typer.Option(None, "--root", help="Alternate stacks/recipes root"),
    no_scans: bool = typer.Option(False, "--no-security-scans", help="Skip credentialed scans"),
    no_strict: bool = typer.Option(
        False, "--no-strict",
        help="Allow unknown recipe-manifest fields (disables the typo guardrail)",
    ),
    force: bool = typer.Option(False, "--force", help="Force rebuild of base images"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable podman layer cache for image builds"),
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

    With no `stack` argument: rebuilds the base/claude/hatago images, then reconciles every stack
    across the catalog (repo + user overlay) — comparing each stack's recipe-closure content hash
    (`compute_recipe_hash`) against the `harnessed.recipe-hash` label baked into its built image,
    and rebuilding any that are missing or stale. This is how editing a shared recipe propagates to
    every stack that uses it without having to name them one by one.

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
        _build_stack(rt, stack, root_path, strict=not no_strict)
    else:
        _build_images_cmd(rt, force=force)
        _reconcile_stacks(rt, root_path, strict=not no_strict)


@app.command("list")
def list_stacks() -> None:
    """List authored stacks and running harnessed instances."""
    rt = _runtime()
    _out.print("[bold]Authored stacks:[/bold]")
    for name in paths.list_catalog_stacks():
        built = "[green]built[/green]" if is_built(name) else "[yellow]not built[/yellow]"
        _out.print(f"  {name}  ({built})")
    _out.print("[bold]Running instances:[/bold]")
    subprocess.run([
        rt, "ps", "-a", "--filter", "name=harnessed-",
        "--format", "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}",
    ])


@app.command("stop")
def stop(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Stop every running instance of a stack."""
    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", f"name=harnessed-{stack}-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    for name in names:
        _out.print(f"[blue][INFO][/blue] Stopping {name}")
        subprocess.run([rt, "stop", name], capture_output=True)
    if not names:
        _out.print(f"No running instances for stack '{stack}'")


@app.command("rm")
def remove(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Remove every instance (stopped or running) of a stack."""
    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "-a", "--filter", f"name=harnessed-{stack}-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
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
    Instances never interactively attached (headless / externally driven) are left untouched.
    """
    import time

    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    # hatago no longer runs as a separate `{inst}-hatago` member (hatago-consolidation), so every
    # `harnessed-` container listed here is a prunable instance.
    members = [n.strip() for n in result.stdout.splitlines() if n.strip()]

    pruned = 0
    for inst in members:
        marker = _attach_marker(inst)
        if not marker.exists():
            continue  # never interactively attached — leave it alone
        # Prune ONLY on a confirmed-idle reading. `_session_active` returns None when `top` failed
        # (transient runtime hiccup): treat unknown as "leave it alone" so a momentary error never
        # tears down a live attached session. The next prune run retries.
        if _session_active(rt, inst) is not False:
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
    project: Optional[str] = typer.Option(None, "--project", help="Scratch project path"),
    keep: bool = typer.Option(False, "--keep", help="Keep instance after test"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON result"),
) -> None:
    """Capability test: launch --fresh headless + assert declared capabilities."""
    rt = _runtime()
    root = _harnessed_dir()

    reason = None
    if not is_built(stack):
        reason = "not built"
    else:
        try:
            staleness.check_profile_fresh(None, stack)
        except (SchemaError, staleness.StaleProfileError) as exc:
            reason = f"stale ({exc})"
    if reason:
        _out.print(f"[blue][INFO][/blue] Stack '{stack}' {reason} — assembling first")
        _build_stack(rt, stack)

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
               "python", "-m", "harnessed.cli", "test", stack, "--root", str(root)]
    elif shutil.which("python3"):
        cmd = ["python3", "-m", "harnessed.cli", "test", stack, "--root", str(root)]
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
    harness: str = typer.Option("claude", "--harness", help="Harness (claude|omp|opencode|antigravity|codex)"),
    recipes: str = typer.Option("", "--recipes", help="Comma-joined recipe names"),
) -> None:
    """Scaffold a stack manifest in stacks/<name>/stack.yaml."""
    if harness not in HARNESS_CONFIG_DIR:
        _err.print(f"[bold red]error:[/bold red] unsupported harness '{harness}' (supported: {', '.join(sorted(HARNESS_CONFIG_DIR))})")
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
        f"harness: {harness}",
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


@app.command("rescan")
def rescan() -> None:
    """Re-scan installed harnessed images online (post-build CVE catch)."""
    rt = _runtime()
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
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tf:
            tar_path = tf.name
        try:
            _run([rt, "save", image, "-o", tar_path])
            res = subprocess.run(
                ["uv", "run", "--no-project", "--quiet", "--with", "ruamel.yaml",
                 "python", "-m", "harnessed.cli", "scan-image-online", tar_path],
                env=run_env,
            )
            if res.returncode != 0:
                has_errors = True
        finally:
            Path(tar_path).unlink(missing_ok=True)
    if has_errors:
        raise typer.Exit(1)


# Subcommand names — anything else in the first position is treated as a stack name and routed
# to `launch` (the `harnessed <stack> [project] [--fresh]` shorthand the README documents and the
# capability test relies on).
_COMMANDS = {
    "launch", "init", "build", "list", "stop", "rm", "prune", "clean", "test", "new",
    "install", "uninstall", "rescan", "svc", "aws-sso",
}


@app.command("svc")
def svc(
    action: str = typer.Argument(..., help="up | down"),
    name: str = typer.Argument(..., help="Service name (services/<name>/service.yaml)"),
) -> None:
    """Manage a shared-service sidecar (build+start, or stop+remove). Services outlive instances."""
    rt = _runtime()
    if action == "up":
        _ensure_service(rt, name)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' is up")
    elif action == "down":
        cname = _svc_container(name)
        subprocess.run([rt, "rm", "-f", cname], capture_output=True)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' is down")
    else:
        _err.print(f"[bold red]error:[/bold red] unknown svc action '{action}' (use: up | down)")
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
