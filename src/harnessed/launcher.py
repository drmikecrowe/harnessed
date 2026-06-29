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
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import emit
from . import paths
from . import persist
from .paths import CONTAINER_HOME, instance_name, is_built, profile_dir, project_relpath
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
    # No `--profile`: that isolates auth/sessions/settings into a separate store, which would ignore
    # the bind-mounted ~/.omp/agent. We share the host's default omp profile (auth + usage + sessions).
    "omp": "omp",
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


def _build_base_image(rt: str) -> None:
    """Force-(re)build the parameterised base so edits to Dockerfile.harnessed-base (the supply-chain
    scan script, extra-tools, scanner installs) propagate into every FROM-derived agent / hatago /
    stack image. Layer-cached: a no-op when the base Dockerfile is unchanged."""
    _out.print(f"[blue][INFO][/blue] Building {_BASE_IMAGE} ...")
    _run([rt, "build", "-t", _BASE_IMAGE, "-f", str(_catalog_base("Dockerfile.harnessed-base")),
          str(_harnessed_dir())])


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

    # Always rebuild the parameterised base first: hatago and the agent image below are both `FROM
    # harnessed-base`, so a stale base (e.g. after editing Dockerfile.harnessed-base) would silently
    # propagate into every derived image. Cache-backed — a no-op when the base Dockerfile is unchanged.
    _build_base_image(rt)

    _out.print(f"[blue][INFO][/blue] Building {_HATAGO_IMAGE} for stack '{stack}' ...")
    hdir = _harnessed_dir()
    _run([rt, "build", "-t", _HATAGO_IMAGE, "-f", str(_catalog_base("Dockerfile.hatago")), str(hdir)])

    # (Re)build the agent base image so a changed agent Dockerfile / build_args (e.g. OMP_VERSION)
    # actually propagates — the derived image is `FROM` it. Cache-backed: a no-op when unchanged,
    # but a changed pin cache-busts the version layer and, in turn, the derived image's FROM.
    _build_agent_image(rt, load_stack(stack_dir).harness)

    # Always build the derived per-stack image: its FINAL layer is the supply-chain scan (BLD-02,
    # emit.write_derived_dockerfile), so every stack — not just ones shipping a recipe Dockerfile —
    # gets scanned. The scan runs over the agent's mise globals + recipe installs under ~/.claude.
    derived = _derived_image(stack)
    dockerfile = prof / f"Dockerfile.harnessed-{stack}"
    _out.print(f"[blue][INFO][/blue] Building derived image {derived} (incl. supply-chain scan) ...")
    _build_derived_image(rt, derived, dockerfile, hdir)
    # Merge image-baked ~/.claude extensions into the profile only when a recipe actually baked some.
    if any((r.root / "Dockerfile").is_file() for r in result.recipes):
        _merge_baked_extensions(rt, derived, prof)

    # Replace the assemble-time settings.json FLOOR with the image's installer-written
    # settings.json (merged with harnessed's required grant). UNCONDITIONAL — a settings.json can
    # be baked by the agent BASE image, not only by a recipe Dockerfile, so this must NOT hide
    # behind the recipe-bake gate above.
    _merge_baked_settings(rt, derived, prof)

    # Surface the advisory supply-chain report (baked by the derived image's final scan layer).
    _surface_scan_report(rt, derived, prof)

    _out.print(f"[green][SUCCESS][/green] Stack '{stack}' built — profile: {prof}")


def _build_derived_image(rt: str, derived: str, dockerfile: Path, hdir: Path) -> None:
    """Build the derived image, supplying SNYK_TOKEN to its scan layer as a build SECRET.

    The token is resolved via varlock from ~/.config/harnessed/.env.schema and passed with
    `--secret id=snyk_token,env=SNYK_TOKEN` — never a build-arg, so it is never baked into image
    history. No schema / no varlock → plain build; the scan's `--mount=type=secret,...,required=false`
    yields no token and snyk warn-skips (osv + pip-audit advisory output still runs).
    """
    schema = Path.home() / ".config" / "harnessed" / ".env.schema"
    if schema.is_file() and shutil.which("varlock"):
        _run(["varlock", "run", "-p", str(schema), "--",
              rt, "build", "-t", derived, "-f", str(dockerfile),
              "--secret", "id=snyk_token,env=SNYK_TOKEN", str(hdir)])
    else:
        _run([rt, "build", "-t", derived, "-f", str(dockerfile), str(hdir)])


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

    cid = subprocess.run([rt, "create", image], capture_output=True, text=True).stdout.strip()
    if not cid:
        return
    baked_text: str | None = None
    try:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "settings.json"
            cp = subprocess.run(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.claude/settings.json", str(dest)],
                capture_output=True,
            )
            # cp of a missing file exits non-zero → baked_text stays None (distinct from malformed).
            if cp.returncode == 0 and dest.is_file():
                baked_text = dest.read_text(encoding="utf-8")
    finally:
        subprocess.run([rt, "rm", "-f", cid], capture_output=True)

    def _warn(msg: str) -> None:
        _out.print(f"[yellow]⚠ settings:[/yellow] {msg}")

    baked = emit.read_baked_settings(baked_text, warn=_warn)
    if baked is None:
        return  # nothing usable baked; the floor stub already on disk is correct.
    merged = emit.merge_settings(baked, required, warn=_warn)
    stub.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def _surface_scan_report(rt: str, image: str, prof: Path) -> None:
    """Copy the in-image supply-chain report (harnessed-scan, the derived image's final layer) to the
    profile dir and print a one-line advisory summary. The scan is advisory — this surfaces its posture
    host-side so the user sees it without digging into the image or scrolling the build log."""
    cid = subprocess.run([rt, "create", image], capture_output=True, text=True).stdout.strip()
    if not cid:
        return
    dest = prof / "scan-report.json"
    try:
        subprocess.run(
            [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json", str(dest)],
            capture_output=True,
        )
    finally:
        subprocess.run([rt, "rm", "-f", cid], capture_output=True)
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
        for name in (instance, f"{instance}-hatago"):
            subprocess.run([rt, "rm", "-f", name], capture_output=True)


def _attach_marker(inst: str) -> Path:
    """Host-side marker whose mtime records when `inst` was last interactively attached."""
    return paths.xdg_state_home() / "harnessed" / "attached" / inst


def _touch_attach_marker(inst: str) -> None:
    m = _attach_marker(inst)
    m.parent.mkdir(parents=True, exist_ok=True)
    m.touch()


def _session_active(rt: str, inst: str) -> bool:
    """True while an interactive harness session is attached.

    An idle instance runs only its PID-1 `sleep infinity`; an attached one also carries the
    `bash -l -c … <harness>` exec tree. Any process other than `sleep` counts as activity.
    """
    result = subprocess.run([rt, "top", inst, "comm"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    # Drop the header row `top` prints; treat any surviving non-`sleep` process as a live session.
    procs = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return any(c != "sleep" for c in procs)


def _apply_firewall(rt: str, instance: str) -> None:
    if os.environ.get("NO_FIREWALL", "false").lower() == "true":
        return
    # egress-firewall.sh is mounted at /usr/local/sbin/egress-firewall by _build_mount_args.
    subprocess.run([
        rt, "exec", instance, "bash", "/usr/local/sbin/egress-firewall",
    ], capture_output=True)


def _wait_hatago(rt: str, instance: str, port: int | None = None, timeout: int = 30) -> None:
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


def _persist_mounts(stack: str, project_path: Path) -> list[str]:
    """Bind-mount each recipe's declared persist folders (rw) so their state survives `--fresh`.

    Project scope (T4a): each entry names a `$HOME`-relative folder the tool writes to inside the
    container (e.g. `.context-mode`); harnessed maps it to persist/<recipe>/<project-hash>/<name>/
    on the host, created here. Ownership is correct by construction (the invoking user creates it).

    Global scope (T4b): an entry names a REAL host dir (e.g. `~/.gbrain`) shared with host-native
    runs. It mounts PATH-PRESERVING (host <realpath> → container <same realpath>) so the tool finds
    its data where it expects — but ONLY after `persist.resolve_global_persist` clears it: a
    hard-denied sensitive dir (`~/.ssh` etc.) or any path absent from the user-owned allowlist
    fails loudly here and the pod is never created.

    Ownership (T5): every target dir is ownership-guarded — a pre-existing dir owned by another uid
    would silently EACCES under `--userns=keep-id`, so it is rejected with a remediation.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    args: list[str] = []
    for recipe in recipes:
        spec = recipe.persist
        for name in spec.project:
            host_dir = paths.persist_project_dir(recipe.name, project_path, name)
            persist.guard_ownership(host_dir)
            host_dir.mkdir(parents=True, exist_ok=True)
            ctr_dir = f"{_CONTAINER_HOME_STR}/{name}"
            args += ["-v", f"{host_dir}:{ctr_dir}:rw"]
        for entry in spec.global_dirs:
            host_dir = persist.resolve_global_persist(entry)
            persist.guard_ownership(host_dir)
            args += ["-v", f"{host_dir}:{host_dir}:rw"]
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
    rm: bool = typer.Option(False, "--rm", help="Ephemeral: tear the pod down when the interactive session exits"),
    no_firewall: bool = typer.Option(False, "--no-firewall", help="Skip egress firewall"),
    agent_start_folder: Optional[str] = typer.Option(
        None, "--agent-start-folder",
        help="Start the agent in this subfolder of the project (root is still mounted in full)",
    ),
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
    start_dir = _resolve_start_dir(project_path, agent_start_folder)

    # Ensure harness image exists (lazy-build for non-claude harnesses).
    _ensure_harness_image(rt, harness)
    if not _image_exists(rt, _HATAGO_IMAGE):
        _err.print(f"[bold red]error:[/bold red] hatago image not found — run: harnessed build {stack}")
        raise typer.Exit(1)

    # --fresh: tear down existing pod.
    if fresh:
        _out.print(f"[blue][INFO][/blue] --fresh: tearing down existing pod/instance for {inst}")
        _pod_teardown(rt, inst, pod)

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
                _attach(rt, harness, inst, project_path, ephemeral=rm, pod=pod, start_dir=start_dir)
                return
        else:
            _out.print(f"[blue][INFO][/blue] Attaching to running instance: {inst}")
            _attach(rt, harness, inst, project_path, ephemeral=rm, pod=pod, start_dir=start_dir)
            return
    # Stopped leftover: a previous non-ephemeral session exited without tearing down its pod (only
    # --rm cleans up). A same-name `pod create` would fail "name already in use", so remove the
    # stopped instance and recreate. A running instance is re-attached via the guard above.
    if _stopped_leftover(rt, inst, pod):
        _out.print(f"[blue][INFO][/blue] Recreating stopped instance '{inst}' from a prior session …")
        _pod_teardown(rt, inst, pod)

    # Start any shared-service sidecars this stack's recipes reference (host-published; reached from
    # the pod via host.containers.internal:<port>). Idempotent — skips services already running.
    _ensure_services(rt, stack)

    _out.print(f"[blue][INFO][/blue] Creating isolated pod: {pod} (harness + hatago)")
    _out.print(f"[blue][INFO][/blue] Project: {project_path} -> {CONTAINER_HOME / relpath}")
    if start_dir != project_path:
        _out.print(f"[blue][INFO][/blue] Agent start folder: {start_dir}")

    # Build mount args.
    mount_args = _build_mount_args(harness, prof, project_path, relpath)
    # Seed a token-free ~/.claude.json stub so Claude skips onboarding (auth = the ro credential).
    mount_args += _claude_config_seed_mount(harness, inst)
    # Share omp's state with the host (auth + usage + sessions) via a bind mount of ~/.omp/agent.
    mount_args += _omp_agent_mount(harness)
    # Persist recipe-declared project-scoped folders (rw) so their state survives --fresh.
    mount_args += _persist_mounts(stack, project_path)

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
        "hatago", "serve", "--http", "--port", str(paths.hatago_port()),
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
        if rm:
            _out.print("[yellow]note:[/yellow] --rm has no effect in headless mode (no interactive session to exit)")
        _out.print(f"[green][SUCCESS][/green] Isolated pod running headless: {inst} (hatago: {inst}-hatago)")
        return

    _attach(rt, harness, inst, project_path, ephemeral=rm, pod=pod, start_dir=start_dir)


def _attach(
    rt: str,
    harness: str,
    inst: str,
    project_path: Path,
    *,
    ephemeral: bool = False,
    pod: Optional[str] = None,
    start_dir: Optional[Path] = None,
) -> None:
    """Exec into the running instance with the harness command.

    Default: os.execvp hands the TTY to the container natively (clean attach, no post-exit hook).
    ephemeral (--rm): run the exec as a child so the pod can be torn down when the session exits.
    start_dir: working directory for the agent (defaults to project_path; --agent-start-folder).
    """
    mise_init = "source ~/.bashrc && mise trust -a 2>/dev/null"
    mcp_cfg = str(paths.container_mcp_config())

    harness_cmd_tpl = _HARNESS_ATTACH_CMD.get(harness, "claude")
    harness_cmd = harness_cmd_tpl.format(mcp_cfg=mcp_cfg, instance=inst)
    shell_cmd = f"{mise_init} && {harness_cmd}"

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


@app.command("prune")
def prune(
    idle: int = typer.Option(120, "--idle", help="Prune instances detached at least this many minutes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be pruned without tearing down"),
) -> None:
    """Tear down instances whose interactive session exited and stayed idle.

    An instance is prunable when no session is attached (only its PID-1 `sleep infinity` runs)
    and its last attach was at least --idle minutes ago. Instances never interactively attached
    (headless / externally driven) and shared services are left untouched.
    """
    import time

    rt = _runtime()
    result = subprocess.run(
        [rt, "ps", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    members = [
        n.strip() for n in result.stdout.splitlines()
        if n.strip() and not n.strip().endswith("-hatago")
    ]

    pruned = 0
    for inst in members:
        marker = _attach_marker(inst)
        if not marker.exists():
            continue  # never interactively attached — leave it alone
        if _session_active(rt, inst):
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
    "launch", "build", "list", "stop", "rm", "prune", "clean", "test", "new",
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
