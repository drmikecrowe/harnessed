"""Compose the environment and file surface a recipe`s setup/install scripts run against.

A recipe can declare `setup:`, `install:` and `init:` scripts plus `env:`. Everything those need in
order to run — the substituted config values, the derived project primitives, the env map, the
mount list, the `.mise.local.toml` task block, the project tool-env file — is derived here from the
stack, its recipes and the project path.

Shared by both launch modes: the container path hands these to podman, the host path (hostrun.py)
applies them in-process. That is exactly why they live in one module instead of one per mode.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

from pathlib import Path
from typing import Optional

import typer

from . import aoe
from . import emit
from . import paths
from rich.markup import escape

from .console import _err, _out
from .layout import _harnessed_dir
from .paths import CONTAINER_HOME
from .proc import _say
from .schema import HARNESS_CONFIG_DIR, load_stack_with_recipes, resolve_recipe_env
from .svcstate import svc_client_env, svc_socket_env

_CONTAINER_HOME_STR = str(CONTAINER_HOME)

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


# The comment that marks a `[tasks.<harness>]` table as OURS to regenerate. Ownership has to be
# per-table, not per-file: the file as a whole is shared with the user the moment they add a task of
# their own, and `_MISE_MARKER` at the top of it says nothing about who wrote the table at line 40.
_MISE_TASK_MARKER = f"{_MISE_MARKER} — regenerated every launch; rename the task to make it yours."


def _mise_task_block(harness: str, stack: str, verb: str, command: str) -> str:
    """One `[tasks.<harness>]` table, marked as ours, ending in a newline.

    Named for the HARNESS alone — `mise run claude`, `mise run omp` — because that is the thing a
    user types from muscle memory. The consequence is that a project's last launch of a given
    harness owns that task name: launching a second stack with claude rewrites `[tasks.claude]`
    rather than adding a second table. That is the same last-launch-wins rule the env file next to
    it already follows, and the description records which stack the current one replays.
    """
    # ensure_ascii=False — TOML is UTF-8 by definition, and the default would render the em dash
    # (and any non-ASCII in a project path) as a `\uXXXX` escape nobody wants to read.
    return (
        f"\n{_MISE_TASK_MARKER}\n"
        f"[tasks.{harness}]\n"
        f"description = {json.dumps(f'harnessed {verb} — {stack}', ensure_ascii=False)}\n"
        f"run = {json.dumps(command, ensure_ascii=False)}\n"
    )


def _upsert_mise_task(mise_local: Path, harness: str, block: str) -> bool:
    """Add or refresh our `[tasks.<harness>]` table in place. True when the file changed.

    Only ever called on a file we own (see `_write_project_tool_env`). Appending `[tasks.claude]` at
    EOF is valid TOML — a table header closes whatever table preceded it — so this appends when the
    table is absent and rewrites in place when it is ours.

    "Ours" is the marker comment on the line directly above the header. A user who deletes that
    comment, or writes their own `[tasks.claude]` into our file, has taken the name — we never touch
    it again and never silently lose their `run` line to a relaunch. Renaming the task is therefore
    the documented way to take ownership of one.
    """
    text = mise_local.read_text(encoding="utf-8")
    header = f"[tasks.{harness}]"
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)

    if start is None:
        mise_local.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8")
        return True
    if start == 0 or _MISE_TASK_MARKER not in lines[start - 1]:
        return False

    # Our block runs from the marker to the next table header. Ours never contains a multi-line
    # array, so "a line starting with `[` at column 0" cannot be anything but the next table.
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines)
    )
    rebuilt = "".join(lines[: start - 1]) + block.lstrip("\n") + "".join(lines[end:])
    if rebuilt == text:
        return False
    mise_local.write_text(rebuilt, encoding="utf-8")
    return True


def _write_project_tool_env(
    stack: str, project_path: Path, *, harness: str, verb: str,
    no_strict_mcp: bool = False, aoe_group: Optional[str] = None, aoe_title: Optional[str] = None,
) -> None:
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
      * `mise.local.toml` in the repo holds NO VALUES — only a POINTER to that dotenv
        (`[env] _.file`) and the launch task below. mise loads it for any process whose CWD is under
        the project, which is exactly the audience that was missing.
      * a `[tasks.<harness>]` table, so `mise run claude` in this repo replays THIS launch. The
        `run` line is `aoe.command_for` verbatim — the same string the dashboard row records —
        because a launcher that drifts from the row purporting to restart it is worse than no
        shortcut at all. It carries every flag that shapes the session (`--stack`,
        `--no-strict-mcp-config`, `--aoe-group`, `--aoe-title`) and, like the row, omits the
        per-invocation lifecycle flags (`--fresh`, `--rm`) that are yours to re-decide each time.

    NEVER WRITES A FILE THAT IS NOT OURS. A `mise.local.toml` without our marker comment is the
    user's: we print what to add and change nothing. Silently reformatting someone's config — TOML
    round-trips lose comments and ordering, and a second `[env]` table is a parse error outright —
    is a worse bug than the one this fixes. Inside a file we DO own, the task table may be refreshed
    (see `_upsert_mise_task`), because a launch flag that changed has to reach the shortcut that
    claims to replay the launch; the user can still claim the name by renaming the task.

    Requires every value to be stable — a `publish: ephemeral` port would be written down and be
    wrong after the next container recreate, which is why beads-server is `publish: stable`.
    """
    _, recipes = load_stack_with_recipes(None, stack)
    values = {
        **_recipe_env(recipes, project_path, mode="host"),
        **svc_client_env(stack, project_path, "host"),
    }

    env_file = None
    if values:
        gcd = paths.git_common_dir(project_path)
        env_file = (
            paths.xdg_state_home() / "harnessed" / "project-env"
            / f"{paths.project_hash(gcd or project_path)}.env"
        )
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.parent.chmod(0o700)
        body = "".join(f"{k}={v}\n" for k, v in sorted(values.items()))
        env_file.write_text(
            f"# {_MISE_MARKER} — regenerated every launch. Do not edit.\n{body}", "utf-8"
        )
        env_file.chmod(0o600)

    mise_local = project_path / "mise.local.toml"
    if not mise_local.exists():
        mise_local.write_text(
            f"{_MISE_MARKER}: this file is NOT committed (see .gitignore). It points mise at the\n"
            f"# tool env for this project, so `bd` and friends work in a plain terminal too, and\n"
            f"# gives you `mise run <harness>` to start this stack again.\n",
            encoding="utf-8",
        )
        _say(f"[blue][INFO][/blue] wrote {mise_local.name} — `bd` now works in a plain shell here")

    text = mise_local.read_text(encoding="utf-8")
    if env_file is not None and str(env_file) not in text:
        pointer = f'[env]\n_.file = "{env_file}"\n'
        # Appending `[env]` is safe here and only here: a file carrying our marker has no `[env]` of
        # its own yet (this is the only code that adds one), and a file that is not ours we do not
        # touch at all. The reachable case is a project whose first launch had no tool env to write.
        if _MISE_MARKER in text:
            mise_local.write_text(text.rstrip("\n") + "\n" + pointer, encoding="utf-8")
        else:
            _say(
                f"[blue][INFO][/blue] {mise_local.name} exists and is yours to edit; to configure "
                f"this project's tools for a plain shell, add:\n    {pointer.rstrip()}"
            )

    command = aoe.command_for(
        verb, stack, harness, Path(project_path).resolve(),
        group=aoe_group, title=aoe_title, no_strict_mcp=no_strict_mcp,
    )
    block = _mise_task_block(harness, stack, verb, command)
    if _MISE_MARKER not in mise_local.read_text(encoding="utf-8"):
        # Someone else's file. Same rule as the pointer above: we offer, we do not edit. Appending a
        # table would be TOML-safe, but "harnessed does not write your mise config" is a guarantee
        # worth more than the convenience, and a task named for a harness is exactly the name they
        # are most likely to want for something of their own.
        # escape() — a TOML table header is `[tasks.claude]`, which rich reads as markup and eats,
        # printing an instruction with the one line the user has to copy missing from it.
        _say(
            f"[blue][INFO][/blue] to get `mise run {harness}` for this stack, add to "
            f"{mise_local.name}:\n{escape(block.strip())}"
        )
    elif _upsert_mise_task(mise_local, harness, block):
        _say(f"[blue][INFO][/blue] `mise run {harness}` in this repo now starts {stack}")
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
