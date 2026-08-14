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
from itertools import cycle
from pathlib import Path
from typing import Callable, Optional, TypeVar

import typer
from rich.markup import escape

from . import aoe
from . import dynstack
from . import emit
from . import lastrun
from . import paths
from . import persist
from . import staleness
from . import capmatrix
from .backend import (
    ATTACH,
    BOUNDARY,
    EGRESS,
    FIRST_START,
    ISOLATION_CONTAINER,
    ISOLATION_NONE,
    ExecutionBackend,
    IsolationPhase,
    LaunchSpec,
    ProvisionPhase,
    register,
)
from .console import _err, _out
from .ctrquery import (
    _container_running,
    _container_stale,
    _image_exists,
    _img_differs,
    _rt_uses_pods,
    _runtime,
    _stopped_leftover,
)
from .hosthome import (
    _DAEMON_STATE_MARKERS,
    _HOST_STACK_FINGERPRINT,
    _LEGACY_PROJECT_DIR_RE,
    _OAUTH_TOKEN_VAR,
    _host_home_lock,
    _host_stack_fingerprint,
    _materialize_host_home,
    _migrate_legacy_host_homes,
    _propagate_host_settings,
    _rescue_host_credentials,
    _scrub_host_home,
    _share_host_claude_state,
    _stamp_host_home,
)
from .attachcmd import (
    _HARNESS_ATTACH_CMD,
    _omp_attach_cmd,
    _opencode_attach_cmd,
    _resolve_mount_path,
    _resolve_start_dir,
)
from .catalogseed import (
    _ensure_docs_wiki_clone,
    _ensure_extra_tools,
    _ensure_local_catalog_links,
    _seed_user_default_recipe,
    _update_recipe_dirs,
    _update_agent_dirs,
)
from .jsonmerge import _merge_host_claude_settings
from .layout import (
    _agent_image,
    _derived_image,
    _ensure_profile_dir,
    _harnessed_dir,
    _stacks_dir,
)
from .mounts import (
    AWS_SSO_ECS_PORT,
    _aws_sso_ecs_forward_args,
    _aws_sso_server_reachable,
    _build_mount_args,
    _ccstatusline_settings_mount,
    _claude_config_seed_mount,
    _claude_creds_expired,
    _claude_creds_seed_mount,
    _claude_isolated_auth_mount,
    _env_files_value,
    _isolated_auth_fresh_wipe,
    _claude_oauth_token_args,
    _claude_oauth_token_configured,
    _credential_forward_args,
    _keyring_fresh_wipe,
    _keyring_init,
    _keyring_state_mount,
    _MCP_REMOTE_SPEC,
    _mcp_auth_store_dir,
    _mcp_auth_store_mount,
    _mcp_remote_argv,
    _mcp_remote_pending_auth,
    _mcp_remote_pod_args,
    _mcp_remote_token_file,
    _omp_agent_mount,
    _omp_mcp_seed_mount,
    _persist_mounts,
)
from .proc import _BUILD_TAG, _TIMEOUT_RC, _bounded, _run, _say
from .setupenv import (
    _CTR_SETUP_DIR,
    _confirm_setup,
    _container_setup_env,
    _gcd_db_name,
    _init_shell_prologue,
    _pending_setup_scripts,
    _recipe_env,
    _repo_primitives,
    _script_env,
    _setup_script_mounts,
    _stack_tools_dirs,
    _subst,
    _write_project_tool_env,
    harnessed_env,
    project_env_path as setupenv_project_env_path,
)
from .svcguards import (
    _abort_dead_service,
    _assert_data_dir_unlocked,
    _assert_placement_unchanged,
    _assert_service_running,
    _service_container_status,
)
from .hostrun import (
    _apply_host_mise_env,
    _host_install_tools,
    _host_mise_env,
    _host_native_mcp,
    _host_run_inits,
    _host_run_installs,
    _host_run_setups,
    _host_tool_shims_dir,
)
from .volumes import (
    _VOL_HARNESS_LABEL,
    _VOL_LABEL,
    _VOL_STACK_LABEL,
    _ensure_config_volume,
    _ensure_stack_volumes,
    _run_container_installs,
    _stack_config_volume,
    _volume_read,
)
from .svcstate import (
    _STABLE_PORT_RANGE,
    _SVC_CONFIG_HASH_LABEL,
    _SVC_STACK_LABEL,
    _repo_project_hashes,
    _service_data_dir,
    _service_refs,
    _svc_config_hash,
    _svc_container,
    _svc_container_stack,
    _svc_drift_reason,
    _svc_password,
    _svc_project_key,
    _svc_published_port,
    _svc_stable_port,
    _svc_stacks_from_instances,
    svc_client_env,
    svc_socket_env,
)
from .credmounts import (
    _gh_hosts_missing_plaintext_token,
    _git_identity_config_mount,
    _gpg_ssh_socket,
    _macos_op_socket_mount_source,
    _op_agent_socket,
    _ssh_agent_args,
    _ssh_agent_auto_forward_args,
    _ssh_dir_mounts,
    _stack_from_overlay,
    _trusted_ssh_keys,
    _yubikey_device_args,
)
from .launchenv import (
    _resolve_launch_env,
    _resolve_launch_secrets,
    _strip_var_from_env_files,
    _varlock_cache_clear,
    _varlock_resolve,
)
from .paths import CONTAINER_HOME, instance_name, is_built, profile_dir, project_relpath
from .assemble import (
    assemble,
    compute_recipe_hash,
    validate_agent_image,
    _merge_servers,
    _resolve_service_servers,
    _validate_direct_servers,
)
from .synclinks import CollisionError
from .schema import (
    HARNESS_CONFIG_DIR,
    HUB_TRANSPORT_STDIO,
    PinValidationError,
    Recipe,
    SchemaError,
    ServiceDef,
    Stack,
    load_agent,
    load_service,
    load_stack,
    load_stack_with_recipes,
    normalize_extra_tools,
    parse_extra_tools,
)

app = typer.Typer(
    name="harnessed",
    help="Launch composable harness stacks (claude/omp/opencode/antigravity/codex + hatago MCP hub).",
    add_completion=False,
)

# Re-exports: this module is a facade left behind by the module split.  The test suite binds to
# these names by attribute (e.g. `launcher._img_differs(...)`, `monkeypatch.setattr(launcher, ...)`).
# Deleting any of these imports breaks tests — exactly as documented in issue #327 / PR #325.
# F401 is suppressed via __all__ rather than per-line noqa to keep the contract explicit.
__all__ = [
    "_DAEMON_STATE_MARKERS",       # hosthome
    "_HOST_STACK_FINGERPRINT",     # hosthome
    "_STABLE_PORT_RANGE",          # svcstate
    "_claude_creds_expired",       # mounts
    "_ensure_config_volume",       # volumes
    "_env_files_value",            # mounts
    "_gcd_db_name",                # setupenv
    "_gh_hosts_missing_plaintext_token",  # credmounts
    "_host_mise_env",              # hostrun
    "_img_differs",                # ctrquery
    "_macos_op_socket_mount_source",  # credmounts
    "_migrate_legacy_host_homes",  # hosthome
    "_op_agent_socket",            # credmounts
    "_repo_primitives",            # setupenv
    "_repo_project_hashes",        # svcstate
    "_run_container_installs",     # volumes
    "_script_env",                 # setupenv
    "_stack_config_volume",        # volumes
    "_subst",                      # setupenv
    "_varlock_cache_clear",        # launchenv
    "_varlock_resolve",            # launchenv
    "_yubikey_device_args",        # credmounts
    "app",
    "svc_client_env",              # svcstate
    "svc_socket_env",              # svcstate
]

# --- shared image names (base; agent images come from catalog/agents/<h>/agent.yaml) ---
# hatago is no longer a separate image — it is baked into harnessed-base and runs in-container
# (hatago-consolidation), so there is no _HATAGO_IMAGE.
_BASE_IMAGE = "harnessed-base:latest"
_CLAUDE_IMAGE = "harnessed-claude:latest"
_CONTAINER_HOME_STR = str(CONTAINER_HOME)

# --- podman deadlines (bd harnessed-1ao) ------------------------------------------------------
#
# An unresponsive podman — a network partition mid-pull, a runc deadlock, a wedged image store —
# blocks an unbounded subprocess.run forever, and only the user or the OS ends it. So every call
# below goes through `_bounded`, which turns "hung" into "failed" rather than into "hangs".
#
# The numbers are generous on purpose: they are not performance budgets, they are the point past
# which podman is not slow but STUCK. Sized by what the command does, since a `rm -f` racing a
# shutting-down container is legitimately slower than an `inspect`. The suite runs no real podman
# (see CLAUDE.md), so nothing here proves these are right under load — only that the mechanism
# fires. Raise one if a real workload trips it; that is a tuning bug, not a design failure.
_PODMAN_QUERY_TIMEOUT = 30      # read-only metadata: inspect, ps, images, volume ls, top, exists
_PODMAN_WRITE_TIMEOUT = 120     # state changes: create, rm -f, stop, pod rm, volume rm, cp
_PODMAN_EXEC_TIMEOUT = 120      # exec of a bounded in-container command (firewall, CA install)
_PODMAN_PROBE_TIMEOUT = 10      # an exec'd readiness probe inside a poll loop
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
            # Normalise BEFORE validating, and stage the SAME normalised text. Validating one
            # string and shipping a different one is how a guard blesses a file the build then
            # chokes on — a CRLF entry reaches awk as `bat@0.26.1\r`, and a BOM rides on the first
            # spec. See schema.normalize_extra_tools.
            # `encoding="utf-8"` on BOTH sides, never the locale default. The BOM defence in
            # `normalize_extra_tools` strips U+FEFF, which only exists if the bytes decoded as
            # UTF-8; under a non-UTF-8 locale the same bytes arrive as "ï»¿", survive the strip, and
            # the file is then refused with a message about control characters that names the wrong
            # problem. The write is the mirror: the staged bytes must be the bytes the build reads,
            # and the build reads UTF-8. `update.discover_extra_tools_pins` already pinned its
            # encoding, so leaving these unpinned also made two readers of one format disagree.
            content = normalize_extra_tools(user_file.read_text(encoding="utf-8"))
            # Validate on the HOST, before podman is ever invoked. An unpinned entry used to
            # surface as `exit status 123` from inside a RUN layer (xargs' "a child exited 1-125"),
            # which names neither the tool nor the file — see bd harnessed-2o9. Raising here names
            # the USER's file, which is the one they must edit: the shipped default is marked
            # "TEMPLATE — do not edit for personal use", so pointing at it would send them wrong.
            #
            # The message has to carry the REMEDY, not just the complaint. Every user who built
            # before this change has a copy of the old unpinned template sitting at this path
            # (it is seeded once, then never touched again), so this fires on the first build
            # after upgrading — for people who did nothing wrong. An error that only says "not
            # pinned" turns that into a support question.
            try:
                parse_extra_tools(content)
            except PinValidationError as exc:
                raise PinValidationError(
                    f"{user_file}: {exc}\n"
                    f"If you have not customised that file, delete it and rebuild — it is "
                    f"re-seeded from the shipped template, which is pinned. Otherwise add an "
                    f"explicit version to each entry."
                ) from exc
            (ctx_path / "catalog" / "base" / "extra-tools.txt").write_text(
                content, encoding="utf-8"
            )
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
        _bounded(cmd, timeout=_PODMAN_EXEC_TIMEOUT, capture_output=True)
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

    # The claude image is an AGENT image, so its pins live in agent.yaml — the Dockerfile's ARG
    # carries no default and its guard refuses an empty CLAUDE_VERSION. This path builds the same
    # Dockerfile as `_build_agent_image`, so it owes the same `--build-arg` flags; omitting them
    # made `harnessed build` (no stack) fail the guard while the per-stack path went green.
    claude_args = _agent_build_arg_flags(load_agent("claude"))
    # AC-9: this path builds an AGENT image without going anywhere near `assemble()`, so the gate
    # wired in there does not cover it. Bare `harnessed build` reaches exactly here. A gate with a
    # documented way around it is a gate that will be walked around, usually by accident.
    validate_agent_image("claude")

    with _staged_build_context() as ctx:
        base = Path(ctx) / "catalog" / "base"
        pairs = [
            (_BASE_IMAGE, base / "Dockerfile.harnessed-base", []),
            (_CLAUDE_IMAGE, base / "Dockerfile.harnessed-claude", claude_args),
        ]
        for image, dockerfile, build_args in pairs:
            if force or not _image_exists(rt, image):
                _out.print(f"[blue][INFO][/blue] Building {image} ...")
                _run([rt, "build", "-t", image, "-f", str(dockerfile), *build_args, *cache_arg, *secret_args, ctx])
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


def _agent_build_arg_flags(agent) -> list[str]:
    """The `--build-arg` flags for an agent image — the boundary the manifest's shapes collapse at.

    Two properties this owes, both invisible from the schema alone (A7):
      * a mapping-form pin contributes its VALUE. `schema.load_agent` already flattened it, so this
        loop sees plain strings — but the f-string below would happily stringify a dict instead of
        raising, shipping `--build-arg NAME={'value': '1.2.3'}` on a build that goes green.
      * an `unpinnable:` entry contributes NOTHING. It names an ARG the Dockerfile does not declare
        (that is what makes it unpinnable), so passing it would be an error at best and a silent
        no-op at worst. It is absent from `build_args` by construction, which is the cheapest way
        to be right — but the test asserts the absence rather than trusting the construction.
    """
    flags: list[str] = []
    for key, val in agent.build_args.items():
        flags += ["--build-arg", f"{key}={val}"]
    return flags


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
    # AC-9, same reason as in `_build_images_cmd`: this is a build site, not an assembly, and the
    # lazy per-harness path arrives here without assembling anything. Validating at the two places
    # that actually BUILD an agent image is what makes the rule unconditional — `assemble()` keeps
    # its own call so a stack is refused before any file is emitted, rather than at build time.
    validate_agent_image(harness)

    def build() -> None:
        if not _image_exists(rt, _BASE_IMAGE):
            _say("[yellow][WARNING][/yellow] harnessed-base not found. Building base first…")
            _build_images_cmd(rt, force=False)
        build_args = _agent_build_arg_flags(agent)
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
        raise typer.Exit(1) from exc

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
        paths.USERNS_ARG,
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
    result = _bounded(
        [
            rt, "inspect", "--format",
            '{{if .Config.Labels}}{{index .Config.Labels "harnessed.recipe-hash"}}{{end}}',
            _derived_image(stack, harness),
        ],
        timeout=_PODMAN_QUERY_TIMEOUT,
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
        raise typer.Exit(1) from exc


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

    result = _bounded(
        [rt, "images", "--filter", "label=harnessed=true", "--format", "{{.Repository}}"],
        timeout=_PODMAN_QUERY_TIMEOUT,
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
    else:
        # Cannot use `_listing` here: unlike the CLI listings, this one is ADDITIVE — declared pairs
        # are still worth reconciling, so aborting would be an overreaction. But saying nothing is
        # the same lie in a quieter voice: previously-built-but-no-longer-declared stacks are
        # silently dropped from the sweep, and the caller goes on to print
        # "[SUCCESS] All stacks up to date" over a reconciliation that never looked at them.
        _err.print(
            f"[bold red]warning:[/bold red] could not list built images (runtime exited "
            f"{result.returncode}) — reconciling only the {len(pairs)} DECLARED stack(s). A stale "
            "image that is no longer declared will not be found on this run."
        )
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


_T = TypeVar("_T")


def _with_image_container(rt: str, image: str, fn: Callable[[str], _T]) -> _T | None:
    """Create ONE throwaway container from `image`, run `fn(cid)` (the `cp` extractions), and
    always `rm -f` it in a `finally`. Returns `fn`'s result, or None when the create produced no
    container id (defensive — mirrors the old per-site `if not cid: return`).

    Unifies the three post-build passes (extensions / settings / scan-report) onto a single
    create/rm instead of one apiece — same podman commands, one container.
    """
    cid = _bounded(
        [rt, "create", image], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True, text=True
    ).stdout.strip()
    if not cid:
        return None
    try:
        return fn(cid)
    finally:
        # `_bounded` cannot raise, which is load-bearing here: a TimeoutExpired thrown from this
        # `finally` would replace whatever `fn` raised with a complaint about the cleanup.
        _bounded([rt, "rm", "-f", cid], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)


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
            cp = _bounded(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.claude/settings.json", str(dest)],
                timeout=_PODMAN_WRITE_TIMEOUT,
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
            cp = _bounded(
                [rt, "cp",
                 f"{cid}:{_CONTAINER_HOME_STR}/.config/opencode/opencode.json", str(dest)],
                timeout=_PODMAN_WRITE_TIMEOUT,
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
        _bounded(
            [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json", str(dest)],
            timeout=_PODMAN_WRITE_TIMEOUT,
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

def _without_userns(args: list[str]) -> list[str]:
    """Drop every `--userns=…` from an argv fragment.

    `--userns` is a POD-level property; podman rejects it on a member, so the mount args the pod was
    created with cannot be handed to the member verbatim. This used to be an inline
    inequality against the bare `keep-id` spelling, which silently stopped matching once it was pinned
    (bd harnessed-rv2.1) — a filter keyed to a literal is a filter that breaks when the literal
    moves. Matching the FLAG covers every spelling of the value.
    """
    return [a for a in args if not a.startswith("--userns")]


def _pod_teardown(rt: str, instance: str, pod: str) -> None:
    if _rt_uses_pods(rt):
        _bounded([rt, "pod", "rm", "-f", pod], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
    else:
        # Single flat container now — hatago runs in-container (hatago-consolidation), not a
        # separate `{instance}-hatago` member.
        _bounded([rt, "rm", "-f", instance], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)


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
    result = _bounded(
        [rt, "top", inst, "tty"], timeout=_PODMAN_QUERY_TIMEOUT, capture_output=True, text=True
    )
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
    res = _bounded([
        rt, "exec", instance, "bash", "/usr/local/sbin/egress-firewall",
        *(domains or []),
    ], timeout=_PODMAN_EXEC_TIMEOUT, capture_output=True)
    # FAIL CLOSED. The script installs a default-DROP policy, so "it did not run" is not a degraded
    # firewall — it is NO firewall, and the container gets unrestricted egress for the whole session.
    # This return value used to be discarded, which was survivable only because an unbounded hang
    # stopped the launch by never finishing; bd harnessed-1ao's deadline removed that accident and
    # would have turned a wedged runtime into a silently unconfined agent. Refusing to continue is
    # the only answer that keeps the isolation harnessed advertises, and NO_FIREWALL=true above is
    # the supported way to say "I do not want one" — so nobody is stuck, they are just asked to
    # say so out loud.
    if res.returncode != 0:
        detail = (res.stderr or b"").decode(errors="replace").strip()
        _err.print(
            f"[bold red]error:[/bold red] could not apply the egress firewall in {instance} "
            f"(exit {res.returncode}) — refusing to continue, because the container would run with "
            "UNRESTRICTED network access. Set NO_FIREWALL=true to launch without one deliberately."
        )
        if detail:
            _err.print(f"[dim]{escape(detail)}[/dim]")
        raise typer.Exit(1)


def _token_is_complete(token: Path) -> bool:
    """True only when the token file holds parseable, non-empty JSON.

    The completion test for a consent. Existence is not enough: mcp-remote writes with a plain
    `writeFile` (no atomic rename anywhere in the pinned dist), so the file appears at its final
    path empty and fills in after. Anything unreadable, unparseable, or empty means "still writing"
    — or a previous run that died mid-write — and both are correctly "not authorized yet".
    """
    try:
        parsed = json.loads(token.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(parsed, dict) and bool(parsed)


def _run_mcp_remote_consent(
    rt: str, instance: str, name: str, argv: list[str], token: Path, timeout: int = 300
) -> bool:
    """Run one mcp-remote consent INTERACTIVELY, attached to the operator's terminal.

    This exists because the authorize URL is otherwise unreachable. In normal operation mcp-remote
    is hatago's stdio child — a GRANDCHILD of the harness — and it prints
    `Please authorize this client by visiting: <url>` to a stderr the harness discards. The operator
    sees only `MCP error -32001: Request timed out` three retries later, with nothing naming a
    missing consent. Running the same argv here, before the harness starts, puts that URL on the
    terminal a human is already looking at.

    IN THE CONTAINER, not on the host: the pod already publishes the callback port and bind-mounts
    the token store, so the redirect resolves and the token lands where the harness will look. Doing
    it host-side would need node on the host — a dependency this CLI deliberately does not have.

    Returns True once the token file appears. mcp-remote does not exit on success (it becomes the
    proxy), so the token file IS the completion signal, and the process is torn down once it lands.
    """
    import time

    _out.print(
        f"\n[bold]{name}[/bold] needs a one-time browser authorization.\n"
        f"Open the URL below, approve it, and this will continue on its own.\n"
        f"[dim]The token is stored on the host and reused by every later launch "
        f"(re-run with --reauth to replace it).[/dim]\n"
    )
    # unbounded: this is the interactive consent itself — it must stay attached to the operator's
    # terminal for as long as they need to finish a browser flow, so a timeout on the CALL would be
    # a timeout on a human. The wait below is deadline-driven instead, and the `finally` terminates
    # this process on every exit path, so nothing here can outlive the launch.
    proc = subprocess.Popen([rt, "exec", "-it", instance, *argv])
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            # PARSED, not merely present. mcp-remote persists with a plain `writeFile` and no
            # atomic rename (verified in the pinned dist: zero `rename(` calls), so the path exists
            # from the moment the file is OPENED and fills in afterwards. Treating existence as
            # success would not just risk reading a truncated token — the teardown below would then
            # terminate mcp-remote mid-write and leave a corrupt one on disk permanently. Requiring
            # parseable, non-empty JSON closes both.
            if _token_is_complete(token):
                _out.print(f"\n[green][SUCCESS][/green] {name} authorized.")
                return True
            if proc.poll() is not None:
                # Exited without writing a token: a declined consent, a bad URL, or a crash. The
                # child's own output is already on the terminal, so add no guesses on top of it.
                _err.print(f"[yellow]note:[/yellow] {name} authorization did not complete.")
                return False
            time.sleep(1)
        _err.print(f"[yellow]note:[/yellow] {name} authorization timed out after {timeout}s.")
        return False
    except KeyboardInterrupt:
        # Ctrl-C aborts THIS consent, not the launch. A stack whose other servers are fine should
        # still come up; the harness will simply be short one server, which is the state the
        # operator just chose.
        _err.print(f"\n[yellow]note:[/yellow] {name} authorization cancelled.")
        return False
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _authorize_mcp_remote_servers(
    rt: str, inst: str, servers: list, stk, *, headless: bool, reauth: bool
) -> None:
    """Prompt for any OAuth MCP server that has no token yet, before the harness starts.

    Ordering is the point: run this AFTER the pod is up (the callback port and the store mount both
    come from it) and BEFORE the harness attaches (so hatago's first connection attempt finds a
    token instead of opening a browser nobody can see).
    """
    store = _mcp_auth_store_dir(inst, stk.isolated_auth)
    pending = _mcp_remote_pending_auth(servers, inst, stk.isolated_auth)
    if reauth:
        # --reauth asks for EVERY mcp-remote server, not only the unauthorized ones: the reason to
        # pass it is that an existing token is wrong (revoked, wrong account, too few scopes), and
        # those are exactly the tokens `_mcp_remote_pending_auth` reports as fine.
        pending = [
            (s.name, _mcp_remote_argv(s))
            for s in servers
            if getattr(s, "is_stdio_child", False)
            and any(_MCP_REMOTE_SPEC.match(a) for a in s.args)
        ]
    if not pending:
        return
    if headless:
        # A blocking browser prompt in CI would hang until the job timeout and report nothing
        # useful. Naming the servers and the flag turns that into an actionable failure.
        names = ", ".join(n for n, _ in pending)
        # Does NOT offer --reauth as a way out: passing it here fails in exactly the same way, and
        # an error that suggests a flag which cannot work sends the reader in a circle. The only
        # remedy is an interactive launch, so that is the only thing named.
        _err.print(
            f"[bold red]error:[/bold red] {names} require a browser authorization that headless "
            f"mode cannot perform. Launch this stack interactively once to store the token; "
            f"headless launches then reuse it."
        )
        raise typer.Exit(1)
    # CONTENTION, and it exists only on the http path. There the entrypoint started the hub with the
    # container, so hatago has ALREADY spawned its own mcp-remote for this server — holding the
    # lockfile and bound to the very callback port the interactive run needs. A second one cannot
    # bind, so the consent would never appear. Stop the hub for the duration and start it again
    # after, by which point the token exists and its first connection attempt succeeds instead of
    # burning three retries. Under stdio there is no hub yet (the harness spawns it at attach), so
    # there is nothing to stop and nothing to restart.
    restart_hub = stk.hub_transport != HUB_TRANSPORT_STDIO
    if restart_hub:
        # `[h]atago` deliberately. `pkill -f` matches against full command lines, INCLUDING the
        # `bash -lc "pkill -f …"` this runs as — so the plain spelling makes the shell match itself
        # and die before it can signal the hub. Not hypothetical: it happened while developing this,
        # and the only symptom was an exec exiting 143 with the hub still running. The bracket makes
        # the pattern match the hub's command line and not its own.
        _bounded(
            [rt, "exec", inst, "bash", "-lc", "pkill -f '[h]atago-mcp-hub' || true"],
            timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True,
        )
    try:
        for name, argv in pending:
            token = _mcp_remote_token_file(store, argv)
            if token is None:
                continue
            _run_mcp_remote_consent(rt, inst, name, argv, token)
    finally:
        # `finally`: a cancelled or failed consent must not leave the stack hubless. Restarting a
        # hub that will still fail to reach one server is strictly better than handing the operator
        # an instance with no MCP at all.
        if restart_hub:
            # The hub command only, NOT `harnessed-start` — that entrypoint ends in
            # `exec sleep infinity`, so re-running it would fork a second PID-1 stand-in. This
            # mirrors the entrypoint's own line and `test_the_hub_restart_matches_the_entrypoint`
            # holds the two together, since a drift here would restart a differently-configured hub.
            _bounded(
                [rt, "exec", "-d", inst, "bash", "-lc",
                 f"nohup hatago serve --http --port {paths.hatago_port()} "
                 f"--config {paths.hatago_config_container()} >/tmp/hatago.log 2>&1 &"],
                timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True,
            )


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
    # Deadline-driven, not `for _ in range(timeout)`. The in-container `timeout 1` bounds the SHELL,
    # not the `podman exec` wrapping it, so a wedged podman used to park here forever. Giving the
    # probe its own deadline fixes that but makes the count-based loop lie — N iterations of
    # (probe + sleep) is up to N*(probe+1) seconds, while the message below still says N. So the
    # loop, the probe and the sleep all measure against one deadline, and the promise stays true.
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = _bounded(
            [rt, "exec", instance, "bash", "-lc",
             f"timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/{port}' 2>/dev/null"],
            timeout=min(_PODMAN_PROBE_TIMEOUT, remaining),
            capture_output=True,
            warn=False,  # one line per second would bury the single actionable error below
        )
        if result.returncode == 0:
            return True
        time.sleep(min(1, max(0.0, deadline - time.monotonic())))
    _err.print(
        f"[bold red]error:[/bold red] hatago hub never came up on :{port} after {timeout}s — "
        f"MCP tools will be unavailable. Inspect the hub log: {rt} exec {instance} cat /tmp/hatago.log"
    )
    return False


# --- Shared-service sidecars (design §3/§9) ------------------------------------
#
# A recipe references a service via `mcp.servers[].service: <name>`; the assembler resolves it to a
# hatago URL-proxy entry at host.containers.internal:<port>. Something must actually RUN that
# container. Services are host-published and outlive any instance, so they are started idempotently
# (skip if already running) and are NOT torn down by `--fresh` (only the pod is).

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


# One list, used to validate the action AND to spell the choices in the error — so a new action can
# never be accepted by the dispatch while the error still calls it unknown.
_SVC_ACTIONS = ("up", "down", "recreate", "sync")


def _svc_run_cmd(
    rt: str,
    svc: "ServiceDef",
    cname: str,
    stack: str,
    project_path: Path | None,
    mount_path: Path | None,
    *,
    stable_port: int = 0,
    password: str = "",
) -> list[str]:
    """The exact `<rt> run` argv for this sidecar, minus the labels.

    PURE — it reads the filesystem but writes nothing. That matters because it is called twice: once
    on the create path, and once on the CHECK path against an ALREADY-RUNNING container, to work out
    what the current code *would* create. A write on the second call would fire for a container
    nobody asked to touch.

    Hence `stable_port` and `password` arrive as arguments rather than being resolved here: both
    come from allocate-once registries that CREATE machine-local state on a miss (a port entry, a
    secret file). `_ensure_service` resolves them, at one visible place, on every path.

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
        run_cmd += ["-p", f"127.0.0.1:{stable_port}:{svc.port}"]
    elif not svc.is_socket_only:
        run_cmd += ["-p", f"{svc.port}:{svc.port}"]
    if svc.wants_password:
        # Generic name: the launcher provisions a secret, the ENTRYPOINT decides what to call it
        # in its own protocol's terms. Same layering as client_env.
        run_cmd += ["-e", f"HARNESSED_SVC_PASSWORD={password}"]

    if svc.scope == "project":
        assert project_path is not None  # noqa: S101  # type-narrowing: guarded by the caller
        host_dir, _, location = _service_data_dir(svc, stack, project_path)
        # keep-id, pinned to the image uid: the service writes as the invoking user, so bind-mounted
        # bytes stay host-owned (a dolt data dir written by a foreign uid would EACCES for every
        # agent container). Unpinned, this was the loudest symptom of bd harnessed-rv2.1 — the
        # entrypoint's `mkdir -p /data/dolt` died with EACCES on any host whose uid is not 1000.
        run_cmd += [paths.USERNS_ARG, "-v", f"{host_dir}:/data:rw"]
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
        # tracked, the socket path is machine-local). Clients now learn the socket from
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
    # The two allocate-once values, resolved HERE rather than inside the pure builder: each creates
    # machine-local state on a miss (a port registry entry, a secret file), and the builder also runs
    # against containers we are only inspecting. Resolving them is idempotent — after the first
    # allocation both are plain reads — and unavoidable either way, since what the current code
    # WOULD publish is part of what we are comparing.
    stable_port = _svc_stable_port(svc, project_path) if svc.is_stable_port else 0
    password = _svc_password(svc, project_path) if svc.wants_password else ""

    # What the current code WOULD create — the yardstick for both the drift check below and the
    # label stamped on the new container. Built before the running-container check precisely so a
    # healthy-looking sidecar can be compared against it.
    want_cmd = _svc_run_cmd(
        rt, svc, cname, stack, project_path, mount_path,
        stable_port=stable_port, password=password,
    )
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
    _bounded([rt, "rm", "-f", cname], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
    if svc.is_socket_only:
        where = f"socket {svc.socket}"
    elif svc.is_ephemeral_port:
        where = f"127.0.0.1:<ephemeral>->{svc.port}"
    elif svc.is_stable_port:
        where = f"127.0.0.1:{stable_port}->{svc.port}"
    else:
        where = f":{svc.port}"
    _out.print(f"[blue][INFO][/blue] Starting service '{name}' on {where} ({cname})")
    if svc.scope == "project":
        assert project_path is not None  # noqa: S101  # type-narrowing: guarded above
        # The side effects and aborts `_svc_run_cmd` deliberately does not carry, because they must
        # fire only when a container is actually about to be created.
        host_dir, _, location = _service_data_dir(svc, stack, project_path)
        persist.guard_ownership(host_dir)
        host_dir.mkdir(parents=True, exist_ok=True)
        _assert_data_dir_unlocked(svc, host_dir)
        _assert_placement_unchanged(svc, location, project_path)

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
    # Deadline-driven for the reason spelled out in `_wait_hatago`: the error below names `timeout`
    # seconds, so a per-probe deadline on its own would multiply the real wait by the probe length.
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = _bounded(
            [rt, "exec", cname, "bash", "-c", svc.healthcheck],
            timeout=min(_PODMAN_PROBE_TIMEOUT, remaining),
            capture_output=True,
            warn=False,
        )
        if result.returncode == 0:
            return
        # A dead container fails the healthcheck for a reason no amount of waiting fixes: every
        # `exec` is failing because there is nothing to exec INTO. Distinguishing that from a
        # slow start is what separates "wait longer" from "abort now" — without it, a service that
        # died in its first second still burns the whole timeout before a warning nobody can act on.
        if _service_container_status(rt, cname) != "running":
            _abort_dead_service(rt, cname, svc)
        time.sleep(min(1, max(0.0, deadline - time.monotonic())))

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


# Catalog-authored shell, run on the host, on the launch critical path, once per recipe per launch.
# Conditions are meant to be cheap probes (`[ ! -f … ]`, `bd list`), so 30s is far past "slow" and
# well into "this will never answer" — a recipe author's typo must not be able to wedge every
# launch of every stack that includes it.
_SETUP_CONDITION_TIMEOUT = 30


def _listing(result: subprocess.CompletedProcess, what: str) -> str:
    """The stdout of a runtime LISTING query, or abort if the runtime did not answer.

    "podman says there are none" and "podman never replied" are the same empty string, and every
    caller here turns that into a cheerful "No instances found" and exits 0 — so a script wrapping
    the command reads success, and a human reads a completed cleanup that never happened. The
    returncode is the only thing separating the two, so reading a listing without consulting it is
    the bug, not the timeout.

    Guards every non-zero, not only `_TIMEOUT_RC`: a listing that failed for any reason is equally
    unable to say "none", and fixing only the deadline case would leave the same lie one line away.
    """
    if result.returncode != 0:
        _err.print(
            f"[bold red]error:[/bold red] could not list {what} — the container runtime exited "
            f"{result.returncode}. Refusing to report an empty result, which would read as "
            "'nothing to do' when the truth is 'we do not know'."
        )
        raise typer.Exit(1)
    return result.stdout


def _collect_setup_notices(
    recipes: list[Recipe], project_path: Path, stack: str, harness: str
) -> list[Recipe]:
    """Recipes whose user-facing `setup:` notice should be shown at this launch, in recipe order.

    A recipe qualifies when:
      - it declares a `setup.condition` that, run host-side in the project dir, exits 0 — i.e. the
        manual step is STILL needed (unchanged polarity; e.g. `! mytool status` is 0 until it is set
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
            proc = _bounded(
                ["bash", "-lc", recipe.setup.condition],
                timeout=_SETUP_CONDITION_TIMEOUT,
                # warn=False because the argv IS the condition — catalog-authored shell, which the
                # schema does not restrict and which may legitimately resolve a secret to do its job
                # (`… -p$(op read op://…)`). `_bounded`'s warning prints the whole command, so it
                # would put that secret on stderr and into any CI log capturing it. The same reason
                # the two healthcheck probes pass warn=False. The hang is still reported below, by
                # RECIPE NAME rather than by command text.
                warn=False,
                cwd=str(project_path),
                env={**os.environ, **harnessed_env(
                    stack, project_path, harness=harness, mode="host", recipe=recipe
                )},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # A timeout must NOT fall into the suppress branch. The polarity here is "non-zero =
            # already satisfied = say nothing", so treating a condition that never answered as
            # non-zero would silently drop a setup step the user still has to perform — and the
            # notice existing at all means nothing else is going to tell them. A redundant notice
            # is recoverable; a missing one is not. `_bounded` already warned.
            if proc.returncode == _TIMEOUT_RC:
                _err.print(
                    f"[bold red]warning:[/bold red] the `setup.condition` for recipe "
                    f"'{recipe.name}' did not finish within {_SETUP_CONDITION_TIMEOUT}s and was "
                    "killed. Showing its notice, since whether the step is still needed is now "
                    "unknown."
                )
            elif proc.returncode != 0:
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
        assert recipe.setup is not None  # noqa: S101  # type-narrowing: guaranteed by _collect_setup_notices
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


def _host_launch_plan(
    stack: str, harness: str, project_path: Path, *, recipes: list | None = None
) -> tuple[Path, list[str], Path, bool]:
    """Materialize the host home and return (home, argv, cwd, rebuilt) WITHOUT exec'ing.

    Split out from _launch_host so the plan is verifiable in tests without handing over the TTY.

    Materialization only: this is `HostBackend.materialize_config`'s whole body. Seeding auth is
    the separate contract operation `HostBackend.seed_auth` (`_share_host_claude_state`), called
    immediately after this returns and inside the same home lock — the credential RESCUE below
    stays here because it exists to survive the rmtree two lines under it, which is this
    function's own hazard rather than a step in wiring auth up.

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
    # Content-only: no --mcp-config / --strict-mcp-config — that flag wires the (absent) hub.
    argv = ["claude"]
    return home, argv, project_path, rebuilt


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


def _aoe_register(
    verb: str, stack: str, harness: str, project_path: Path, *, only: bool,
    group: Optional[str] = None, title: Optional[str] = None, no_strict_mcp: bool = False,
) -> None:
    """Mirror this launch into Agent of Empires, and stop here under `--create-aoe-only`.

    Two different contracts share one call. On a normal launch the mirror is passive: fire the
    write detached (`aoe add` takes ~12s) and carry on regardless of outcome — a dashboard is not
    worth blocking or failing a launch for. Under `--create-aoe-only` registering IS the command,
    so it blocks, reports, and propagates an exit status the user can script against.

    `group`/`title` are the `--aoe-group`/`--aoe-title` overrides; passing both also switches how an
    existing row is recognised. `no_strict_mcp` is recorded so a restart reproduces this launch's
    MCP surface. See `aoe.sync_session`.
    """
    drift: list[bool] = []

    def _on_drift(message: str, repairing: bool) -> None:
        # ESCAPED: a title carries `[<harness>/<backend>]`, which rich would eat as markup.
        drift.append(repairing)
        _err.print(f"[bold yellow]warning:[/bold yellow] {escape(message)}", highlight=False)

    registered = aoe.sync_session(
        verb, stack, harness, project_path, background=not only,
        group=group, title=title, no_strict_mcp=no_strict_mcp, on_drift=_on_drift,
    )
    if not only:
        return
    if not registered:
        if any(drift):
            # A repair was attempted, so the write that failed may have been the second half of
            # it. Saying "left as it is" here would send the user looking for a row that has
            # already been renamed aside.
            _err.print(
                "[bold red]error:[/bold red] --create-aoe-only: the repair failed part-way. The "
                "drifted row may have been renamed aside without its replacement being written — "
                f"check `aoe list -p {aoe.PROFILE}`."
            )
        elif drift:
            # The row was found and reported just above; repeating the install hint would send
            # the user looking for a broken aoe when aoe answered fine.
            _err.print(
                "[bold red]error:[/bold red] --create-aoe-only: left the existing row as it is; "
                "nothing was registered."
            )
        else:
            _err.print(
                "[bold red]error:[/bold red] --create-aoe-only: could not register the session. "
                "Is Agent of Empires (`aoe`) installed and initialized "
                f"({paths.xdg_config_home() / 'agent-of-empires'})?"
            )
        raise typer.Exit(1)
    _out.print(
        f"[bold green]Registered[/bold green] aoe session "
        f"[bold]{aoe.title_for(verb, stack, harness, project_path, title=title, no_strict_mcp=no_strict_mcp)}[/bold]\n"
        f"  profile:  {aoe.PROFILE}\n"
        f"  group:    {aoe.group_for(project_path, group=group)}\n"
        f"  command:  {aoe.command_for(verb, stack, harness, project_path, group=group, title=title, no_strict_mcp=no_strict_mcp)}\n"
        f"  [dim]not launched (--create-aoe-only); start it with `aoe` or `aoe session start`[/dim]",
        highlight=False,
    )
    raise typer.Exit(0)


def _warn_capability_gaps(backend: str, recipes) -> None:
    """Name every declaration this backend will not honor (BACKENDS.md §4, bd harnessed-0tk.2).

    A stack runs on any backend; that does not mean every primitive in it is honored there. Where it
    is not, the launch SUCCEEDS and the declaration is inert — so the user's only signal is this
    line. Today the one such cell is `egress:` on a backend whose isolation is `none`, which matters
    most for a credential-bearing recipe whose allowlist silently stops applying.

    Emitted at launch rather than in `assemble()` because this is where a concrete backend exists:
    `harnessed assemble` has a harness, not a backend, so the same check there could only ever
    answer "nothing to report" (see `capmatrix.gaps`, which refuses to say that about a backend it
    has no column for).

    LEVEL IS `[INFO]`, NOT `WARNING` (#359). `_acknowledge_warnings` counts the word WARNING and
    holds the terminal for a keypress, so at WARNING level every single `host-run` of a stack whose
    recipes declare `egress:` cost the user an extra Enter — for a gap they chose by typing
    `host-run` and cannot fix on that backend. A per-launch keypress about an unchanging, expected
    property is how a real warning gets trained away. The line still says exactly what is inert;
    it just does not claim the launch needs a decision.
    """
    for gap in capmatrix.gaps(backend, recipes):
        _err.print(
            f"[blue][INFO][/blue] {gap.primitive} ({gap.recipe}): {gap.detail}"
        )


@register
class HostBackend(ExecutionBackend):
    """The host backend: no podman, the agent runs as a process on this machine (BACKENDS.md §2).

    Isolation is `none` by declaration, so `apply_isolation` does nothing in either phase — see the
    method. Everything else is the code `_launch_host` has always run, in the order it has always
    run it; `_launch_host` is now the sequencer that calls these in that order.

    State the operations hand each other (the config dir, whether it was rebuilt, the agent's argv)
    lives on the instance rather than in `LaunchSpec`: it is backend-specific, and a spec field only
    one backend can honor is the fixed-order driver this contract deliberately does not have.
    """

    name = "host"
    isolation = ISOLATION_NONE

    def __init__(self, recipes: list) -> None:
        #: This stack's resolved recipe closure — the fingerprint gate reads it.
        self.recipes = recipes
        self.home: Path | None = None
        self.cwd: Path | None = None
        self.rebuilt = False
        self.argv: list[str] = []

    def materialize_config(self, spec: LaunchSpec) -> None:
        """Rebuild the host CLAUDE_CONFIG_DIR from the assembled profile (fingerprint-gated).

        The caller holds the home lock across this and `provision_tools(FIRST_START)` — see
        `_host_home_lock` for why releasing between them would let a second launch skip installs
        that are still running.
        """
        self.home, _argv, self.cwd, self.rebuilt = _host_launch_plan(
            spec.stack, spec.harness, spec.project_path, recipes=self.recipes
        )

    def seed_auth(self, spec: LaunchSpec) -> None:
        """Symlink the host's live `~/.claude` credential/session state into the config dir.

        Reference, never a copy (CLAUDE.md): the agent refreshes the host's own token in place, so
        a host session and every container session stay one login. `_rescue_host_credentials`,
        which runs inside `materialize_config`, is what keeps that true across the rmtree when a
        previous session's refresh replaced the symlink with a regular file (bd harnessed-8px.10).
        """
        assert self.home is not None, "seed_auth before materialize_config"  # noqa: S101  # type-narrowing: ordering enforced by caller
        _share_host_claude_state(self.home)

    def provision_tools(self, spec: LaunchSpec, phase: ProvisionPhase) -> None:
        """`tools:` + `install:` on first start; each recipe's `setup.script` at attach.

        FIRST_START runs under the caller's home lock and is skipped when the fingerprint matched
        (bd harnessed-8px.12) — an install is logically once per STACK, not once per launch. ATTACH
        must run OUTSIDE that lock: a setup script can prompt, and holding an exclusive flock across
        a TTY prompt would hang any concurrent launch of the same stack.
        """
        if phase == FIRST_START:
            assert self.home is not None, "provision_tools(FIRST_START) before materialize_config"  # noqa: S101  # type-narrowing: ordering enforced by caller
            if self.rebuilt:
                # `tools:` BEFORE `install:` — the same order as the derived image, and load-bearing:
                # an install.sh now configures a binary that tools: provides (serena init -b LSP).
                _host_install_tools(spec.stack, self.recipes)
                _host_run_installs(
                    spec.stack, spec.project_path, harness=spec.harness, home=self.home
                )
                # ONLY now is the build complete. _host_run_installs exits non-zero on failure, so a
                # failed install never reaches this line and the next launch rebuilds and retries
                # instead of trusting a stamp that certifies content which was never finished.
                _stamp_host_home(self.home, _host_stack_fingerprint(spec.stack, self.recipes))
            else:
                _say(f"[blue][INFO][/blue] Stack unchanged — reusing {self.home} (installs skipped)")
            return
        # Run each recipe's executable first-run setup (e.g. `mytool init --shared-server …`). The tool
        # owns the shared-server daemon lifecycle — harnessed no longer manages any beads process.
        _host_run_setups(spec.stack, spec.project_path, harness=spec.harness)
        # Recipe `init:` — the host half of the attach shell's init prologue. After setups, since a
        # setup script may install the very binary init invokes.
        _host_run_inits(spec.stack, spec.project_path, harness=spec.harness)

    def wire_mcp(self, spec: LaunchSpec) -> None:
        """Write the stack's `.mcp.json` and build the agent argv that points claude at it.

        Native stdio servers, no hatago hub on this backend. Resolved after PATH is set so the
        stdio-command presence check sees just-provisioned tools AND anything an install/setup
        script put in the stack bin dir.
        """
        assert self.home is not None, "wire_mcp before materialize_config"  # noqa: S101  # type-narrowing: ordering enforced by caller
        mcp_servers = _host_native_mcp(spec.stack)
        # ALWAYS write .mcp.json + --strict-mcp-config, even with no servers: strict makes claude
        # load ONLY this file, so the copied .claude.json's global mcpServers never leak into an
        # isolated stack (content-only included). With servers → the stack's set; without → an empty
        # set. --no-strict-mcp-config opts OUT of that isolation: the file is still passed, but
        # claude also reads the project's `.mcp.json` and the user config.
        mcp_path = self.home / ".mcp.json"
        mcp_path.write_text(json.dumps({"mcpServers": mcp_servers or {}}, indent=2), encoding="utf-8")
        self.argv = ["claude", "--mcp-config", str(mcp_path)]
        if not spec.no_strict_mcp:
            self.argv.append("--strict-mcp-config")
        self.argv += list(spec.extra)

    def wire_services(self, spec: LaunchSpec) -> None:
        """Start the SAME sidecars the container backend ensures (bd harnessed-2sm).

        A `services:` entry is a property of the STACK, not of the backend: host mode makes the
        AGENT host-native, it does not remove the service the stack says it needs. Omitting this
        left every beads stack under `host-run` with no server, no socket and no data dir.

        A socket-backed sidecar composes with a host agent for free: the socket is a filesystem
        object inside the persist dir the service bind-mounts, so the host process dials exactly the
        path the container serves it on. No port, no netns to bridge, nothing mode-specific.

        Guarded on the stack actually declaring services, so a host launch of a service-less stack
        still needs no container runtime at all.
        """
        if not _service_refs(spec.stack):
            return
        # _resolve_mount_path, not project_path (bd harnessed-wnf): the sidecar must get the same
        # git surface whichever entry point starts it. Otherwise the create-time config — and so the
        # `harnessed.svc-config-hash` label — differs by entry point, and alternating host-run with
        # a container launch would flag drift and recreate the container every single time.
        _ensure_services(
            _runtime(), spec.stack, project_path=spec.project_path,
            mount_path=_resolve_mount_path(spec.project_path, None),
        )

    def apply_isolation(self, spec: LaunchSpec, phase: IsolationPhase) -> None:
        """Nothing, in either phase — `isolation` is `none` on this backend (BACKENDS.md §2).

        This is the contract honored, not skipped. A host launch is deliberately the escape hatch
        with the host's own auth, filesystem and network; §4's matrix records host egress control as
        `landlock/proxy`, i.e. the bwrap backend's job (harnessed-0tk.3), not this one's.
        """


def _launch_host(
    stack: str, harness: str, path: Optional[str], *, rm: bool = False,
    extra: Optional[list[str]] = None, create_aoe_only: bool = False,
    no_strict_mcp: bool = False,
    aoe_group: Optional[str] = None, aoe_title: Optional[str] = None,
) -> None:
    """Host-native launch: no podman. Materialize the assembled profile into a host CLAUDE_CONFIG_DIR,
    start any host daemons (beads-server, hatago MCP hub), and exec the harness on the host so it sees
    the host's own auth.

    `rm` switches from exec (persist the daemons, clean TTY handoff) to supervise (fork claude, wait,
    then stop the daemons THIS launch started).

    `no_strict_mcp` (--no-strict-mcp-config) omits `--strict-mcp-config`, so claude reads its own MCP
    sources (project `.mcp.json`, user config) in addition to the stack's file."""
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
        raise typer.Exit(1) from exc

    # Same mirror as the container path, recorded under this verb so the two never collide: a
    # host-native session and a containerized one for the same stack+harness+folder are different
    # things to run. No-op when aoe is absent; never raises.
    #
    # AFTER assembly, not before. Assembly is this backend's real validation gate — the analogue of
    # `launch`'s is_built/staleness checks — so registering ahead of it would leave a row behind for
    # a launch that then died on a renamed recipe, and that row would fail identically every time it
    # was started from the dashboard. It costs `--create-aoe-only` one assembly, which is
    # sub-second, emit-only and container-free on this path.
    # BEFORE the row, because the row's command is `--last` and `--last` reads this. `_aoe_register`
    # EXITS under `--create-aoe-only`, so recording afterwards would write a row whose one job is to
    # replay a launch that was never recorded — dead on arrival, failing "nothing to replay" every
    # time it is started. That is the same class of dead row the comment above avoids by
    # registering after assembly.
    lastrun.record(
        "host-run", stack, harness, project_path,
        group=aoe_group, title=aoe_title, no_strict_mcp=no_strict_mcp,
    )
    # AFTER assembly, not before. Assembly is this backend's real validation gate — the analogue of
    # `launch`'s is_built/staleness checks — so registering ahead of it would leave a row behind for
    # a launch that then died on a renamed recipe, and that row would fail identically every time it
    # was started from the dashboard. It costs `--create-aoe-only` one assembly, which is
    # sub-second, emit-only and container-free on this path.
    _aoe_register(
        "host-run", stack, harness, project_path, only=create_aoe_only,
        group=aoe_group, title=aoe_title, no_strict_mcp=no_strict_mcp,
    )

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

    # The recipe closure, hoisted above the sidecars so the backend can be constructed with it.
    # Inert as a reordering: `assemble(..., strict=True)` above already resolved and validated every
    # recipe this reads, so there is no failure left here for the sidecars to have preceded.
    host_stk, host_recipes = load_stack_with_recipes(None, stack)
    backend = HostBackend(host_recipes)
    # Before anything is materialized: a declaration this backend cannot honor is worth knowing
    # about while there is still a choice to make (rerun under `container-run`), not after the
    # agent is already up.
    _warn_capability_gaps(HostBackend.name, host_recipes)
    spec = LaunchSpec(
        stack=stack, harness=harness, project_path=project_path,
        extra=tuple(extra or []), no_strict_mcp=no_strict_mcp, ephemeral=rm,
    )

    # Sidecars — the SAME ones `launch` ensures (bd harnessed-2sm). Ahead of the recipe env and setup
    # scripts below, which is what needs the socket to already exist.
    backend.wire_services(spec)

    # Hand the PROJECT the same tool env we are about to hand the agent, so a plain `bd` in this
    # repo is configured too. After services, because the client env includes their connection.
    _write_project_tool_env(
        stack, project_path, harness=harness, verb="host-run",
        no_strict_mcp=no_strict_mcp, aoe_group=aoe_group, aoe_title=aoe_title,
    )

    # Recipe `env:` — the host half of what the derived image's ENV does for a container launch.
    # Set on THIS process (same reasoning as the PATH mutation below: the process is dedicated to
    # this launch), so all three consumers get it from one place: any install/setup script spawned
    # from here inherits it, and so does claude itself — `env = dict(os.environ)` at the exec below
    # is what actually delivers it to the running agent, the row that was broken before.
    # Recipe declarations win over an inherited value, mirroring `podman run -e` in container mode.
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
    # CLEARS as well as sets — see `_HOST_MISE_UNSET`. Launching a stack from inside another stack's
    # host session inherits that session's MISE_STATE_DIR, and only a removal gets rid of it.
    _apply_host_mise_env(os.environ, stack)
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
    # let a second launch skip installs that are still running. `seed_auth` joins them inside it,
    # exactly where `_host_launch_plan` used to perform it.
    with _host_home_lock(paths.host_home(stack, harness)):
        backend.materialize_config(spec)
        backend.seed_auth(spec)
        # `install:` — the host half of the derived image's `RUN bash install.sh`, i.e. the content
        # a Dockerfile RUN used to deliver to containers only.
        backend.provision_tools(spec, FIRST_START)
    # setup.script — outside the lock, because a setup can prompt (see provision_tools).
    backend.provision_tools(spec, ATTACH)
    home, cwd = backend.home, backend.cwd
    if cwd is None:
        raise RuntimeError("cwd not set; materialize_config must be called first")

    # Pending `setup:` notices, and BLOCK on them — the host half of what `launch` does at its own
    # line. This was container-only too, so a host launch printed nothing and started the agent
    # anyway: a fresh `beads/team` checkout came up with no workspace, and the agent discovered it
    # rather than the user. Runs after init, so a recipe that self-initializes (beads/stealth) has
    # already satisfied its own condition and stays silent. `allow_terminal=False` — there is no
    # container to drop a shell into here.
    _prompt_setup_notices(host_recipes, project_path, stack, harness, allow_terminal=False)
    # Native MCP (hatago deferred): resolve after PATH is set so the stdio-command presence check
    # sees just-provisioned tools AND anything an install/setup script put in the stack bin dir.
    backend.wire_mcp(spec)
    argv = backend.argv
    # No-ops on this backend (isolation: none) — called so the host path exercises the whole
    # contract rather than quietly implementing five sixths of it. See HostBackend.apply_isolation.
    backend.apply_isolation(spec, BOUNDARY)
    backend.apply_isolation(spec, EGRESS)

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
        os.execvpe(argv[0], argv, env)  # never returns  # noqa: S606 — no shell is the POINT: argv is passed as a vector, so nothing is word-split or glob-expanded
    # --rm: supervise (fork claude, wait). No host daemons to tear down — bd owns its shared server.
    # unbounded: this IS the agent session. Its duration is however long the user works; any
    # deadline here kills a live session mid-thought. The non---rm branch above execvpe's for the
    # same reason.
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
    """The stack to run — named via `--stack`, composed from a `--recipe` set, or, with neither
    given, the `--extends` baseline (`default`). Shared by both run verbs, which differ in BACKEND
    and not in how a stack is chosen (bd harnessed-s84).

    Returns `(name, minted_dir)`. `minted_dir` is non-None only when THIS call created the
    manifest, making it the caller's to remove if a later build fails. An authored stack and a
    dynamic one whose manifest already existed both yield None — neither is ours to delete.
    """
    # First-run overlay bootstrap. It belongs HERE rather than in either verb: resolution is the
    # step that needs the shipped baseline to exist (a `--recipe` set mints `extends: default`),
    # and one shared call site is what keeps the two backends in step — `container-run` and
    # `host-run` differ in backend, never in how a stack is chosen. Only the seed runs; the
    # catalog-local symlinks are a source-checkout DX convenience a launch should not assert.
    _seed_user_default_recipe()

    if stack and recipe:
        _err.print("[bold red]error:[/bold red] provide either --stack or --recipe, not both")
        raise typer.Exit(1)
    if not stack and not recipe:
        # Neither named: run the baseline every dynamic stack extends, exactly as if the user had
        # typed `--stack default`. Composing nothing on top of the baseline is a legitimate launch,
        # not a malformed one — requiring a throwaway `--recipe` to reach it made the common
        # "just start the agent" case the only one with mandatory flags (bd harnessed-jhj).
        # `--no-extends` is the one shape that cannot mean this: it says inherit from nothing, and
        # with no recipe list to stand alone there is nothing left to run.
        if no_extends:
            _err.print(
                "[bold red]error:[/bold red] --no-extends needs at least one --recipe "
                "(it inherits nothing, so the recipe list is the whole stack)"
            )
            raise typer.Exit(1)
        return extends, None
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


def _resolve_last(
    verb: str, harness: str, path: Optional[str],
    stack: Optional[str], recipe: list[str], extends: str, no_extends: bool, service: list[str],
    *, no_strict_mcp: bool, aoe_group: Optional[str], aoe_title: Optional[str],
) -> tuple[str, bool, Optional[str], Optional[str]]:
    """Replay the last launch in this folder — the `--last` path (bd harnessed-7mt).

    This is what the aoe dashboard row invokes (`aoe.replay_command`), and what a human types to get
    the same thing back without retyping a recipe set. It is deliberately a FLAG rather than the
    bare `harnessed <verb>-run <harness>` form: bare is documented as the `default` baseline, and
    redefining it would silently change the most-typed command in a folder whose record names a
    different stack — the wrong-stack-at-exit-0 class this module keeps paying to avoid.

    FAILS LOUDLY with no record. Falling back to the baseline is precisely the silent wrong launch
    above, one layer down: the row says "restart what was here", and starting something else while
    reporting success is worse than not starting at all.

    Explicit flags still win. `--last --aoe-title x` replays the stack and takes the new title; the
    record only fills what the user did not say.

    EVERY STACK-SELECTION INPUT IS REJECTED, not just `--stack`/`--recipe`. They each feed
    `_resolve_stack`, which `--last` skips entirely, so any of them left merely "allowed" would be
    accepted and then silently dropped — `--last --service redis` would start no redis and say
    nothing. Rejecting is not an inconvenience here: pairing "replay the last launch" with an
    instruction to compose a different one is a contradiction, and picking a winner silently is how
    you get a launch nobody asked for. Lifecycle flags (`--fresh`, `--rm`) are deliberately NOT in
    this set — they say what you want THIS time and apply to a replay exactly as they would to any
    other launch.
    """
    conflicting = [
        name for name, given in (
            ("--stack", bool(stack)), ("--recipe", bool(recipe)), ("--service", bool(service)),
            ("--extends", extends != _EXTENDS_DEFAULT), ("--no-extends", no_extends),
        ) if given
    ]
    if conflicting:
        _err.print(
            f"[bold red]error:[/bold red] --last replays the last launch here; "
            f"{', '.join(conflicting)} compose a different one. Provide one or the other."
        )
        raise typer.Exit(1)

    project_path = Path(path).resolve() if path else Path.cwd()
    entry = lastrun.load(verb, harness, project_path)
    if entry is None:
        _err.print(
            f"[bold red]error:[/bold red] no recorded {verb} launch for {harness} in "
            f"{project_path} — nothing to replay.\n"
            f"Start one explicitly first (e.g. `harnessed {verb} {harness}` for the default "
            f"baseline, or with --stack/--recipe), and --last will replay it after that."
        )
        raise typer.Exit(1)

    return (
        entry["stack"],
        no_strict_mcp or bool(entry.get("no_strict_mcp")),
        aoe_group if aoe_group is not None else entry.get("aoe_group"),
        aoe_title if aoe_title is not None else entry.get("aoe_title"),
    )


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
# The baseline `--extends` names when the user does not. Named because `_resolve_last` compares
# against it to tell "user asked for a different baseline" from "user said nothing".
_EXTENDS_DEFAULT = "default"
_EXTENDS_OPT = typer.Option(
    _EXTENDS_DEFAULT, "--extends",
    help="Stack to inherit from (baseline recipes, permissions, credential forwarding). "
         "With neither --stack nor --recipe, this baseline is itself the stack that runs.",
)
_NO_EXTENDS_OPT = typer.Option(
    False, "--no-extends", help="Inherit from nothing — the recipe list stands alone.",
)
_SERVICE_OPT = typer.Option(
    [], "--service",
    help="Extra service sidecar. Rarely needed: a recipe declares the services it requires.",
)
_NO_STRICT_MCP_OPT = typer.Option(
    False, "--no-strict-mcp-config",
    help="claude only: drop --strict-mcp-config so claude ALSO loads its own MCP sources (the "
         "project's .mcp.json, your user config) on top of the stack's. Default is strict — the "
         "stack's MCP surface is exactly what it declares.",
)
_AOE_GROUP_OPT = typer.Option(
    None, "--aoe-group",
    help="Agent of Empires group for this session's row, instead of the repo name it is derived "
         "from. Created if it does not exist. With --aoe-title, also identifies the row to reuse.",
)
_AOE_TITLE_OPT = typer.Option(
    None, "--aoe-title",
    help="Agent of Empires title for this session's row, instead of the derived "
         "'<folder> [<harness>/<backend>] <stack>'. With --aoe-group, also identifies the row to "
         "reuse — the pair is how an existing or hand-written row is adopted rather than duplicated.",
)
_LAST_OPT = typer.Option(
    False, "--last",
    help="Replay the last launch of this harness in this folder — its stack and flags, without "
         "retyping them. This is what an Agent of Empires row runs. Errors if nothing was launched "
         "here yet; it never falls back to the default baseline. Not combinable with "
         "--stack/--recipe, which select a different stack.",
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
    no_strict_mcp_config: bool = _NO_STRICT_MCP_OPT,
    aoe_group: Optional[str] = _AOE_GROUP_OPT,
    aoe_title: Optional[str] = _AOE_TITLE_OPT,
    last: bool = _LAST_OPT,
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

        harnessed host-run <harness> [path]                        # the `default` baseline
        harnessed host-run <harness> [path] --stack <name>
        harnessed host-run <harness> [path] --recipe r1 --recipe r2
        harnessed host-run <harness> [path] --last                 # replay what ran here last

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
    if last:
        # No mint on this path — the record already names a RESOLVED stack (a `--recipe` set was
        # minted by the launch that recorded it), so there is nothing to create and nothing to
        # clean up if the launch fails. Hence minted_dir stays None.
        stack_name, no_strict_mcp_config, aoe_group, aoe_title = _resolve_last(
            "host-run", harness, path, stack, recipe, extends, no_extends, service,
            no_strict_mcp=no_strict_mcp_config, aoe_group=aoe_group, aoe_title=aoe_title,
        )
        minted_dir = None
    else:
        stack_name, minted_dir = _resolve_stack(stack, recipe, extends, no_extends, service)
    try:
        _launch_host(
            stack_name, harness, path, rm=rm, extra=_passthrough,
            create_aoe_only=create_aoe_only, no_strict_mcp=no_strict_mcp_config,
            aoe_group=aoe_group, aoe_title=aoe_title,
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


@register
class ContainerBackend(ExecutionBackend):
    """The podman backend: the agent runs in a rootless pod (BACKENDS.md §2).

    Same contract as `HostBackend`, sequenced differently — and the difference is the reason this
    contract is a capability set rather than a pipeline. This backend provisions BEFORE it
    materializes, because podman's copy-up is what lifts the image's `~/.claude` into the volume
    that the mount set then delivers; the host backend must do the reverse, because materializing
    rmtree's the very dir installs write into.

    `container_run` is the sequencer. State the operations hand each other lives on the instance.
    """

    name = "container"
    isolation = ISOLATION_CONTAINER

    def __init__(
        self, rt: str, inst: str, pod: str, prof: Path, harness_image: str, mount_path: Path,
        recipes: list, servers: list, stk, *, stack_from_overlay: bool, headless: bool,
    ) -> None:
        self.rt = rt
        self.inst = inst
        self.pod = pod
        self.prof = prof
        self.harness_image = harness_image
        self.mount_path = mount_path
        self.recipes = recipes
        #: The stack's resolved MCP server set. Computed once by the sequencer and shared, so
        #: `wire_mcp` and the settings merge cannot drift apart on what this stack's servers are.
        self.servers = servers
        self.stk = stk
        self.stack_from_overlay = stack_from_overlay
        self.headless = headless
        self.config_volume: str | None = None
        self.tools_volume: str | None = None
        self.mount_args: list[str] = []
        self.member_mounts: list[str] = []
        self.pending_setups: list = []
        # Set by seed_auth; initialized here so apply_isolation reads an empty list rather than
        # raising AttributeError if a future sequencer ever skips the operation.
        self.secrets_env_files: list = []
        self.secrets_temp_files: list = []

    def provision_tools(self, spec: LaunchSpec, phase: ProvisionPhase) -> None:
        """Compose the per-stack volumes on first start; run each `setup.script` at attach.

        FIRST_START is the container mirror of the host path's `rebuilt` gate — fingerprint-gated,
        so an unchanged stack pays nothing, and a CHANGED stack reinstalls here with no podman
        build at all (bd harnessed-8px.21: a one-line recipe edit used to cost a 307s layer
        rebuild). It composes BOTH volumes in one call because podman's copy-up populates them
        together; `materialize_config` is what then delivers the config volume to the harness.

        ATTACH runs the setup scripts via `podman exec`, so it necessarily follows
        `apply_isolation(BOUNDARY)` — and precedes `apply_isolation(EGRESS)`, since a first-run
        setup is exactly the step that downloads things.
        """
        if phase == FIRST_START:
            # Uses `harness_image` — the derived image when one exists, else the plain agent image —
            # because podman's copy-up is what lifts that image's `~/.claude` into the volume.
            self.config_volume, self.tools_volume = _ensure_stack_volumes(
                self.rt, spec.stack, spec.harness, self.prof, self.harness_image, self.recipes
            )
            return
        _run_container_setups(
            self.rt, self.inst, self.pending_setups, spec.stack, spec.project_path,
            harness=spec.harness,
        )

    def materialize_config(self, spec: LaunchSpec) -> None:
        """Compose the mount set that delivers the assembled profile into the pod.

        NOTE — a known imprecision in this slice, tracked as harnessed-0tk.1.1: several CREDENTIAL
        mounts are composed here rather than in `seed_auth`. They are emitted as one ordered block
        today, and this repo's suite runs no `podman run` at all (CLAUDE.md), so regrouping podman
        `-v` arguments would be an unverifiable change to the one path no test exercises. The block
        moves verbatim; splitting it is its own change with its own evidence. `seed_auth` owns the
        part that is already contiguous and deliberately last.
        """
        assert self.config_volume and self.tools_volume, "materialize_config before provision_tools"  # noqa: S101  # type-narrowing: ordering enforced by caller
        # Build mount args.
        self.mount_args = _build_mount_args(
            spec.harness, self.prof, self.mount_path, self.config_volume, self.tools_volume
        )
        # Seed a token-free ~/.claude.json stub so Claude skips onboarding (auth = the token/credential).
        self.mount_args += _claude_config_seed_mount(
            spec.harness, self.inst,
            # Same gate as seed_auth: an isolated stack gets the onboarding fields WITHOUT the host
            # account's email/uuid/organization, which have no business in a container that
            # authenticates as someone else.
            isolated_auth=self.stk.isolated_auth and spec.harness == "claude",
        )
        # NB: the Claude credential fallback mount is appended AFTER secrets resolve (see seed_auth)
        # — whether it is needed at all depends on a CLAUDE_CODE_OAUTH_TOKEN that may arrive via
        # --env-file.
        # Persist agy's in-pod keyring store (rw) so its Google-OAuth token survives recreates (antigravity).
        self.mount_args += _keyring_state_mount(spec.harness, self.inst)
        # Persist mcp-remote's OAuth token store (rw) so a consent outlives the instance it happened
        # in. Sourced from the host's ~/.mcp-auth, or — for an isolated_auth stack, which runs as a
        # DIFFERENT account — from that instance's own dir, so it never inherits the host's identity.
        # No-op for every stack that runs no mcp-remote. Pairs with the callback publish on the pod.
        self.mount_args += _mcp_auth_store_mount(
            self.servers, self.inst, self.stk.isolated_auth
        )
        # Share omp's state with the host (auth + usage + sessions) via a bind mount of ~/.omp/agent.
        self.mount_args += _omp_agent_mount(spec.harness)
        # Point omp at the in-container hatago hub (nested ro mount shadowing the agent dir's
        # mcp.json), so a stack's assembled MCP servers reach omp — mirrors claude's --mcp-config
        # wiring. Emitted here, immediately after the dir mount it shadows, because the ORDER of
        # this block is load-bearing (see the note above); `wire_mcp` owns the hub itself.
        self.mount_args += _omp_mcp_seed_mount(spec.harness, self.inst)
        # Forward the host's ccstatusline config (ro) so the baked statusLine matches the host layout.
        self.mount_args += _ccstatusline_settings_mount()
        # Bind-mount the corporate proxy CA (ro) so _install_corp_proxy_ca_in_container can register it.
        self.mount_args += _corp_proxy_ca_mount_args()
        # Persist recipe-declared project-scoped folders (rw) so their state survives --fresh.
        self.mount_args += _persist_mounts(spec.stack, spec.project_path)
        # Forward the host's git signing + push credentials (1Password/GPG/YubiKey agent, git config,
        # ssh config/known_hosts/pubkeys + opt-in private keys) so the agent can push and sign — no
        # secret baked into an image. Private keys (ssh_keys) are honored ONLY from the user's own overlay
        # catalog — a shared repo-catalog stack must not mount your private key.
        if self.stk.forward_git_credentials:
            trusted_keys = _trusted_ssh_keys(self.stk.ssh_keys, self.stack_from_overlay, spec.stack)
            self.mount_args += _credential_forward_args(ssh_keys=trusted_keys, rt=self.rt)
        else:
            # Even without the full opt-in, auto-forward the SSH signing/auth agent (1Password/gpg) +
            # ro git config whenever the agent socket is live on the host: "1Password available → wired
            # up". The agent gates every use behind a host approval/touch and exposes no key material, so
            # this is safe as a default; the secret-bearing surface (gh oauth token, private keys) still
            # requires forward_git_credentials.
            self.mount_args += _ssh_agent_auto_forward_args(rt=self.rt)

        # Forward host AWS credentials via the aws-sso ECS server (opt-in per stack). Injects the AWS SDK's
        # ECS-task-role endpoint + bearer token as env only — no aws-sso binary/store/token enters the
        # container. No-op unless the host token file exists (written by `harnessed aws-sso serve`).
        if self.stk.forward_aws_sso:
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
                if self.headless or not sys.stdin.isatty() or not typer.confirm(
                    "Continue launching without AWS credentials?", default=False
                ):
                    raise typer.Exit(1)
            elif aws_args:
                self.mount_args += aws_args

    def seed_auth(self, spec: LaunchSpec) -> None:
        """Resolve launch-time secrets and append the Claude credential mount, which must be LAST.

        Referenced, never baked (CLAUDE.md): the credential file is mounted from the host's live
        store, and a long-lived CLAUDE_CODE_OAUTH_TOKEN supersedes it — in which case nothing is
        mounted at all. Returns the ordered `--env-file` list and the temp files the caller must
        unlink once podman has ingested them; resolved secrets must not linger on disk (T-05-06).
        """
        # Layered global → project (project wins on conflict). Stays AFTER the aborting checks in
        # materialize_config so an early exit can't strand resolved secrets on disk.
        secrets_env_files, secrets_temp_files = _resolve_launch_secrets(spec.project_path)
        if self.stk.isolated_auth and spec.harness == "claude":
            # This stack has its OWN identity: neither the host's token nor the host's credential
            # file may reach it, or it would come up as the WRONG ACCOUNT — the one failure this
            # field exists to prevent. `_build_pod_args` suppresses the token forward off the same
            # condition; here the seed mount is simply not built.
            self.mount_args += _claude_isolated_auth_mount(spec.harness, self.inst)
            # ...and the env-file route too: --env-file is passed unconditionally, so a token in the
            # user-global .env.schema would otherwise walk straight past both suppressions above.
            _strip_var_from_env_files(_OAUTH_TOKEN_VAR, secrets_env_files)
        else:
            if self.stk.isolated_auth:
                # Gated on the harness, NOT just the flag: omp authenticates from the SAME
                # CLAUDE_CODE_OAUTH_TOKEN this branch would otherwise strip, so suppressing it here
                # would leave an omp launch with no auth at all — while the warning below promised
                # the opposite. Every non-claude harness therefore falls through to the normal path.
                _err.print(
                    "[bold yellow]warning:[/bold yellow] this stack sets [bold]isolated_auth[/bold] but "
                    f"[bold]{spec.harness}[/bold] keeps its credentials outside "
                    "~/.claude/.credentials.json, so the flag does nothing here — this launch uses "
                    "the host identity.\n"
                    "  Isolated auth is claude-only today."
                )
            # Claude auth, last of the mounts: a long-lived CLAUDE_CODE_OAUTH_TOKEN (host env, varlock,
            # or plain .env) supersedes the credential file, so nothing is mounted in that case.
            self.mount_args += _claude_creds_seed_mount(
                spec.harness, self.inst, _claude_oauth_token_configured(spec.harness, spec.project_path)
            )
        self.secrets_env_files = secrets_env_files
        self.secrets_temp_files = secrets_temp_files

    def wire_mcp(self, spec: LaunchSpec) -> None:
        """Regenerate this instance's hatago config and mount it (ro) into the harness container.

        Every assembled MCP server is fronted by the hub, so wiring MCP on this backend is wiring
        hatago. Written per-instance with each stdio child's cwd pinned to the mirrored project path
        (bd main-u5d): the committed profile config is project-agnostic (built before any project is
        known — path mirroring makes the container project path per-launch), so serena/repowise
        would otherwise resolve the container home instead of the project root. Per-instance so two
        projects on the same stack never race on one shared cwd.

        Waiting for the hub to come up is a readiness gate, not wiring — the sequencer does it after
        the container starts, the same way a service sidecar's health check sits outside
        `wire_services`.
        """
        inst_cfg_dir = self.prof / ".instances" / self.inst
        inst_cfg_dir.mkdir(parents=True, exist_ok=True)
        hatago_cfg_host = emit.write_hatago_config(inst_cfg_dir, self.servers, spec.project_path)
        hatago_cfg_ctr = str(paths.hatago_config_container())
        # Filter --userns out of the member args (it is a pod-level property). Mount the hatago
        # config (ro) into the HARNESS container — after the hatago-consolidation, hatago runs IN
        # this container (not a separate pod member), so the hub and the stdio children it spawns
        # share this container's home and see the project bind-mount.
        self.member_mounts = _without_userns(self.mount_args)
        self.member_mounts += ["-v", f"{hatago_cfg_host}:{hatago_cfg_ctr}:ro"]
        self.member_mounts += _setup_script_mounts(self.recipes)

    def wire_services(self, spec: LaunchSpec) -> None:
        """Start any service sidecars this stack's recipes reference. Idempotent.

        Global services are host-published (reached from the pod via host.containers.internal:<port>);
        project-scoped ones bind-mount this project's persist dir and are reached through a unix
        socket inside it, so they need the project/mount context.

        The sequencer calls this BEFORE the re-attach branch, deliberately: a long-lived agent
        container outlives its sidecars. This used to sit after the create path only, so once an
        instance was running, every subsequent launch took the attach branch and never looked at
        services again — a sidecar that died stayed dead for the life of the container, long after
        whatever killed it was gone (observed 2026-07-21: a sidecar dead for 3h, revived by nothing,
        while `bd` failed every session). Reviving it is exactly what "idempotent" already promised.
        """
        _ensure_services(
            self.rt, spec.stack, project_path=spec.project_path, mount_path=self.mount_path
        )

    def apply_isolation(self, spec: LaunchSpec, phase: IsolationPhase) -> None:
        """Stand the pod up (BOUNDARY), then close egress once setups have had the network (EGRESS).

        BOUNDARY is also what DELIVERS everything the earlier operations composed: on this backend
        the single `podman run` is both the isolation boundary and the only way mounts and env cross
        it, which is why the env assembly lives here rather than in `materialize_config`. The setup
        env is resolved here too because a `setup.config` item may prompt, and that must happen
        before the container starts.
        """
        if phase == EGRESS:
            # Recipe-declared egress: union the extra allowlist hosts across this stack's recipes so
            # the firewall opens them ONLY when a recipe that needs them is present (default-DROP
            # otherwise).
            egress_domains = sorted({d for r in self.recipes for d in r.egress})
            try:
                _apply_firewall(self.rt, self.inst, egress_domains)
            except BaseException:
                # By this phase BOUNDARY has already started the pod, so simply propagating would
                # hand the user their shell back and leave a container running with UNRESTRICTED
                # egress — quieter than the old unbounded hang, and no safer. Failing closed has to
                # mean the thing we could not confine does not survive, so tear it down first.
                #
                # BaseException, not typer.Exit: `_bounded` catches only TimeoutExpired, so an OSError
                # from `subprocess.run` (podman missing, permission denied) would skip a narrower
                # handler and leave exactly the unconfined container this exists to prevent. Ctrl-C
                # belongs here too — an interrupted launch must not strand one either. Nothing is
                # swallowed: every path re-raises.
                _err.print(
                    f"[bold red]error:[/bold red] tearing down {self.inst} — it cannot be left "
                    "running without the egress firewall it was launched with."
                )
                _pod_teardown(self.rt, self.inst, self.pod or self.inst)
                raise
            return

        # Pod network.
        net = os.environ.get("HARNESSED_NET", "")

        # Create pod.
        if _rt_uses_pods(self.rt):
            # --hostname explicitly: without it podman uses the pod NAME, which crun rejects past
            # HOST_NAME_MAX (see paths.container_hostname). Set on the POD, not the member — pod
            # members share the pod's UTS namespace, so this is the one that governs.
            pod_cmd = [
                self.rt, "pod", "create", "--name", self.pod,
                "--hostname", paths.container_hostname(self.pod), paths.USERNS_ARG,
            ]
            # Publish mcp-remote's OAuth callback port (loopback only) so the redirect can reach the
            # process waiting for it. Without this the pod publishes nothing, the browser opens
            # inside the container where nobody sees it, and a URL pasted into the host's browser
            # redirects to the HOST's loopback — a different netns from the listener — so the flow
            # times out three times with no explanation. Ports are a POD-level property, so this
            # belongs here and not on the member. Empty unless a recipe pins one.
            # The publish is INERT without pasta's --host-lo-to-ns-lo: mcp-remote binds the pod's
            # 127.0.0.1 unconditionally, and pasta forwards to the namespace's public address by
            # default. Measured both ways on real podman — see the helper. Composed there as one
            # list so the two cannot be wired apart, and so it also owns the plain `--network`
            # passthrough (which cannot be passed twice). Empty unless a recipe pins a port.
            pod_cmd += _mcp_remote_pod_args(self.servers, net)
            _run(pod_cmd, capture_output=True)

        # Socket-backed project services (beads-server) as REAL container env, not only an attach-shell
        # export: `_init_shell_prologue` reaches the interactive shell and nothing else, so a `podman
        # exec`, a hook, or any subprocess saw $HARNESSED_BEADS_SERVER_SOCKET unset — and bd silently
        # accepts an EMPTY --server-socket, falling back to its old TCP config instead of failing. Set it
        # on the container so every process in it agrees.
        # (Now the whole folder-env contract, not just the sockets — `_init_shell_prologue` still
        # exports it for the attach shell, but a hook or a `podman exec` never sees that shell.)
        socket_env = [arg for var, val in harnessed_env(
            spec.stack, spec.project_path, harness=spec.harness, mode="container",
            mount_path=self.mount_path,
        ).items() for arg in ("-e", f"{var}={val}")]
        # Same rationale as socket_env: a recipe's setup env belongs to the CONTAINER, not to one exec,
        # so hooks and later execs see what the setup script saw. Resolved here because a `setup.config`
        # item may prompt, which must happen before the container starts.
        self.pending_setups = _pending_setup_scripts(spec.project_path, self.recipes)
        setup_env = [arg for var, val in _container_setup_env(
                         spec.stack, spec.project_path, self.pending_setups,
                         harness=spec.harness).items()
                     for arg in ("-e", f"{var}={val}")]
        # Recipe `env:` — set on the CONTAINER for the third time and the same reason. The image already
        # carries the build-resolvable subset as real ENV (emit.write_derived_dockerfile), but that is
        # not sufficient: a value templated on the PROJECT (`{project_dir}`, an in_repo persist dir) is
        # unknowable at build. Setting the resolved values here makes the running agent's env complete
        # and identical to what the host mode gives it.
        recipe_env = [arg for var, val in _recipe_env(self.recipes, spec.project_path, mode="container").items()
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
        mise_trust_env = ["-e", f"MISE_TRUSTED_CONFIG_PATHS={self.mount_path}"]
        harness_run = [
            self.rt, "run", "-d",
            # No --hostname in the pod branch: a member inherits the pod's UTS namespace, and the pod
            # create above already set it. The pod-less runtime has no infra container to inherit from,
            # so it needs its own bound (same EINVAL, from the container's own name).
            *(["--pod", self.pod] if _rt_uses_pods(self.rt)
              else [f"--network=container:{self.pod}", "--hostname", paths.container_hostname(self.inst)]),
            "--name", self.inst,
            *[arg for f in self.secrets_env_files for arg in ("--env-file", str(f))],
            # ORDER IS PRECEDENCE: podman applies `-e` left-to-right, so the LAST wins. Recipe `env:` goes
            # FIRST — it is catalog-authored and must not be able to clobber harnessed-owned values. That
            # matches host mode, where _launch_host applies _recipe_env to os.environ and THEN overwrites
            # with harnessed_env. Reversing these two silently inverts precedence between modes (caught
            # merging harnessed-0tk.7 and harnessed-8px.2, each of which was self-consistent alone).
            *recipe_env,
            # Long-lived subscription token from the host env (bare `-e NAME` → podman reads the value
            # from its own env, keeping the secret off the command line). No-op when unset or supplied
            # via --env-file above. Withheld from an `isolated_auth` CLAUDE stack: forwarding the
            # HOST's token into a stack that exists to run as someone else is the exact
            # wrong-account failure that flag prevents (see seed_auth). The harness gate matches
            # seed_auth's — omp reads this same variable, so withholding it there would break auth
            # the flag never claimed to touch.
            *([] if self.stk.isolated_auth and spec.harness == "claude"
              else _claude_oauth_token_args(spec.harness, self.secrets_env_files)),
            *socket_env,
            *setup_env,
            *mise_trust_env,
            # Tells the entrypoint whether to start a hub at all. Under `stdio` the harness spawns
            # its own, so a background one here would be a second hub with a second copy of every
            # stdio child — for an OAuth child like mcp-remote, two processes contending for one
            # lockfile and one callback port. Passed always, so the entrypoint never has to infer
            # the default the schema already decided.
            # `none` when every declared server is direct: the entrypoint then starts no hub, and
            # the emitted .mcp.json names none either. One value, read by the emitter, the launcher
            # and the entrypoint, so all three agree on whether a hub exists at all.
            "-e", f"HATAGO_TRANSPORT="
                  f"{self.stk.hub_transport if emit.hub_is_needed(self.servers) else 'none'}",
            *self.member_mounts,
            # Use harnessed-start (baked into base since hatago-consolidation) when present; fall back
            # to plain `sleep infinity` on older images so the launch degrades gracefully rather than
            # hard-failing on a missing binary. Once the base image is rebuilt, the entrypoint runs
            # hatago automatically and this shell one-liner is a no-op (exec replaces it immediately).
            self.harness_image, "bash", "-c",
            "exec /usr/local/bin/harnessed-start 2>/dev/null || exec sleep infinity",
        ]
        try:
            _run(harness_run, capture_output=True)
        finally:
            # Unlink the temp env-files as soon as podman has ingested them into the container's env —
            # resolved secret values must not linger on disk (T-05-06). Always runs (success or failure).
            # Every env-file is a generated temp (the user's own .env is copied, never handed to podman).
            for f in self.secrets_temp_files:
                try:
                    f.unlink()
                except OSError:
                    pass
            self.secrets_temp_files = []


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
    reauth: bool = typer.Option(
        False, "--reauth",
        help="Re-run the browser consent for OAuth MCP servers even when a token already exists "
             "(revoked, wrong account, or a scope change)",
    ),
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
    no_strict_mcp_config: bool = _NO_STRICT_MCP_OPT,
    aoe_group: Optional[str] = _AOE_GROUP_OPT,
    aoe_title: Optional[str] = _AOE_TITLE_OPT,
    last: bool = _LAST_OPT,
    create_aoe_only: bool = typer.Option(
        False, "--create-aoe-only",
        help="Register the Agent of Empires session for this stack and exit without launching. "
             "Requires aoe; validates the stack first, so the row is only created for a launch "
             "that would have worked.",
    ),
) -> None:
    """Run a stack in an isolated container against a project directory (container backend).

        harnessed container-run <harness> [path] --last                 # replay what ran here last
        harnessed container-run <harness> [path]                        # the `default` baseline
        harnessed container-run <harness> [path] --stack <name>
        harnessed container-run <harness> [path] --recipe r1 --recipe r2

    Same grammar as `host-run`; the verb picks the backend and nothing else. The recipe form is
    content-named and mints a real manifest under the generated catalog root, which is what lets
    `harnessed list`, the staleness check and both GCs treat it like any other stack. An identical
    set in another repo resolves to the same stack and shares its image and volumes — that is what
    collapses proliferation rather than relocating it.
    """
    _require_supported_harness(harness)
    if last:
        # See the same branch in `host_run`: the record names an already-resolved stack, so there is
        # nothing minted here and nothing to clean up. `recipe` stays empty, which also keeps the
        # rebuild below off — a replay runs what is already assembled.
        stack, no_strict_mcp_config, aoe_group, aoe_title = _resolve_last(
            "container-run", harness, path, stack, recipe, extends, no_extends, service,
            no_strict_mcp=no_strict_mcp_config, aoe_group=aoe_group, aoe_title=aoe_title,
        )
        minted_dir = None
    else:
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
        raise typer.Exit(1) from exc
    except staleness.StaleProfileError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc} — run: harnessed build {stack} {harness}")
        raise typer.Exit(1) from exc

    # BEFORE the row, for the reason spelled out at the host-run call site: the row's command is
    # `--last`, `_aoe_register` EXITS under `--create-aoe-only`, and a row recorded afterwards
    # would have nothing to replay.
    lastrun.record(
        "container-run", stack, harness, project_path,
        group=aoe_group, title=aoe_title, no_strict_mcp=no_strict_mcp_config,
    )
    # Mirror into Agent of Empires if the user runs it. Placed after every validation above so a
    # launch that is about to fail never leaves a row behind, and before the podman work so the row
    # exists even if the container half goes wrong. No-op when aoe is absent; never raises.
    _aoe_register(
        "container-run", stack, harness, project_path, only=create_aoe_only,
        group=aoe_group, title=aoe_title, no_strict_mcp=no_strict_mcp_config,
    )

    try:
        stk = load_stack(stack_dir)
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1) from exc

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
    # Same check, same reason, other backend — silent today (every container cell is SUPPORTED), and
    # called anyway so a future DEGRADED cell reaches the user without anyone remembering to wire it.
    # BEFORE _prompt_setup_notices: that prompt can block, and a user should not answer it without
    # having seen what this backend will not honor.
    _warn_capability_gaps(ContainerBackend.name, launch_recipes)
    shell = _prompt_setup_notices(launch_recipes, project_path, stack, harness) or shell

    launch_servers = _resolve_service_servers(_merge_servers(launch_recipes), None)

    # THE CONTAINER PATH NEVER ASSEMBLES, so `assemble`'s guard against a `direct:` server on a
    # harness that cannot honour one has never run here — `build` (669) and the host path (2335)
    # both assemble, this one launches a previously-built image and reads the recipes live. An
    # image built before a recipe gained `direct:` therefore reaches launch with servers the
    # harness will never see: they are excluded from hatago.config.json by `direct`, and only
    # claude's MCP config is emitted, so an omp or codex stack would come up silently toolless —
    # and, once every server is direct, with `HATAGO_TRANSPORT=none` stopping the hub as well.
    #
    # Enforcing the same rule here makes that a clear error instead. Raised by CodeRabbit on #381,
    # whose suggested fix was to route direct entries into omp's config; that is the wrong remedy —
    # it would undo the deliberate decision that only claude's MCP config is emitted per stack.
    try:
        _validate_direct_servers(launch_servers, harness)
    except SchemaError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    backend = ContainerBackend(
        rt, inst, pod, prof, harness_image, mount_path, launch_recipes, launch_servers, stk,
        stack_from_overlay=stack_from_overlay,
        headless=os.environ.get("HARNESSED_HEADLESS", "false").lower() == "true",
    )
    spec = LaunchSpec(
        stack=stack, harness=harness, project_path=project_path,
        extra=tuple(_passthrough), no_strict_mcp=no_strict_mcp_config, ephemeral=rm,
    )

    # --fresh: tear down existing pod.
    if fresh:
        _out.print(f"[blue][INFO][/blue] --fresh: tearing down existing pod/instance for {inst}")
        _pod_teardown(rt, inst, pod)
        # Also wipe the persisted agy keyring (antigravity only) so --fresh forces a re-login — the
        # keyring dir deliberately survives a normal recreate, so this is the one place it is cleared.
        _keyring_fresh_wipe(harness, inst)
        # Same contract for an isolated_auth stack's own login (claude): it survives a normal
        # recreate on purpose, so --fresh is the only way back to a logged-out agent. Not gated on
        # the flag — the store exists only for stacks that set it, so this is a no-op otherwise, and
        # leaving it ungated also clears a stale login from a stack that has since turned it off.
        _isolated_auth_fresh_wipe(harness, inst)

    # Idempotent — skips services already running. BEFORE the re-attach branch below, deliberately:
    # see ContainerBackend.wire_services for why.
    backend.wire_services(spec)

    # Same as the host path: the project gets a config of its own, not just the agent we launch.
    _write_project_tool_env(
        stack, project_path, harness=harness, verb="container-run",
        no_strict_mcp=no_strict_mcp_config, aoe_group=aoe_group, aoe_title=aoe_title,
    )

    # Re-attach to a running instance (interactive only) — but if it was built from an older image
    # (rebuilt since it started), a re-attach would silently run the stale build. Offer to recreate.
    headless = backend.headless
    if not headless and _container_running(rt, inst):
        # THE RE-ATTACH PATH NEEDS THIS TOO, and missing it was not a small gap: both branches
        # below `return` straight into `_attach`, so a running instance skipped the consent
        # entirely. That is the likeliest state to need it — an instance that came up, failed to
        # authorize, and is still running is exactly what an operator re-attaches to — and it made
        # `--reauth` silently do nothing whenever the pod happened to be up.
        _authorize_mcp_remote_servers(
            rt, inst, launch_servers, stk, headless=headless, reauth=reauth
        )
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
                _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough, no_strict_mcp=no_strict_mcp_config)
                return
        else:
            _out.print(f"[blue][INFO][/blue] Attaching to running instance: {inst}")
            _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough, no_strict_mcp=no_strict_mcp_config)
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

    required = emit.required_settings(launch_servers, launch_recipes, stk.permissions, harness)
    if harness in ("claude", "omp", "opencode"):
        # Folds the host's live preferences into the assembled PROFILE — a backend-independent
        # artifact, and the last step of assembly rather than a backend operation, which is why
        # both sequencers do it identically before handing off to their backend.
        _merge_host_claude_settings(prof, required, harness)

    # Compose the agent-config volume BEFORE the mounts reference it (bd harnessed-8px.21.2).
    backend.provision_tools(spec, FIRST_START)
    backend.materialize_config(spec)
    backend.seed_auth(spec)
    backend.wire_mcp(spec)
    # Creating the pod is also what delivers the mounts and env across the boundary — see
    # ContainerBackend.apply_isolation.
    backend.apply_isolation(spec, BOUNDARY)

    # Install the corp proxy CA into the container's trust store (no-op when cert absent).
    # Runs before the egress firewall: update-ca-certificates is local-only and needs no network,
    # but placing it here keeps all post-start container setup before the firewall guard.
    _install_corp_proxy_ca_in_container(rt, inst)

    # Recipe setup scripts run here: after the CA is trusted, before the firewall closes egress —
    # a first-run setup is the step most likely to need the network.
    backend.provision_tools(spec, ATTACH)

    backend.apply_isolation(spec, EGRESS)

    # hatago starts automatically via /usr/local/bin/harnessed-start (the container entrypoint).
    # No exec -d needed — the entrypoint script starts it in the background before exec-ing sleep.
    #
    # UNLESS the stack is stdio: then there is deliberately no hub running, because the harness
    # spawns its own on launch. Probing for one would wait out the full timeout and then report a
    # degraded hub — turning correct configuration into a red herring, and (headless) into a hard
    # exit. `harnessed-start` reads the same field, so the two cannot disagree.
    # BEFORE the hub is waited on and before the harness attaches. An OAuth server with no token
    # cannot be fixed later from here: hatago spawns mcp-remote, mcp-remote wants a browser, and the
    # request for one goes to a grandchild's stderr the harness throws away. Asking now — while a
    # human is still watching the launch — is the only point where the URL can reach them.
    _authorize_mcp_remote_servers(
        rt, inst, launch_servers, stk, headless=headless, reauth=reauth
    )

    # No hub is started in either of these cases, so probing for one would wait out the full timeout
    # and then report a degraded hub — turning correct configuration into a red herring, and in
    # headless mode into a hard exit. Under `stdio` the harness spawns the hub at attach; when every
    # server is direct there is no hub anywhere by design.
    if stk.hub_transport == HUB_TRANSPORT_STDIO or not emit.hub_is_needed(launch_servers):
        hatago_up = True
    else:
        hatago_up = _wait_hatago(rt, inst)

    if headless:
        if rm:
            _out.print("[yellow]note:[/yellow] --rm has no effect in headless mode (no interactive session to exit)")
        if not hatago_up:
            # Headless callers (CI / capability tests) have no terminal to notice a degraded hub, so
            # a dead hatago must be a hard failure here, not a green SUCCESS line.
            raise typer.Exit(1)
        # The hub's WHEREABOUTS, not a fixed string: under stdio nothing is running in the container
        # and the harness spawns the hub when it starts. Saying "hatago in-container" there would be
        # a success line asserting something false, and the next person to debug a missing tool
        # would go looking for a process that was never meant to exist.
        if not emit.hub_is_needed(launch_servers):
            hub_where = "no hub — every server is direct"
        elif stk.hub_transport == HUB_TRANSPORT_STDIO:
            hub_where = "hatago spawned by the harness (stdio)"
        else:
            hub_where = "hatago in-container"
        _out.print(f"[green][SUCCESS][/green] Isolated pod running headless: {inst} ({hub_where})")
        return

    _attach(rt, harness, inst, project_path, stack=stack, mount_path=mount_path, ephemeral=rm, pod=pod, start_dir=start_dir, shell=shell, extra=_passthrough, no_strict_mcp=no_strict_mcp_config)


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
    no_strict_mcp: bool = False,
) -> None:
    """Exec into the running instance with the harness command.

    Default: os.execvp hands the TTY to the container natively (clean attach, no post-exit hook).
    ephemeral (--rm): run the exec as a child so the pod can be torn down when the session exits.
    start_dir: working directory for the agent (defaults to project_path; --agent-start-folder).
    shell (--shell): drop into an interactive bash instead of starting the harness.
    extra: passthrough args (from `launch … -- <suffix>`) appended verbatim to the harness command;
    ignored under --shell, which starts no harness.
    no_strict_mcp (--no-strict-mcp-config): drop `--strict-mcp-config` from the claude command so
    claude ALSO reads its own MCP sources — the project's `.mcp.json`, the user config — on top of
    the stack's. Off by default: strict is what keeps a stack's MCP surface exactly what it declares.

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
        strict = "" if no_strict_mcp else " --strict-mcp-config"
        tail = harness_cmd_tpl.format(mcp_cfg=mcp_cfg, instance=inst, strict=strict)
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
        os.execvp(rt, exec_argv)  # noqa: S606 — no shell is the POINT: exec_argv is passed as a vector, so nothing is word-split or glob-expanded

    # Keep this process alive so we can reap the pod once the interactive session exits.
    try:
        # unbounded: the interactive container session — same reasoning as `_launch_host`. The
        # teardown in the `finally` below is the part that must not hang, and it is bounded.
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
    # Streams straight to the terminal, so there is no stdout to guard with `_listing` — but the
    # same lie is available: a failed query prints the heading above and then nothing, which reads
    # as "no instances". Only the return code tells the two apart.
    listed = _bounded([
        rt, "ps", "-a", "--filter", "name=harnessed-",
        "--format", "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}",
    ], timeout=_PODMAN_QUERY_TIMEOUT)
    if listed.returncode != 0:
        _err.print(
            f"[bold red]warning:[/bold red] the instance list above is INCOMPLETE — the container "
            f"runtime exited {listed.returncode}. An empty list here does not mean there are none."
        )


@app.command("stop")
def stop(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Stop every running instance of a stack (all harnesses)."""
    rt = _runtime()
    result = _bounded(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        timeout=_PODMAN_QUERY_TIMEOUT,
        capture_output=True, text=True,
    )
    # Match harnessed-<harness>-<stack>-<hash> — filter for this stack across all harnesses.
    all_names = [n.strip() for n in _listing(result, "instances").splitlines() if n.strip()]
    names = [n for n in all_names if re.search(rf"-{re.escape(stack)}-[0-9a-f]{{8}}$", n)]
    for name in names:
        _out.print(f"[blue][INFO][/blue] Stopping {name}")
        _bounded([rt, "stop", name], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
    if not names:
        _out.print(f"No running instances for stack '{stack}'")


@app.command("rm")
def remove(stack: str = typer.Argument(..., help="Stack name")) -> None:
    """Remove every instance (stopped or running) of a stack (all harnesses)."""
    rt = _runtime()
    result = _bounded(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}"],
        timeout=_PODMAN_QUERY_TIMEOUT,
        capture_output=True, text=True,
    )
    # Match harnessed-<harness>-<stack>-<hash> — filter for this stack across all harnesses.
    all_names = [n.strip() for n in _listing(result, "instances").splitlines() if n.strip()]
    names = [n for n in all_names if re.search(rf"-{re.escape(stack)}-[0-9a-f]{{8}}$", n)]
    for name in names:
        _out.print(f"[blue][INFO][/blue] Removing {name}")
        _bounded([rt, "rm", "-f", name], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
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
    result = _bounded(
        [rt, "ps", "-a", "--filter", "name=harnessed-", "--format", "{{.Names}}\t{{.State}}"],
        timeout=_PODMAN_QUERY_TIMEOUT,
        capture_output=True, text=True,
    )
    # hatago no longer runs as a separate `{inst}-hatago` member (hatago-consolidation), so every
    # `harnessed-` container listed here is a prunable instance. Carry each container's State so
    # non-running ones can be reaped without the (running-only) tty probe.
    members = []
    for line in _listing(result, "instances").splitlines():
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
    if report.unpinnable:
        # Its own section, never folded into `unresolved` (AC-12). These are not failures to
        # check — they are agents we have looked at and conceded cannot be pinned, so they track
        # upstream and move on a rebuild. Saying so here is half of what makes that a stated
        # property rather than a surprise; the agent's own description says the other half.
        _out.print("[bold]Unpinnable (tracks upstream — upgrade by rebuilding):[/bold]")
        for f in report.unpinnable:
            _out.print(f"  {f.pin.recipe}/{f.pin.key} ({f.pin.file.name})\n      [dim]{f.error}[/dim]")


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
    # Both sources are gathered BEFORE the empty check. The recipe-only guard predates agents
    # having pins at all; left in front of the agent scan it would make a catalog of agents and no
    # recipes report nothing — including its unpinnable ones — and keep `--check` green over pins
    # nobody had looked at.
    agent_dirs = _update_agent_dirs()
    if not dirs and not agent_dirs:
        _err.print("[yellow]warning:[/yellow] no recipes or agents found in the active catalog")
        raise typer.Exit(0)

    # Resolve THROUGH the module attribute rather than importing the function, so a test (or a
    # future offline mode) can swap `update.resolve_latest` and have it take effect here.
    report = pinupdate.build_report(
        dirs,
        # A7: agent manifests own their pins too, and used not to be swept at all — which is how
        # three agents reached main with genuinely unpinned downloads.
        agent_dirs=agent_dirs,
        # The base image's extra-tools pins rot exactly like recipe pins do, and used not to be
        # swept at all — which is how bd harnessed-2o9 reached CI.
        extra_tools=pinupdate.extra_tools_default_path(),
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

    # unbounded: the capability suite, which brings containers up and exercises them. The child
    # bounds its own work (capability.DEFAULT_TEST_TIMEOUT per test); a second deadline out here
    # would only cut off a run that is legitimately still going.
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

# The ONLINE archive scan (`harnessed rescan`, fired by a systemd timer). Larger again: it contacts
# osv.dev over the network and `uv run` may resolve a dependency first. Bounded despite that, and
# for a reason the interactive commands do not share — nobody is watching. An unattended hang here
# wedges the timer silently and the nightly re-scan simply stops happening, which looks exactly
# like a nightly that keeps finding nothing (scan.py's Pitfall 6 warning sign).
_SCAN_ONLINE_TIMEOUT = 1800


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
            _bounded(
                [rt, "cp", f"{cid}:{_CONTAINER_HOME_STR}/.harnessed/scan-report.json",
                 str(report_dest)],
                timeout=_PODMAN_WRITE_TIMEOUT,
                capture_output=True,
            )
        # Return means "the scan ran cleanly" — NOT "a report was persisted". `_scan_image` calls
        # this without a report_dest and needs that original meaning; whether a report landed is a
        # separate question the caller answers by looking for the file.
        return res.returncode == 0
    finally:
        if cid:
            _bounded([rt, "rm", "-f", cid], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
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
        res = _bounded(
            ["uv", "run", "--no-project", "--quiet", "--with", "ruamel.yaml",
             "python", "-m", "harnessed.cli", "scan-image-online", tar_path],
            timeout=_SCAN_ONLINE_TIMEOUT,
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
        exists = _bounded(
            [rt, "image", "exists", image], timeout=_PODMAN_QUERY_TIMEOUT, capture_output=True
        )
        if exists.returncode != 0:
            _err.print(
                f"[bold red]error:[/bold red] no such image '{image}' "
                "(build it first, or run `harnessed rescan` to scan every built image)"
            )
            raise typer.Exit(1)
        images = [image]
    else:
        result = _bounded(
            [rt, "images", "--filter", "label=harnessed=true", "--format", "{{.Repository}}:{{.Tag}}"],
            timeout=_PODMAN_QUERY_TIMEOUT,
            capture_output=True, text=True,
        )
        # Especially load-bearing here: `rescan` is what the systemd timer fires, so an unanswered
        # listing would print "nothing to rescan", exit 0, and silently skip the whole nightly
        # vulnerability scan — indistinguishable from a nightly that keeps finding nothing, which is
        # exactly scan.py's Pitfall 6 warning sign.
        images = [i.strip() for i in _listing(result, "images").splitlines() if i.strip()]
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

    for stack, harness, is_orphan, age_days, size_kb, cred_status, legacy, _home in entries:
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
    out = _bounded(
        [rt, "volume", "ls", "--filter", f"label={_VOL_LABEL}",
         "--format", "{{.Name}}\t{{.Labels}}"],
        timeout=_PODMAN_QUERY_TIMEOUT,
        capture_output=True, text=True,
    )
    rows: list[tuple[str, str, str, str, bool]] = []
    for line in _listing(out, "volumes").splitlines():
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
        _bounded([rt, "volume", "rm", "-f", name], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
    if not dry_run:
        _out.print(f"[green][SUCCESS][/green] Removed {len(orphans)} orphan volume(s)")


@app.command("svc")
def svc(
    action: str = typer.Argument(..., help=" | ".join(_SVC_ACTIONS)),
    name: str = typer.Argument(..., help="Service name (services/<name>/service.yaml)"),
    stack: str = typer.Option(
        "", "--stack",
        help="Stack context (required for scope: project; recreate reads it off the container)",
    ),
) -> None:
    """Manage a service sidecar (build+start, stop+remove, recreate, or sync).

    `up`/`down`/`recreate` on a `scope: project` service act on THIS project's container
    (git-common-dir keyed), so they need `--stack` to resolve which persist entry holds the data.
    `recreate` is the exception: it rebuilds the container that is already here, so from inside the
    project it takes no flags at all. It reads the stack back off that container
    (`harnessed.svc-stack`) and, for a container predating that label, off the agent instance
    running for this repo. Pass `--stack` only to override, or when neither source exists.

    `recreate` TEARS DOWN and REBUILDS the container — it is not `podman restart`, and deliberately
    is not named that. Mounts, published ports and env are fixed when a container is CREATED, so a
    restart reuses the existing one and reports success while changing nothing. Recreating is the
    only way a running sidecar picks up a change to how harnessed builds it. Data (the bind-mounted
    or named-volume /data) is untouched.

    `sync` execs the service's own sync command in its container. It exists for a server whose git
    sync shells out to a CLI that only routes to a server on its OWN loopback — so the push can only
    run inside the service container, never in an agent container. Sync pushes to your git remote,
    so it is explicit, never automatic.
    """
    rt = _runtime()
    project_path = Path.cwd().resolve()
    # BEFORE the scope/stack guard below, which interpolates `action` into the command it suggests:
    # reaching that guard first answers `svc restart <name>` with "pass --stack ... e.g.
    # harnessed svc restart <name> --stack my-stack", sending the user to a second failure
    # instead of the real one. `restart` is exactly the wrong verb someone will try here.
    if action not in _SVC_ACTIONS:
        _err.print(
            f"[bold red]error:[/bold red] unknown svc action '{action}' "
            f"(use: {' | '.join(_SVC_ACTIONS)})"
        )
        raise typer.Exit(1)
    svc_def = load_service(None, name)
    key = _svc_project_key(svc_def, project_path)
    cname = _svc_container(name, key)

    if svc_def.scope == "project" and not stack and action == "recreate":
        # Recreating rebuilds the sidecar THAT IS HERE, and that container already records the stack
        # it was built from (_SVC_STACK_LABEL). Making the user re-supply it would be asking for
        # something the machine knows — and inviting a typo that silently rebuilds against a
        # different persist entry, i.e. a different data dir.
        stack = _svc_container_stack(rt, cname) or ""
        if not stack:
            # No label: the container predates it, which is true of EVERY sidecar on any machine
            # running this for the first time. Fall back to the agent instances for this repo, so
            # the first recreate — the one that fixes a container built before some fix landed —
            # does not demand a flag. Recreating stamps the label, so this runs at most once.
            candidates = _svc_stacks_from_instances(rt, project_path)
            if len(candidates) == 1:
                stack = candidates[0]
                _out.print(
                    f"[blue][INFO][/blue] Using stack '{stack}' — from the agent instance running "
                    f"for this repo ({cname} predates the {_SVC_STACK_LABEL} label)."
                )
            elif len(candidates) > 1:
                _err.print(
                    f"[bold red]error:[/bold red] this repo has instances for more than one stack "
                    f"({', '.join(candidates)}) and {cname} predates the {_SVC_STACK_LABEL} label, "
                    "so which one owns the sidecar cannot be told from here — pass --stack."
                )
                raise typer.Exit(1)
    if svc_def.scope == "project" and not stack:
        _err.print(
            f"[bold red]error:[/bold red] service '{name}' is scope: project — pass --stack so its "
            f"data dir can be resolved (e.g. harnessed svc {action} {name} --stack my-stack)"
        )
        if action == "recreate":
            # Reached only when BOTH sources came up empty: no label on the container, and no agent
            # instance for any worktree of this repo to read a stack off.
            _err.print(
                f"  ({cname} carries no {_SVC_STACK_LABEL} label and this repo has no agent "
                "instance to infer from. After one run with --stack, recreate needs no flag here "
                "again.)"
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
        _bounded([rt, "rm", "-f", cname], timeout=_PODMAN_WRITE_TIMEOUT, capture_output=True)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' is down ({cname})")
    elif action == "sync":
        sync_cmd = (svc_def.raw.get("sync") or "").strip()
        if not sync_cmd:
            _err.print(f"[bold red]error:[/bold red] service '{name}' declares no `sync:` command")
            raise typer.Exit(1)
        if not _container_running(rt, cname):
            _err.print(f"[bold red]error:[/bold red] service '{name}' is not running ({cname})")
            raise typer.Exit(1)
        # unbounded: a catalog-authored `sync:` is arbitrary work the user explicitly asked for and
        # is watching — a database import legitimately runs for many minutes. Ctrl-C is the control.
        result = subprocess.run([rt, "exec", cname, "bash", "-lc", sync_cmd])
        if result.returncode != 0:
            _err.print(f"[bold red]error:[/bold red] sync failed for service '{name}'")
            raise typer.Exit(result.returncode)
        _out.print(f"[green][SUCCESS][/green] Service '{name}' synced")


@app.command("project-env-path")
def project_env_path_cmd(
    path: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)"),
) -> None:
    """Print where this project's tool-env dotenv lives.

    A launch already gives the agent it starts this env. This is for the OTHER audience — a `bd`
    you run in a terminal, a `claude` you started yourself, a hook — which harnessed does not
    configure and never has. Wiring that up is OPT-IN and yours to choose (bd harnessed-7mt);
    harnessed writes nothing into your repo and nothing into your shell or mise config.

    REFERENCE THIS FILE, NEVER COPY IT. It holds real service credentials and is regenerated on
    every launch, so a copy is both a secret replicated into wherever you put it and a value that
    goes stale at the next container recreate. Run this command IN the project and quote the result:

        direnv, per project (.envrc):   dotenv "$(harnessed project-env-path)"
        a shell function, on demand:    set -a; . "$(harnessed project-env-path)"; set +a

    Both forms invoke this command from inside the directory it is asking about, so the path never
    passes through a shell as text.

    NOT DOCUMENTED, DELIBERATELY: mise's `[env] _.file` with
    `{{ exec(command='harnessed project-env-path ' ~ cwd) }}`. mise runs `exec()` relative to the
    CONFIG file's directory rather than yours, so the only way to make one global line
    per-project is to concatenate `cwd` into a string that mise hands to a shell — and tera's `~`
    is string concatenation, not argv construction. VERIFIED on mise 2026.8.2: from a directory
    literally named `$(echo INJECTED)`, the substitution ran. A cloned repo or extracted archive
    carrying a crafted directory name would execute code on `cd` alone. Double quotes do not help
    (`$(...)` expands inside them in sh) and tera has no shell-quoting filter. That is the same
    class of hazard `mise.local.toml` was retired for (bd harnessed-7mt); replacing it with a
    worse one would be a poor trade.

    Prints the path whether or not it exists, so a directory that was never launched in is not an
    error — direnv tolerates a missing env file silently.
    """
    # PRINT NOTHING ON A FAILED LOOKUP, and exit non-zero. The caller is a shell substitution in
    # someone's env loader, so a path printed here is used without question — and a fallback path
    # computed after a failed git lookup is a plausible-looking wrong answer that loads no env and
    # explains nothing. Empty stdout makes the loader load nothing too, but the message on stderr
    # says why (bd harnessed-654).
    try:
        env_path = setupenv_project_env_path(Path(path).resolve() if path else Path.cwd())
    except paths.GitLookupFailed as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    # BUILTIN print, NOT `_out.print`. This output is consumed as a filename by mise, and the rich
    # console mangles it two ways: it hard-wraps at the terminal width, so a path longer than the
    # window comes back with a newline in the middle of it, and it reads `[...]` as markup, so a
    # path containing a bracket loses the bracketed span. Both fail SILENTLY — mise tolerates a
    # missing `_.file`, so the project env would simply never load and nothing would say why.
    print(env_path)


@app.command("aws-sso")
def aws_sso(
    action: str = typer.Argument("serve", help="serve — run the aws-sso ECS credential server for containers"),
    port: int = typer.Option(AWS_SSO_ECS_PORT, "--port", help="port the ECS server listens on"),
    bind_ip: str = typer.Option(
        "0.0.0.0",  # noqa: S104 — deliberate and user-overridable: containers reach the ECS server via host.containers.internal, which 127.0.0.1 does not answer. The listener is gated by a bearer token, and --bind-ip 127.0.0.1 turns it host-only.
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
        # unbounded: interactive — this prompts for credentials and waits for the human at the
        # keyboard. A deadline here fails the setup of anyone who pauses to find their phone.
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
        # unbounded: a foreground daemon. The message above literally says "leave this running.
        # Ctrl-C to stop" — running until interrupted is the feature, not a hang.
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
