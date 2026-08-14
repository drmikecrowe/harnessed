"""Run a recipe`s tools, installs, inits and setups for a HOST-NATIVE launch.

The container path runs these inside the image; host mode has no image, so it runs them directly
against the per-stack home — through mise shims, with the harness config dir pointed at that home.
The env they run with is derived by setupenv.py, shared with the container path so the two modes
cannot drift.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

from pathlib import Path
from typing import MutableMapping, Optional

import typer

from . import capability
from . import emit
from . import paths, toollock
from .assemble import _merge_servers
from .hosthome import _relink
from .schema import load_stack_with_recipes
from .console import _err
from .proc import _say
from .setupenv import (
    _confirm_setup,
    _recipe_env,
    _repo_primitives,
    _resolve_setup_config,
    _script_env,
    _stack_tools_dirs,
    harnessed_env,
)

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

    MISE_STATE_DIR IS DELIBERATELY NOT REDIRECTED. mise keeps its TRUST STORE in the state dir, and
    trust is a fact about the user and a config FILE — never about which stack happens to be
    running. Redirecting it gave every stack an empty trust store, so every project `mise.toml` the
    user had already trusted read as untrusted inside every harnessed session, and each new stack
    (or a rebuilt tools dir) re-broke one the user had just repaired. mise reports that as

        mise ERROR error parsing config file: <path>

    which reads as a TOML syntax error and is not one — the real reason is on the NEXT line. The
    file is then not loaded at all, so a project whose `[env]` carries e.g. `BEADS_DIR` comes up
    unconfigured for reasons nothing on screen explains.

    The state dir holds `trusted-configs` and `tracked-configs` and nothing else. Neither is
    stack-scoped, so sharing the user's costs no isolation: the stack's own `config.toml` lives
    under MISE_CONFIG_DIR and is trusted implicitly for being there — verified against mise
    2026.8.2 with this exact split.

    NOT fixed by auto-trusting instead. Harnessed NAMING a path in `MISE_TRUSTED_CONFIG_PATHS` (what
    the container path does, where the only config present is the one we put there) would grant
    trust the user never granted, and a mise config can carry `_.source` — so that is code
    execution. Keeping the user's own store means harnessed grants no trust at all and simply stops
    discarding theirs.

    The distinction is INVENTING versus CARRYING, not the variable. `_apply_host_mise_env` does set
    MISE_TRUSTED_CONFIG_PATHS on a host launch (bd harnessed-67u) — from entries read out of the
    user's OWN config, which the MISE_CONFIG_DIR redirect below would otherwise hide from them.
    Every entry there traces to the user or to the environment we were handed; harnessed still names
    none of its own, which is what this paragraph forbids.
    """
    mise_root = _stack_tools_dirs(stack)[0] / "mise"
    return {
        "MISE_DATA_DIR": str(mise_root),
        "MISE_CONFIG_DIR": str(mise_root / "config"),
    }


def _is_a_harnessed_stack_state_dir(value: str) -> bool:
    """Whether `value` is a MISE_STATE_DIR a PREVIOUS harnessed release exported.

    `<xdg_data_home>/harnessed/tools/<stack>/mise/state` — the shape `_host_mise_env` used to
    return, for ANY stack. The stack name is matched as "one path segment", not against a list:
    the value we have to recognise belongs to the OUTER session, whose stack this process has no
    way to know.

    NARROW ON PURPOSE. `MISE_STATE_DIR` is an ordinary mise variable a user may set for their own
    reasons, and blanket-removing it would drop them onto mise's default state dir — a DIFFERENT
    trust store than the one they chose. That is precisely the bug this module now exists to
    prevent, aimed at a different victim, so only the value we ourselves wrote is eligible.
    """
    return _is_a_harnessed_stack_dir(value, "state")


def _is_a_harnessed_stack_dir(value: str, tail: str) -> bool:
    """Whether `value` is `<xdg_data_home>/harnessed/tools/<stack>/mise/<tail>` — a dir WE wrote.

    RESOLVED ON BOTH SIDES, not compared as text. A purely lexical check reads a symlink pointing
    into a stack's own dir as "not harnessed's", which let an inherited MISE_CONFIG_DIR launder that
    stack's `trusted_config_paths` into the next launch as though the user had chosen them — an
    over-grant, and `trusted_config_paths` decides which configs mise will EXECUTE via `_.source`.
    Found by adversarial review. Resolving both sides also keeps the comparison honest where the
    data dir itself sits behind a symlink, which is why the base is resolved too rather than only
    the candidate.

    The stack name stays "one path segment" rather than a known list: the value belongs to the OUTER
    session, whose stack this process has no way to name.

    EMPTY IS NEVER OURS, and it has to be rejected before the resolve: callers pass
    `env.get(VAR, "")`, so an UNSET variable arrives here as `""` — and `Path("").resolve()` is the
    CWD, which under a process sitting in a stack's own dir made an absent variable match. The
    invariant is "only a value harnessed itself wrote is eligible"; nobody wrote an absent one.
    """
    if not value:
        return False
    try:
        relative = Path(value).resolve().relative_to(
            (paths.xdg_data_home() / "harnessed" / "tools").resolve()
        )
    except (ValueError, TypeError, OSError, RuntimeError):
        return False
    return relative.parts[1:] == ("mise", tail)


# mise splits MISE_TRUSTED_CONFIG_PATHS on THIS and nothing else — verified against 2026.8.3, where
# a comma-joined value is read as one (nonexistent) path and every config reads untrusted.
_TRUSTED_PATHS_DELIMITER = ":"


def _is_a_harnessed_stack_config_dir(value: str) -> bool:
    """Whether `value` is a MISE_CONFIG_DIR harnessed itself exported — `_host_mise_env`'s shape.

    The `_is_a_harnessed_stack_state_dir` predicate with a `config` tail, and it exists for the same
    inheritance trap: launching a stack from inside another stack's host session is routine, so the
    MISE_CONFIG_DIR already in the environment is frequently the OUTER STACK's, not the user's.
    Reading that one as "the user's config" would propagate stack-level trust as though the user had
    chosen it — an over-grant, which is the one failure this whole path exists to avoid.
    """
    return _is_a_harnessed_stack_dir(value, "config")


def _user_mise_config_file(env: MutableMapping[str, str]) -> Path:
    """The global mise config the user would read WITHOUT our redirect.

    Their own MISE_CONFIG_DIR is honoured — it is their choice, same narrowness rule the state-dir
    removal follows. Only a value matching our own shape is disregarded.

    RESOLVED FROM `env`, not from the process. This function's whole subject is the environment it
    was handed, so reading XDG_CONFIG_HOME off `os.environ` instead lets the env being BUILT and the
    config being CONSULTED disagree. The two coincide for both production callers, which is exactly
    why no unit test could see it — the real-execution check handed the constructed env to a live
    mise and got a different user's config back.
    """
    configured = env.get("MISE_CONFIG_DIR", "")
    if configured and not _is_a_harnessed_stack_config_dir(configured):
        return Path(configured) / "config.toml"
    xdg = env.get("XDG_CONFIG_HOME", "")
    return (Path(xdg) if xdg else paths.xdg_config_home()) / "mise" / "config.toml"


def _user_trusted_config_paths(env: MutableMapping[str, str]) -> list[str]:
    """The `trusted_config_paths` the USER set, or `[]` — never an error, never a guess.

    FAILS CLOSED on everything: no file, unreadable file, malformed TOML, wrong type, junk entries.
    A config harnessed cannot read grants nothing, and never aborts the launch it is only reading
    for. An entry containing the delimiter is dropped rather than emitted, because joining it would
    hand mise two paths the user never wrote.
    """
    try:
        parsed = tomllib.loads(_user_mise_config_file(env).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    settings = parsed.get("settings")
    configured = settings.get("trusted_config_paths") if isinstance(settings, dict) else None
    if not isinstance(configured, list):
        return []
    return [
        entry for entry in configured
        if isinstance(entry, str) and entry and _TRUSTED_PATHS_DELIMITER not in entry
    ]


def _apply_host_mise_env(env: MutableMapping[str, str], stack: str) -> None:
    """Put `_host_mise_env` onto `env` and clear what a previous release left behind.

    One function so install time and run time cannot drift: they redirect the same instance, and a
    variable cleared on one side only is the same broken-shim class `_host_mise_env` guards against.

    MISE_STATE_DIR has to be actively REMOVED, not merely no longer set. Both consumers merge over
    an inherited environment, and launching one stack from inside another stack's host session is
    routine — so a stale value from the outer session would survive the merge and keep the empty
    trust store alive in the inner one. Same shape as the CLAUDE_CONFIG_DIR inheritance trap
    documented further down this module. Only OUR value is removed; see the predicate.

    MISE_TRUSTED_CONFIG_PATHS is the same argument reaching the SETTINGS the redirect also hides
    (bd harnessed-67u). mise's global config file IS `$MISE_CONFIG_DIR/config.toml`, so pointing
    that dir at the stack discards the user's `trusted_config_paths` along with the tool list the
    redirect exists to isolate — and that setting is the only one that survives a new git worktree,
    since the trust STORE is keyed per config file while this is a path PREFIX.

    Carrying it is NOT harnessed granting trust, the thing `_host_mise_env` is careful never to do:
    every entry comes from the user's own config or from the environment we were handed.

    Read BEFORE the redirect lands — but NOT because reading late would over-grant. Read late,
    MISE_CONFIG_DIR is the stack's own dir, which `_is_a_harnessed_stack_config_dir` recognises and
    skips, so it falls back to the XDG config and still reads the user's. What breaks is the user
    who set their OWN MISE_CONFIG_DIR: the redirect has already replaced it, so the config dir they
    chose is silently passed over for the default. The ordering protects THEM.

    Measured, not reasoned: moving `env.update` above the loop fails exactly one test,
    `test_a_user_chosen_config_dir_is_honoured`, and the over-grant test
    `test_an_inherited_stack_config_dir_is_not_treated_as_the_users` still passes.

    INHERITED ENTRIES ARE DEDUPED TOO, not just the user's. Seeding the list from the inherited
    value unfiltered let a duplicate already present there survive every later launch — stable, so
    the merge stayed idempotent, but "each path once" is the property, and a property that holds for
    one source and not the other is the one a reader will assume holds for both.
    """
    if _is_a_harnessed_stack_state_dir(env.get("MISE_STATE_DIR", "")):
        del env["MISE_STATE_DIR"]
    inherited = env.get("MISE_TRUSTED_CONFIG_PATHS", "").split(_TRUSTED_PATHS_DELIMITER)
    trusted: list[str] = []
    for entry in (*inherited, *_user_trusted_config_paths(env)):
        if entry and entry not in trusted:
            trusted.append(entry)
    env.update(_host_mise_env(stack))
    if trusted:
        env["MISE_TRUSTED_CONFIG_PATHS"] = _TRUSTED_PATHS_DELIMITER.join(trusted)


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
    # After the splat, because it CLEARS as well as sets: an inherited MISE_STATE_DIR has to lose to
    # the removal, not be reinstated by `**os.environ`.
    _apply_host_mise_env(env, stack)
    # Per-recipe checksums, merged into the one lockfile mise reads (NC-7). Written BEFORE the
    # install, into the same redirected config dir `mise use -g` writes — mise enforces
    # `$MISE_CONFIG_DIR/mise.lock` and ignores every other spelling, which is measured in
    # toollock's module docstring. An empty body REMOVES a stale file rather than leaving it to
    # verify a tool set this stack no longer has.
    # A conflict here is a recipe-AUTHORING mistake — two recipes locking one spec to different
    # bytes — and it is the single thing this mechanism exists to surface. Reported the way every
    # other failure in this path is, because a traceback buries the message that names both
    # recipes. Raised in review of PR #342, after confirming nothing above catches it.
    try:
        body = toollock.stack_lock_body(recipes)
    except toollock.ToolLockError as exc:
        _err.print(f"[bold red]error:[/bold red] tools: {exc}")
        raise typer.Exit(1) from exc
    lock = toollock.write_stack_lock(Path(env["MISE_CONFIG_DIR"]), body)
    if lock is not None:
        _err.print(f"[blue][INFO][/blue] tools: verifying checksums from {lock}")
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
        if inst is None:  # filtered above, but narrow for type checker
            continue
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
        # THIS recipe's tests, before the next recipe installs. Per-recipe interleaving, not
        # install-all-then-test-all: a test asserts what its own install produced, and a later
        # recipe must not install onto a stack that has already failed. Same env as the install
        # above — one contract, so a host/container drift is not expressible here.
        tests = capability.discover_recipe_tests([recipe])
        if tests:
            _err.print(
                f"[blue][INFO][/blue] tests ({recipe.name}): {len(tests)} script(s) (host)"
            )
            # Timeout read at CALL time, not bound as a default: a def-time default cannot be
            # varied, which would make the "a hung test does not wedge every launch" guarantee
            # untestable. Same constant the container seam passes — one authority, both modes.
            failed = capability.first_failed_test(
                capability.run_recipe_tests_host(
                    tests, env=env, workdir=project_path,
                    timeout=capability.DEFAULT_TEST_TIMEOUT,
                )
            )
            if failed is not None:
                _err.print(
                    f"[bold red]error:[/bold red] recipe test failed for '{recipe.name}': "
                    f"{failed.name} — {failed.detail}"
                )
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
    """Run each recipe's `setup.script` host-side — the host half of the both-mode executable setup.

    `condition` is deliberately not consulted (see `_pending_setup_scripts`): a script is idempotent
    and self-gating by contract, so it runs every launch and converges. The container half is
    `_run_container_setups`, and both are reached through the same contract operation,
    `provision_tools(ATTACH)`.

    This REPLACES per-launch daemon management: for beads the script runs `bd init --shared-server …`
    and bd itself auto-manages the shared dolt server — harnessed only supplies the project identity
    (unique database, chosen prefix)."""
    _, recipes = load_stack_with_recipes(None, stack)
    _, bin_dir, uv_tool_dir = _stack_tools_dirs(stack)
    # Same containment as the install path (bd harnessed-8px.26): a setup script is catalog-authored
    # content too, so an inherited CLAUDE_CONFIG_DIR would redirect its writes just as readily.
    cfg_env = _harness_config_env(harness, paths.host_home(stack, harness))
    primitives: dict[str, str] | None = None
    for recipe in recipes:
        setup = recipe.setup
        if not (setup and setup.script):
            continue
        # Before `config` resolution, which may prompt: asking for values the user is about to
        # decline to use is backwards.
        if not _confirm_setup(recipe, stack, project_path, harness=harness):
            continue
        if primitives is None:
            primitives = _repo_primitives(project_path)
        values = _resolve_setup_config(setup, primitives, interactive=sys.stdin.isatty())
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
