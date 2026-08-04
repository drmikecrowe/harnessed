"""`launch` and `host-run` must stay in step on everything derived from the STACK.

Five separate capabilities were implemented in the container launch path and silently skipped in
`_launch_host`. Each surfaced as a different symptom, and every one was found by a person hitting it
rather than by a test:

  harnessed-2sm  sidecars       `_ensure_services` was called from `launch` only
  harnessed-162  socket env     `svc_socket_env` was gated on `mode == "container"`
  harnessed-5ek  agent path     `_service_data_dir` returned the CONTAINER path for `location: host`
  (unnumbered)   recipe `init:` ran only from `_init_shell_prologue`, the attach shell
  (unnumbered)   setup notices  `_prompt_setup_notices` was called from `launch` only

Five is a pattern, not five accidents. A host launch reads the same stack, the same recipes and the
same services as a container launch, so anything derived from those should either apply in both
modes or be a written-down exception.

This is a LINT, not a semantic guarantee, and the distinction matters when reading a failure:
  * It catches ABSENCE — a helper called on one path and not the other. harnessed-2sm and -162 would
    both have failed this test.
  * It cannot catch WRONGNESS — harnessed-5ek called the right helper and got the wrong value back,
    and this test would have passed throughout.

The structural fix (one shared stack-semantics routine that both verbs call, so parity cannot be
forgotten rather than merely being tested) is tracked separately — see harnessed-w3g.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from harnessed import launcher
from harnessed.backend import ExecutionBackend

# Container-only by NATURE, with the reason each cannot apply to a host-native launch. Grouped by
# why, because the reason is the part a future reader needs — a bare list of 39 names would just be
# re-derived from scratch every time this test fails.
#
# Adding a call to `launch` that is not here fails the test. That is the point: the author must
# either wire it into `_launch_host` too, or write down why it cannot be.
CONTAINER_ONLY: dict[str, str] = {
    # --- image + container lifecycle: there is no image and no container on the host ---
    "_agent_image": "names a container image",
    "_derived_image": "names a container image",
    "_ensure_harness_image": "builds a container image",
    "_image_exists": "inspects the image store",
    "_container_running": "inspects a container",
    "_container_stale": "inspects a container",
    "_stopped_leftover": "removes a dead container",
    "_pod_teardown": "tears down a pod",
    "_rt_uses_pods": "asks the container runtime about pods",
    "_run": "shells out to podman/docker",
    "_attach": "attaches to a container's TTY; the host execs the harness directly",
    # --- bind mounts: the host already has these paths, so there is nothing to map in ---
    "_build_mount_args": "bind mounts",
    "_persist_mounts": "bind mounts; on the host a persist entry IS its real path",
    "_setup_script_mounts": "bind mounts; host setups read the catalog dir directly",
    "_ccstatusline_settings_mount": "bind mount",
    "_claude_config_seed_mount": "seeds config INTO a container; the host uses its own ~/.claude",
    "_claude_creds_seed_mount": "seeds credentials INTO a container; the host already has them",
    "_keyring_state_mount": "bind mount",
    "_keyring_fresh_wipe": "resets container-side keyring state",
    # `isolated_auth` (a stack running as a DIFFERENT Claude account) is container-only for now, by
    # decision rather than by nature — a host-native launch COULD hold a second identity, but not
    # this way: _materialize_host_home rmtree's the per-stack home on every launch, so the store
    # would need a home outside it plus its own rescue path, and host mode's auth is a symlink to
    # the user's live store rather than a mount that can be swapped. Tracked separately; the host
    # backend is deliberately the maintained-secondary that gets no new investment.
    "_claude_isolated_auth_mount": "bind mounts a per-instance credentials file over the config volume",
    "_isolated_auth_fresh_wipe": "resets the container-side isolated-auth store",
    "_strip_var_from_env_files": "scrubs the token from podman --env-file temps; host mode has no env-file",
    "_omp_agent_mount": "bind mount",
    "_omp_mcp_seed_mount": "bind mount",
    # --- credential/socket forwarding: the host reaches these natively ---
    "_credential_forward_args": "forwards host credentials into a netns the host is not in",
    "_ssh_agent_auto_forward_args": "forwards $SSH_AUTH_SOCK; the host already has it",
    "_trusted_ssh_keys": "gates which keys get MOUNTED",
    "_claude_oauth_token_args": "passes the token as container env; the host inherits it",
    "_claude_oauth_token_configured": "paired with the arg builder above",
    "_aws_sso_ecs_forward_args": "ECS credential endpoint for a container; the host has real creds",
    "_aws_sso_server_reachable": "paired with the forward args above",
    "_corp_proxy_ca_mount_args": "mounts the CA; the host trusts its own store",
    "_install_corp_proxy_ca_in_container": "installs the CA inside a container",
    # --- network/namespace: nothing to isolate or proxy on the host ---
    "_apply_firewall": "netns firewall; a host launch is not isolated",
    "_wait_hatago": "waits on the in-pod MCP hub; the host uses _host_native_mcp",
    "_resolve_mount_path": "maps a host path to its in-container path",
    "_resolve_start_dir": "resolves the agent's start dir INSIDE the pod",
    "project_relpath": "the mount point a host path takes INSIDE the container",
    "instance_name": "names the container/pod; a host launch creates neither",
    # --- same capability, different executor (the host has its own implementation) ---
    "_container_setup_env": "container half of the setup env; host: _script_env via _host_run_setups",
    "_run_container_setups": "container half; host: _host_run_setups",
    "_pending_setup_scripts": "container half; host: _host_run_setups",
    "_resolve_launch_secrets": "container half (--env-file); host: _resolve_launch_env",
    # Composes image + profile content into one agent-config tree AND runs tools:/install: into the
    # per-stack volumes. Both halves are the container-side answer to problems the host does not
    # have: host mode materializes the per-stack home directly (_materialize_host_home +
    # LinkSyncer.fan) with nothing mounted over it — which is exactly why bd harnessed-8px.22 hit
    # container launches and not host ones — and runs its installs through _host_run_installs.
    "_ensure_stack_volumes": "composes podman volumes + runs installs; host: _materialize_host_home + _host_run_installs",
    # --- container-only by nature ---
    # Host mode has no image: `_launch_host` assembles in-process on every launch, so a minted
    # recipe set needs no build step there at all.
    "_build_stack": "builds the container image; the host assembles in-process every launch",
    "is_built": "requires a pre-assembled profile; `_launch_host` calls `assemble` itself instead",
    "load_stack": "host: load_stack_with_recipes, which it needs for the recipe list anyway",
    # --- called by the host VERB rather than by _launch_host ---
    "_require_supported_harness": "`host_run` calls it itself, before delegating",
    "_resolve_stack": "`host_run` calls it itself — shared --stack/--recipe resolution",
}


def _stack_helpers(fn) -> set[str]:
    """Names of harnessed-defined helpers this function calls.

    Restricted to callables defined somewhere in the `harnessed` package, which is what scopes this
    to harnessed's own logic — stdlib and third-party calls are noise for this question.

    Package-wide rather than `launcher`-only ON PURPOSE. launcher.py is being split into modules
    (bd harnessed-4l8), and a `__module__ == launcher` test would silently STOP SEEING each helper
    the moment it moved — the lint would decay to nothing exactly as the file it guards is
    rearranged, and every entry in CONTAINER_ONLY would go stale one extraction at a time. The
    question this asks is "does the host path do the same stack-derived work", and that does not
    depend on which module the work now lives in.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if not name:
            continue
        obj = getattr(launcher, name, None)
        module = getattr(obj, "__module__", None) or ""
        # The backend class each path constructs is the SEAM, not a capability: `container-run`
        # naming ContainerBackend and `_launch_host` naming HostBackend is the contract working, and
        # counting it would report a permanent, meaningless asymmetry.
        if isinstance(obj, type) and issubclass(obj, ExecutionBackend):
            continue
        if callable(obj) and (module == "harnessed" or module.startswith("harnessed.")):
            found.add(name)
    return found


def _launch_path(fn, backend_cls) -> set[str]:
    """Every harnessed helper a launch path calls: the sequencer PLUS the backend it drives.

    Same reasoning as `_stack_helpers`' package-wide scope, one seam later. The contract operations
    moved out of the Typer command and into `ExecutionBackend` implementations (bd harnessed-0tk.1),
    so scanning the command alone stopped seeing the work — and this lint would have decayed to
    nothing while reporting green, which is the decay this module's docstring exists to prevent.
    """
    names = _stack_helpers(fn)
    for op in vars(backend_cls).values():
        if callable(op):
            names |= _stack_helpers(op)
    return names


def _container_path() -> set[str]:
    return _launch_path(launcher.container_run, launcher.ContainerBackend)


def _host_path() -> set[str]:
    return _launch_path(launcher._launch_host, launcher.HostBackend)


class TestLaunchAndHostRunStayInStep:
    def test_no_unexplained_container_only_capability(self):
        container_only = _container_path() - _host_path()
        unexplained = sorted(container_only - set(CONTAINER_ONLY))
        assert not unexplained, (
            "these are called by `container-run` but not by `_launch_host`:\n  "
            + "\n  ".join(unexplained)
            + "\n\nEither wire them into the host path too, or add each to CONTAINER_ONLY in this "
            "file with the reason it cannot apply to a host-native launch. Five capabilities were "
            "already missed this way — see this module's docstring."
        )

    def test_the_ledger_has_no_stale_entries(self):
        """A name that `container-run` no longer calls is a licence nobody needs — and, worse, it would
        silently pre-authorise a FUTURE helper that happens to reuse the name."""
        stale = sorted(set(CONTAINER_ONLY) - _container_path())
        assert not stale, f"CONTAINER_ONLY lists helpers `container-run` no longer calls: {stale}"

    def test_the_five_known_misses_are_wired_into_the_host_path(self):
        """Regression pin for the specific bugs, independent of the diff above: the ledger could be
        edited to silence the general test, but these five were real and must stay fixed."""
        host = _host_path()
        for helper in ("_ensure_services", "_host_run_inits", "_prompt_setup_notices"):
            assert helper in host, f"{helper} must run on a host launch too"
        # The other two are values rather than calls: the socket export is no longer gated on mode,
        # and the agent path is resolved per mode. Pin the exact gate that was wrong — harnessed_env
        # still branches on mode for HARNESSED_RECIPE_DIR, which genuinely does differ per mode.
        assert 'mode == "container" and sockets' not in inspect.getsource(launcher.harnessed_env)
        assert "mode" in inspect.signature(launcher._service_data_dir).parameters
