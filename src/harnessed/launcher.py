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
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import paths
from .paths import CONTAINER_HOME, HATAGO_PORT, instance_name, is_built, profile_dir, project_relpath
from .assemble import assemble
from .synclinks import CollisionError
from .schema import (
    HARNESS_CONFIG_DIR,
    SchemaError,
    load_agent,
    load_service,
    load_stack,
    load_stack_with_recipes,
)

app = typer.Typer(
    name="harnessed",
    help="Launch composable harness stacks (claude/omp/opencode/gemini/antigravity/codex + hatago MCP hub).",
    add_completion=False,
)

_out = Console()
_err = Console(stderr=True)

# --- shared image names (base + hatago; agent images come from catalog/agents/<h>/agent.yaml) ---
_BASE_IMAGE = "harnessed-base:latest"
_CLAUDE_IMAGE = "harnessed-claude:latest"
_HATAGO_IMAGE = "harnessed-hatago:latest"
_CONTAINER_HOME_STR = str(CONTAINER_HOME)

# Attach command for each harness inside the container.
_HARNESS_ATTACH_CMD = {
    "claude": "claude --mcp-config '{mcp_cfg}' --strict-mcp-config",
    "omp": "omp --profile '{instance}'",
    "opencode": "opencode",
    "gemini": "gemini",
    "antigravity": "agy",
    "codex": "codex",
}


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


def _rt_uses_pods(rt: str) -> bool:
    return rt == "podman"


def _harnessed_dir() -> Path:
    """The installed source root (honors HARNESSED_DIR). Build context + catalog live under it."""
    return paths.repo_root()


def _stacks_dir() -> Path:
    """Repo catalog stacks dir (where `new` writes; `list` also scans the user catalog)."""
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


def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, **kwargs)


def _catalog_base(rt_path: str) -> Path:
    return _harnessed_dir() / "catalog" / "base" / rt_path


def _build_images_cmd(rt: str, force: bool = False) -> None:
    """(Re)build the shared base + hatago images (agent images are built lazily per stack)."""
    hdir = _harnessed_dir()
    pairs = [
        (_BASE_IMAGE, _catalog_base("Dockerfile.harnessed-base")),
        (_CLAUDE_IMAGE, _catalog_base("Dockerfile.harnessed-claude")),
        (_HATAGO_IMAGE, _catalog_base("Dockerfile.hatago")),
    ]
    for image, dockerfile in pairs:
        if force or not _image_exists(rt, image):
            _out.print(f"[blue][INFO][/blue] Building {image} ...")
            _run([rt, "build", "-t", image, "-f", str(dockerfile), str(hdir)])
    _out.print("[green][SUCCESS][/green] harnessed images ready")


def _ensure_harness_image(rt: str, harness: str) -> None:
    """Build the agent image (from its agent.yaml Dockerfile) if it is not present."""
    agent = load_agent(harness)
    image = _agent_image(harness)
    if not _image_exists(rt, image):
        if not _image_exists(rt, _BASE_IMAGE):
            _out.print("[yellow][WARNING][/yellow] harnessed-base not found. Building base first…")
            _build_images_cmd(rt, force=False)
        hdir = _harnessed_dir()
        dockerfile = hdir / agent.dockerfile if agent.dockerfile else _catalog_base(
            f"Dockerfile.harnessed-{harness}")
        _out.print(f"[blue][INFO][/blue] Building {image} ...")
        _run([rt, "build", "-t", image, "-f", str(dockerfile), str(hdir)])


def _build_stack(rt: str, stack: str, root: Path | None = None) -> None:
    """Assemble a stack IN-PROCESS (host-native, emit-only — no tool container) + build hatago.

    `root` is an optional single catalog root (tests); None resolves across the catalog roots
    (repo catalog/ + user ~/.config/harnessed/catalog, user wins).
    """
    stack_dir = (root / "stacks" / stack) if root else paths.find_in_catalog("stacks", stack)
    if not (stack_dir / "stack.yaml").is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_dir}/stack.yaml)")
        raise typer.Exit(1)

    prof = _ensure_profile_dir(stack)
    # assemble emits to <build-dir>/profiles/<stack>; pass the dir that *contains* profiles/.
    build_root = paths.profiles_root().parent

    _out.print(f"[blue][INFO][/blue] Assembling stack '{stack}' ...")
    try:
        result = assemble(root, stack, build_root)
    except (SchemaError, CollisionError) as exc:
        # Clean rejection (raw npm/npx, floating pin, name collision, missing recipe/agent) — a
        # build that is *meant* to fail should read as a one-line error, not a Python traceback.
        _err.print(f"[bold red]error:[/bold red] assembling stack '{stack}' failed: {exc}")
        raise typer.Exit(1)

    _out.print(f"[blue][INFO][/blue] Building {_HATAGO_IMAGE} for stack '{stack}' ...")
    hdir = _harnessed_dir()
    _run([rt, "build", "-t", _HATAGO_IMAGE, "-f", str(_catalog_base("Dockerfile.hatago")), str(hdir)])

    # Dockerfile recipes: build the derived per-stack image from the emitted Dockerfile, then merge
    # its baked ~/.claude extensions into the profile so they are visible at runtime (the profile
    # mount would otherwise shadow image-baked skills/commands). Skipped when no recipe ships a
    # Dockerfile — then the stack runs the plain agent image.
    if any((r.root / "Dockerfile").is_file() for r in result.recipes):
        derived = _derived_image(stack)
        dockerfile = prof / f"Dockerfile.harnessed-{stack}"
        _out.print(f"[blue][INFO][/blue] Building derived image {derived} ...")
        _run([rt, "build", "-t", derived, "-f", str(dockerfile), str(hdir)])
        _merge_baked_extensions(rt, derived, prof)

    _out.print(f"[green][SUCCESS][/green] Stack '{stack}' built — profile: {prof}")


def _derived_image(stack: str) -> str:
    return f"harnessed-{stack}:latest"


# Extension dirs an agent reads out of the Claude-canonical ~/.claude tree.
_EXT_SUBDIRS = ("skills", "commands", "plugins", "agents", "hooks", "rules")


def _merge_baked_extensions(rt: str, image: str, prof: Path) -> None:
    """Copy ~/.claude/{skills,commands,plugins,…} baked into `image` INTO the profile tree.

    A Dockerfile recipe delivers skills/commands/plugins by writing them into the image's
    ~/.claude. The launcher bind-mounts the profile's .claude over the container's, which would
    hide those image-baked files — so we extract them into the profile here, unifying
    recipe-fanned (profile) and image-baked (Dockerfile) extensions before launch.
    """
    cid = subprocess.run(
        [rt, "create", image], capture_output=True, text=True,
    ).stdout.strip()
    if not cid:
        return
    try:
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
    finally:
        subprocess.run([rt, "rm", "-f", cid], capture_output=True)


# --- Pod / container lifecycle helpers -----------------------------------------

def _pod_teardown(rt: str, instance: str, pod: str) -> None:
    if _rt_uses_pods(rt):
        subprocess.run([rt, "pod", "rm", "-f", pod], capture_output=True)
    else:
        for name in (instance, f"{instance}-hatago"):
            subprocess.run([rt, "rm", "-f", name], capture_output=True)


def _apply_firewall(rt: str, instance: str) -> None:
    if os.environ.get("NO_FIREWALL", "false").lower() == "true":
        return
    # egress-firewall.sh is mounted at /usr/local/sbin/egress-firewall by _build_mount_args.
    subprocess.run([
        rt, "exec", instance, "bash", "/usr/local/sbin/egress-firewall",
    ], capture_output=True)


def _wait_hatago(rt: str, instance: str, port: int = HATAGO_PORT, timeout: int = 30) -> None:
    import time
    _out.print(f"[blue][INFO][/blue] Waiting for hatago hub on :{port} ...")
    for _ in range(timeout):
        result = subprocess.run(
            [rt, "exec", instance, "bash", "-lc",
             f"timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/{port}' 2>/dev/null"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)


def _build_mount_args(
    harness: str,
    prof: Path,
    project_path: Path,
    relpath: str,
) -> list[str]:
    """Assemble -v mount arguments for the harness container."""
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

    # History dirs (rw) — sourced from host $HOME for session persistence.
    home = str(Path.home())
    for rel in (".claude/projects", ".claude/file-history", ".claude/tasks",
                ".claude/session-env", ".claude/todos"):
        host_d = Path(home) / rel
        host_d.mkdir(parents=True, exist_ok=True)
        args += ["-v", f"{host_d}:{ctr_home}/{rel}:rw"]

    # omp: the whole agent dir (auth + sessions) is a per-instance mount seeded by
    # _omp_auth_seed_mount (appended in launch()) — it supersedes the old per-slug session mount.

    # Auth mounts (ro credentials)
    creds = Path(home) / ".claude" / ".credentials.json"
    if creds.is_file():
        args += ["-v", f"{creds}:{ctr_home}/.claude/.credentials.json:ro"]

    # egress-firewall.sh (run inside the container by _apply_firewall).
    fw = _catalog_base("egress-firewall.sh")
    if fw.is_file():
        args += ["-v", f"{fw}:/usr/local/sbin/egress-firewall:ro"]

    # Path mirroring (MNT2-02): project accessible at its host absolute path inside container.
    args += ["-v", f"{project_path}:{project_path}"]

    return args


def _claude_config_seed_mount(harness: str, inst: str) -> list[str]:
    """Mount a minimal, token-free ~/.claude.json stub so Claude Code skips first-run onboarding.

    The real OAuth token is the read-only ~/.claude/.credentials.json mount (see
    _build_mount_args). But Claude Code *also* gates its onboarding (the "Select login method"
    screen) on ~/.claude.json — a credentialed container with no .claude.json still shows
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


# Host omp state we DON'T carry into the isolated pod — only auth (auth_credentials +
# auth_schema_version) survives; the container's omp recreates these on first run.
_OMP_HISTORY_TABLES = (
    "threads", "jobs", "usage_history", "usage_cost_history",
    "model_usage", "stage1_outputs", "cache",
)


def _omp_auth_seed_mount(harness: str, inst: str) -> list[str]:
    """Seed omp's credentials into a per-instance agent dir so the pod launches authenticated.

    omp (Oh My Pi) keeps credentials in its OWN store — ~/.omp/agent/agent.db, table
    auth_credentials (anthropic OAuth + any API keys) — NOT in ~/.claude. We snapshot the host DB
    into a per-instance state dir (sqlite3 stdlib .backup → WAL-safe), strip the host's
    threads/jobs/usage/cache so no host history bleeds in, and mount that dir rw at ~/.omp/agent.
    Re-seeded on each container creation, so the credentials stay current. Parallel to the Claude
    .credentials.json seeding; the mount supersedes the old per-slug session mount.
    """
    if harness != "omp":
        return []

    host_db = Path.home() / ".omp" / "agent" / "agent.db"
    if not host_db.is_file():
        _err.print(
            "[yellow]note:[/yellow] no omp credential store at ~/.omp/agent/agent.db — "
            "omp will prompt to log in (run `omp` on the host first)."
        )
        return []

    state_root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    inst_agent = state_root / "harnessed" / inst / "omp-agent"
    inst_agent.mkdir(parents=True, exist_ok=True)
    target = inst_agent / "agent.db"

    try:
        src = sqlite3.connect(f"file:{host_db}?mode=ro", uri=True)
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)  # consistent online snapshot (handles the host's WAL)
            existing = {r[0] for r in dst.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for tbl in _OMP_HISTORY_TABLES:
                if tbl in existing:
                    dst.execute(f"DELETE FROM {tbl}")
            dst.commit()
        finally:
            src.close()
            dst.close()
    except sqlite3.Error as exc:
        _err.print(f"[yellow]note:[/yellow] could not seed omp auth ({exc}) — omp may prompt to log in.")
        return []

    return ["-v", f"{inst_agent}:{_CONTAINER_HOME_STR}/.omp/agent:rw"]


# --- Shared-service sidecars (design §3/§9) ------------------------------------
#
# A recipe references a service via `mcp.servers[].service: <name>`; the assembler resolves it to a
# hatago URL-proxy entry at host.containers.internal:<port>. Something must actually RUN that
# container. Services are host-published and outlive any instance, so they are started idempotently
# (skip if already running) and are NOT torn down by `--fresh` (only the pod is).

def _svc_container(name: str) -> str:
    return f"harnessed-svc-{name}"


def _service_refs(stack: str) -> list[str]:
    """Distinct service names referenced by a stack's recipes (via `service:` MCP servers)."""
    _, recipes = load_stack_with_recipes(None, stack)
    names: list[str] = []
    for recipe in recipes:
        for server in recipe.servers:
            if server.service and server.service not in names:
                names.append(server.service)
    return names


def _ensure_service(rt: str, name: str) -> None:
    """Build (if missing) and start (if not running) one host-published service sidecar."""
    svc = load_service(None, name)
    if not _image_exists(rt, svc.image):
        svc_dir = paths.find_in_catalog("services", name)
        _out.print(f"[blue][INFO][/blue] Building service image {svc.image} ...")
        _run([rt, "build", "-t", svc.image, "-f", str(svc_dir / "Dockerfile"), str(svc_dir)])
    cname = _svc_container(name)
    if _container_running(rt, cname):
        return
    # Remove any stopped leftover with the same name before (re)starting.
    subprocess.run([rt, "rm", "-f", cname], capture_output=True)
    _out.print(f"[blue][INFO][/blue] Starting service '{name}' on :{svc.port} ({cname})")
    run_cmd = [rt, "run", "-d", "--name", cname, "-p", f"{svc.port}:{svc.port}"]
    if svc.volume:
        run_cmd += ["-v", f"{svc.volume}:/data"]
    run_cmd.append(svc.image)
    _run(run_cmd, capture_output=True)
    _wait_service(svc.port)


def _wait_service(port: int, timeout: int = 30) -> None:
    """Poll the host-published service port until it accepts a TCP connection."""
    import socket
    import time
    for _ in range(timeout):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)


def _ensure_services(rt: str, stack: str) -> None:
    for name in _service_refs(stack):
        _ensure_service(rt, name)


# --- Typer commands ------------------------------------------------------------

@app.command()
def launch(
    stack: str = typer.Argument(..., help="Stack name (stacks/<name>/stack.yaml)"),
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
    fresh: bool = typer.Option(False, "--fresh", help="Tear down any existing pod/instance first"),
    no_firewall: bool = typer.Option(False, "--no-firewall", help="Skip egress firewall"),
) -> None:
    """Launch an isolated harness stack against a project directory."""
    if no_firewall:
        os.environ["NO_FIREWALL"] = "true"

    rt = _runtime()
    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.is_dir():
        _err.print(f"[bold red]error:[/bold red] project directory does not exist: {project_path}")
        raise typer.Exit(1)

    stack_yaml = _stacks_dir() / stack / "stack.yaml"
    if not stack_yaml.is_file():
        _err.print(f"[bold red]error:[/bold red] unknown stack '{stack}' (no {stack_yaml})")
        raise typer.Exit(1)

    if not is_built(stack):
        _err.print(f"[bold red]error:[/bold red] stack '{stack}' has no assembled profile (run: harnessed build {stack})")
        raise typer.Exit(1)

    try:
        stk = load_stack(_stacks_dir() / stack)
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1)

    harness = stk.harness
    # Prefer the derived per-stack image (recipe Dockerfile layers); fall back to the plain agent.
    derived = _derived_image(stack)
    harness_image = derived if _image_exists(rt, derived) else _agent_image(harness)
    prof = profile_dir(stack)
    relpath = project_relpath(project_path)
    inst = instance_name(stack, project_path)
    pod = inst

    # Ensure harness image exists (lazy-build for non-claude harnesses).
    _ensure_harness_image(rt, harness)
    if not _image_exists(rt, _HATAGO_IMAGE):
        _err.print(f"[bold red]error:[/bold red] hatago image not found — run: harnessed build {stack}")
        raise typer.Exit(1)

    # --fresh: tear down existing pod.
    if fresh:
        _out.print(f"[blue][INFO][/blue] --fresh: tearing down existing pod/instance for {inst}")
        _pod_teardown(rt, inst, pod)

    # Re-attach to running instance (interactive only).
    headless = os.environ.get("HARNESSED_HEADLESS", "false").lower() == "true"
    if not headless and _container_running(rt, inst):
        _out.print(f"[blue][INFO][/blue] Attaching to running instance: {inst}")
        _attach(rt, harness, inst, project_path)
        return

    # Start any shared-service sidecars this stack's recipes reference (host-published; reached from
    # the pod via host.containers.internal:<port>). Idempotent — skips services already running.
    _ensure_services(rt, stack)

    _out.print(f"[blue][INFO][/blue] Creating isolated pod: {pod} (harness + hatago)")
    _out.print(f"[blue][INFO][/blue] Project: {project_path} -> {CONTAINER_HOME / relpath}")

    # Build mount args.
    mount_args = _build_mount_args(harness, prof, project_path, relpath)
    # Seed a token-free ~/.claude.json stub so Claude skips onboarding (auth = the ro credential).
    mount_args += _claude_config_seed_mount(harness, inst)
    # Seed omp's own credential store (~/.omp/agent/agent.db) into a per-instance agent dir.
    mount_args += _omp_auth_seed_mount(harness, inst)

    # Pod network.
    net = os.environ.get("HARNESSED_NET", "")

    # Create pod.
    if _rt_uses_pods(rt):
        pod_cmd = [rt, "pod", "create", "--name", pod, "--userns=keep-id"]
        if net:
            pod_cmd += ["--network", net]
        _run(pod_cmd, capture_output=True)

    hatago_cfg_host = prof / "hatago.config.json"
    hatago_cfg_ctr = str(paths.hatago_config_container())

    # Start hatago member.
    hatago_run = [
        rt, "run", "-d",
        *(["--pod", pod] if _rt_uses_pods(rt) else [f"--network=container:{pod}"]),
        "--name", f"{inst}-hatago",
        "-v", f"{hatago_cfg_host}:{hatago_cfg_ctr}:ro",
        _HATAGO_IMAGE,
        "hatago", "serve", "--http", "--port", str(HATAGO_PORT),
        "--config", hatago_cfg_ctr,
    ]
    _run(hatago_run, capture_output=True)

    # Filter out --userns=keep-id from member (pod-level property).
    member_mounts = [a for a in mount_args if a != "--userns=keep-id"]
    harness_run = [
        rt, "run", "-d",
        *(["--pod", pod] if _rt_uses_pods(rt) else [f"--network=container:{pod}"]),
        "--name", inst,
        *member_mounts,
        harness_image, "sleep", "infinity",
    ]
    _run(harness_run, capture_output=True)

    _apply_firewall(rt, inst)
    _wait_hatago(rt, inst)

    if headless:
        _out.print(f"[green][SUCCESS][/green] Isolated pod running headless: {inst} (hatago: {inst}-hatago)")
        return

    _attach(rt, harness, inst, project_path)


def _attach(rt: str, harness: str, inst: str, project_path: Path) -> None:
    """Exec into the running instance with the harness command (os.execvp for clean TTY)."""
    mise_init = "source ~/.bashrc && mise trust -a 2>/dev/null"
    mcp_cfg = str(paths.container_mcp_config())

    harness_cmd_tpl = _HARNESS_ATTACH_CMD.get(harness, "claude")
    harness_cmd = harness_cmd_tpl.format(mcp_cfg=mcp_cfg, instance=inst)
    shell_cmd = f"{mise_init} && {harness_cmd}"

    exec_argv = [
        rt, "exec", "-it",
        "-e", "TERM=xterm-256color",
        "-w", str(project_path),
        inst,
        "bash", "-l", "-c", shell_cmd,
    ]
    # os.execvp replaces this process — hands the TTY to the container natively.
    os.execvp(rt, exec_argv)


@app.command("build")
def build(
    stack: Optional[str] = typer.Argument(None, help="Stack to assemble; omit to rebuild base images"),
    root: Optional[str] = typer.Option(None, "--root", help="Alternate stacks/recipes root"),
    no_scans: bool = typer.Option(False, "--no-security-scans", help="Skip credentialed scans"),
    force: bool = typer.Option(False, "--force", help="Force rebuild of base images"),
) -> None:
    """Assemble a stack (emit + build hatago), or rebuild base/claude/hatago images."""
    if no_scans:
        os.environ["HARNESSED_NO_SCANS"] = "true"
    rt = _runtime()
    root_path = Path(root).resolve() if root else None
    if stack:
        _build_stack(rt, stack, root_path)
    else:
        _build_images_cmd(rt, force=force)


@app.command("list")
def list_stacks() -> None:
    """List authored stacks and running harnessed instances."""
    rt = _runtime()
    _out.print("[bold]Authored stacks:[/bold]")
    stacks_d = _stacks_dir()
    if stacks_d.is_dir():
        for s in sorted(stacks_d.iterdir()):
            if (s / "stack.yaml").is_file():
                built = "[green]built[/green]" if is_built(s.name) else "[yellow]not built[/yellow]"
                _out.print(f"  {s.name}  ({built})")
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

    if not is_built(stack):
        _out.print(f"[blue][INFO][/blue] Stack '{stack}' not built — assembling first")
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
    harness: str = typer.Option("claude", "--harness", help="Harness (claude|omp|opencode|gemini|antigravity|codex)"),
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
    "launch", "build", "list", "stop", "rm", "clean", "test", "new",
    "install", "uninstall", "rescan", "svc",
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
