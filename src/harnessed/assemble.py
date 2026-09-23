"""Orchestrate the emit-only assembly of a stack into a committed profile + hatago config.

Flow (design §7/§15, D-04/D-12/D-13):
  read stack + its recipes
    → fan skills/commands into the harness profile (fail-fast on name collision)
    → merge every recipe's mcp.servers into one hatago.config.json (child stdio servers)
    → derive the harness .mcp.json (exactly ONE entry → the hatago endpoint)
    → record which stdio servers the hatago image must bake
    → emit all of the above into the mounted build dir.

EMIT ONLY: nothing here invokes podman/docker or mounts a daemon socket.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import emit, paths, staleness
from .schema import (
    HUB_TRANSPORT_EMITTED_HARNESSES,
    HUB_TRANSPORT_STDIO,
    McpServer,
    PinValidationError,
    Recipe,
    SchemaError,
    Stack,
    load_agent,
    load_service,
    load_stack,
    load_stack_with_recipes,
    validate_container_only_declared,
    validate_init_no_exit,
    validate_dockerfile_not_dependent_on_install,
    validate_no_claude_writes,
    validate_agent_pin,
    validate_no_raw_npm,
    validate_install_script,
    validate_pin,
    validate_setup_script,
)
from .synclinks import CollisionError, LinkSyncer


@dataclass
class AssembleResult:
    stack: Stack
    harness: str
    recipes: list[Recipe]
    profile_dir: Path
    servers: list[McpServer]
    baked: list[McpServer]


def compute_recipe_hash(stack_yaml: Path, recipes: list[Recipe]) -> str:
    """Content hash of a stack's full recipe closure: the stack's own ``stack.yaml``, every file
    under each recipe directory, and every referenced service directory.

    Services are part of the stack's build closure — an edit to a service's Dockerfile or
    entrypoint must move the hash just as a recipe edit does.  Service names are collected from
    three sources: ``recipe.servers[].service`` (MCP service refs), ``recipe.services`` (non-MCP
    sidecars declared by recipes), and the stack's own ``services:`` list.

    Stamped as the ``harnessed.recipe-hash`` label on the derived stack image (see
    ``_build_derived_image``) rather than kept in a side-file manifest, so the hash can never
    drift from the image it describes — ``harnessed build``'s reconciliation pass compares this
    against ``podman inspect``'s label directly.
    """
    digest = hashlib.sha256()
    digest.update(stack_yaml.read_bytes())
    for recipe in sorted(recipes, key=lambda r: r.name):
        for path in sorted(p for p in recipe.root.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(recipe.root)).encode())
            digest.update(path.read_bytes())

    # Collect referenced service names from all three sources (mirrors _service_refs in launcher).
    service_names: list[str] = []
    for recipe in sorted(recipes, key=lambda r: r.name):
        for server in recipe.servers:
            if server.service and server.service not in service_names:
                service_names.append(server.service)
        for name in recipe.services:
            if name not in service_names:
                service_names.append(name)
    stack = load_stack(stack_yaml.parent)
    for name in stack.services:
        if name not in service_names:
            service_names.append(name)

    # Locate each service directory.  Build the search list the same way the runtime does:
    # paths.catalog_roots() first (user overlay wins on a name clash, matching runtime resolution),
    # then any roots inferred from recipe/stack paths that are not already present (handles
    # isolated test roots and non-standard layouts).
    seen_roots: set[Path] = set()
    service_catalog_roots: list[Path] = []
    for croot in paths.catalog_roots():
        if croot not in seen_roots:
            service_catalog_roots.append(croot)
            seen_roots.add(croot)
    for recipe in recipes:
        croot = recipe.root.parent.parent
        if croot not in seen_roots:
            service_catalog_roots.append(croot)
            seen_roots.add(croot)
    stack_croot = stack_yaml.parent.parent.parent
    if stack_croot not in seen_roots:
        service_catalog_roots.append(stack_croot)

    for name in sorted(service_names):
        service_dir: Path | None = None
        for croot in service_catalog_roots:
            cand = croot / "services" / name
            if cand.is_dir():
                service_dir = cand
                break
        if service_dir is None:
            continue
        # Length-prefix each field to avoid hash collisions from ambiguous concatenation
        # (file "a/b" with content "c" must not collide with file "a" with content "bc").
        # The service NAME is framed in too: the file paths below are relative to service_dir, so
        # without it two same-content services are indistinguishable and a rename moves nothing.
        svc_name = name.encode()
        digest.update(len(svc_name).to_bytes(4, "big"))
        digest.update(svc_name)
        for path in sorted(p for p in service_dir.rglob("*") if p.is_file()):
            rel = str(path.relative_to(service_dir)).encode()
            content = path.read_bytes()
            digest.update(len(rel).to_bytes(4, "big"))
            digest.update(rel)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)

    return digest.hexdigest()


def _merge_servers(recipes: list[Recipe]) -> list[McpServer]:
    """Collect every recipe's MCP servers, failing fast on a duplicate server name."""
    servers: list[McpServer] = []
    owner: dict[str, str] = {}
    for recipe in recipes:
        for server in recipe.servers:
            if server.name in owner:
                raise CollisionError(
                    f"mcp server name collision: '{server.name}' is declared by two recipes "
                    f"('{owner[server.name]}' and '{recipe.name}'). Rename one server."
                )
            owner[server.name] = recipe.name
            servers.append(server)
    return servers


def _resolve_service_servers(servers: list[McpServer], root: Path | None) -> list[McpServer]:
    """Resolve ``service:``-referenced MCP servers to network-native URLs (plan 04-01 / SVC-01).

    A recipe declares a service-referenced server with ``service: <name>`` and NO command
    (``is_stdio_child`` is False). The assembler resolves the service name → port by reading
    ``services/<name>/service.yaml`` and sets ``url`` + ``transport`` so ``emit._hatago_entry``
    emits a ``{url, type: http}`` hatago proxy entry. The resolution lives HERE so emit stays
    dumb (it already emits network-native servers as ``{url, type}`` — no emit change needed).
    """
    for server in servers:
        if server.service and not server.is_stdio_child:
            svc = load_service(root, server.service)
            # Rootless model (plan 04-01 fix): no bridge — services publish to 0.0.0.0 and peers
            # reach them via the podman host gateway `host.containers.internal`. A rootless bridge
            # is unsupported on most hosts (netavark "Operation not supported"), so DNS-by-service-
            # name over harnessed-net was replaced with the host-gateway address.
            server.url = f"http://host.containers.internal:{svc.port}/mcp"
            if server.transport == "stdio":
                server.transport = "http"
    return servers


def validate_agent_image(harness: str) -> None:
    """AC-9 part 2: lint the AGENT image's Dockerfile, the way `validate_pin` lints a recipe's.

    Resolved with `root=None` DELIBERATELY, and not from `assemble`'s `root`. That parameter
    restricts which catalog roots recipes and stacks resolve from; the agent image is built by
    `launcher._build_agent_image`, which always loads the agent across every root. Linting what the
    build will actually use is the whole point — reading whatever a restricted root happened to
    contain would be a different question wearing the same name, and it would go quiet exactly when
    a caller narrowed the root.

    FAILS CLOSED on a Dockerfile it cannot read. An agent whose Dockerfile is missing is not an
    agent that passes: the build would fail on it seconds later, and a gate that returns silently
    for an input it could not examine is indistinguishable from one that examined it and approved.
    """
    agent = load_agent(harness)
    # The manifest's path is home-relative (`catalog/base/Dockerfile.harnessed-omp`), the same
    # convention `launcher._build_agent_image` reads it under. Anchored to `harnessed_home()`, never
    # the CWD — assembly must not depend on where it was invoked from (CLAUDE.md).
    rel = agent.dockerfile or f"catalog/base/Dockerfile.harnessed-{harness}"
    dockerfile = paths.harnessed_home() / rel
    if not dockerfile.is_file():
        raise PinValidationError(
            f"agent '{harness}': its Dockerfile is declared as {rel!r} but no file is there "
            f"({dockerfile}). The pin lint cannot examine it, and the build would fail on the same "
            f"path — refusing to assemble rather than passing an image nothing checked."
        )
    validate_agent_pin(
        harness, dockerfile.read_text(encoding="utf-8"), unpinnable=agent.unpinnable,
    )


def _validate_hub_transport(stack: Stack, harness: str) -> None:
    """`hub_transport: stdio` is only honourable for a harness whose hub wiring harnessed EMITS.

    Only claude's hub entry is written per stack (`emit.write_mcp_json`). codex bakes
    `[mcp_servers.hatago]` with an HTTP url into its IMAGE, and omp has no hub wiring at all — so
    assembling a stdio stack for one of those yields a harness that still dials HTTP while
    `harnessed-start`, honouring the same field, starts no hub. The result is an agent with no tools
    and no error explaining why, which is exactly the failure mode worth refusing at build time.
    """
    if stack.hub_transport != HUB_TRANSPORT_STDIO:
        return
    if harness in HUB_TRANSPORT_EMITTED_HARNESSES:
        return
    raise SchemaError(
        f"stack '{stack.name}' declares hub_transport: stdio, which harness '{harness}' cannot "
        f"honour — only {', '.join(sorted(HUB_TRANSPORT_EMITTED_HARNESSES))} has its hub entry "
        f"emitted per stack; '{harness}' bakes the hub address into its image. Build this stack "
        f"for a supported harness, or set hub_transport: http."
    )


def _validate_direct_servers(servers: list[McpServer], harness: str) -> None:
    """`direct:` is only honourable for a harness whose MCP config harnessed EMITS.

    Same boundary as `hub_transport: stdio`, for the same reason. Only claude's `.mcp.json` is
    written per stack; codex and omp carry their MCP wiring baked into their IMAGE, so a direct
    server declared for one of those would be silently absent — the recipe would read as if the
    server were configured while the harness never learned of it, and hatago would not have it
    either, because `direct` removes it from the hub's config. Failing the build names the problem;
    the alternative names nothing at all.
    """
    direct = [s.name for s in servers if s.direct]
    if not direct or harness in HUB_TRANSPORT_EMITTED_HARNESSES:
        return
    raise SchemaError(
        f"mcp server(s) {', '.join(sorted(direct))} declare 'direct: true', which harness "
        f"'{harness}' cannot honour — only "
        f"{', '.join(sorted(HUB_TRANSPORT_EMITTED_HARNESSES))} has its MCP config emitted per "
        f"stack; '{harness}' bakes it into its image. Drop 'direct' so the server is reached "
        f"through hatago, or build this stack for a supported harness."
    )


def assemble(
    root: Path | None, stack_name: str, build_dir: Path, harness: str, *, strict: bool = False,
    shared_identity: bool = True,
) -> AssembleResult:
    """Assemble a stack into a profile. `root` None → resolve recipes/stacks/services across the
    catalog roots (user overlay first); a Path restricts resolution to that single root.

    `strict` → reject unknown recipe-manifest fields (typo guardrail); `harnessed build` passes it
    on by default, `--no-strict` opts out.

    `shared_identity=False` suppresses the ONE emit step that writes OUTSIDE the profile — omp's
    delimiter-marked blocks in the shared `~/.omp/agent` (#307). A host launch assembles in-process
    every time and then materializes a PER-STACK agent dir under `PI_CODING_AGENT_DIR`, so leaving
    the shared write on would have every `host-run <stack> omp` deposit blocks in the user's own omp
    while the session read a different file entirely — writing into the shared dir precisely to
    achieve nothing. The container path, which has no per-stack agent dir, keeps the default."""
    root = Path(root) if root is not None else None
    build_dir = Path(build_dir)

    stack, recipes = load_stack_with_recipes(root, stack_name, strict=strict)

    # Fail-fast recipe validation (BLD-03 + ASM-02): reject raw npm/npx and floating Dockerfile refs
    # BEFORE any file is emitted. Recipes are harness-independent (any harness consumes the same
    # Claude-canonical profile; harness-specific needs are handled inside the recipe Dockerfile via
    # ${HARNESS}), so there is no harness-compat gate.
    for recipe in recipes:
        validate_no_raw_npm(recipe)
        validate_init_no_exit(recipe)  # Model A: init.run is sourced — a bash `exit` kills the shell
        validate_setup_script(recipe)  # setup.script is a FILE — neither gate below would read it
        validate_install_script(recipe)  # ditto, and it is where Dockerfile RUN bodies now live
        dockerfile = recipe.root / "Dockerfile"
        if dockerfile.is_file():
            body = dockerfile.read_text(encoding="utf-8")
            validate_pin(recipe.name, body)  # ASM-02 (T-08-01)
            # A migrated recipe that kept a RUN must SAY what a host launch loses (harnessed-8px.1).
            validate_container_only_declared(recipe, body)
            # Content in ~/.claude is invisible host-side and hidden container-side (harnessed-8px.7).
            validate_no_claude_writes(recipe, body)
            validate_dockerfile_not_dependent_on_install(recipe, body)

    # AC-9 PART 2 — the agent image is a Dockerfile too, and until now nothing linted it. That gap
    # is how three agents reached `main` acquiring their CLI with no version at all: `validate_pin`
    # has only ever read RECIPE Dockerfiles, so the images every stack is built FROM were the one
    # unlinted surface in the pipeline. Deferred until now on purpose (plan REVISION 9) because
    # switching it on while claude, codex or omp still floated would have failed their builds; A2,
    # A3 and A5b closed the last of those.
    validate_agent_image(harness)

    servers = _resolve_service_servers(_merge_servers(recipes), root)

    profile_dir = build_dir / "profiles" / stack.name / harness

    _validate_hub_transport(stack, harness)
    _validate_direct_servers(servers, harness)

    emit.reset_profile(profile_dir)
    emit.write_mcp_json(profile_dir, stack.hub_transport, servers)
    emit.write_settings_json(profile_dir, servers, recipes, stack.permissions, harness)
    emit.write_hatago_config(profile_dir, servers)
    # ASM-03 — derived Dockerfile. No scan layer: the scan moved to the credentialed post-build
    # pass (bd harnessed-8px.21.5), which is the only one that has tokens and the only one that can
    # see the stack volumes. HARNESSED_NO_SCANS is honoured there instead.
    emit.write_derived_dockerfile(profile_dir, stack.name, harness, recipes)

    # Fan each recipe's standalone skills/commands into the harness-native profile tree
    # (<profile>/.claude/{skills,commands}). The launcher mounts these dirs into the instance and
    # the capability test reads them back, so the fan-out is what makes a skill recipe observable.
    # `harness` is threaded in so an entry's `only_harnesses` can drop it here: content that exists
    # to patch one harness's hole must not ship, always-on, to the harnesses without that hole.
    syncer = LinkSyncer(harness=harness)
    for recipe in recipes:
        syncer.add_recipe(recipe)
    syncer.fan(profile_dir / ".claude")

    # Stack-level identity → the harness's own top-level memory file (bd main-ylz, main-72j, main-7rh).
    #   - claude: `.claude/CLAUDE.md` (its memory file); recipe rules stay as `.claude/rules/*.md`.
    #   - antigravity (agy, gemini-derived): a `.gemini` context file named by settings.json
    #     context.fileName.
    #   - codex:  `.codex/AGENTS.md` — codex has no directory-rules primitive, so identity AND the
    #             fanned `.claude/rules/*.md` are concatenated into the ONE doc codex reads.
    #   - omp:    identity → APPEND_SYSTEM.md, rules → RULES.md, as delimiter-marked per-stack blocks
    #             in the SHARED host ~/.omp/agent (the dir the launcher bind-mounts rw into every omp
    #             pod). The omp-claude-hooks-bridge cannot inject per-profile context, so this reuses
    #             the existing agent-dir mount instead (bd main-w8k; shared, not profile-scoped).
    # opencode's identity is wired post-build in the launcher (it merges the image-baked config).
    # A recipe's `setup:` note is deliberately NOT combined into any identity file — setup notices
    # are user-facing and shown host-side by the launcher at attach time (launcher._prompt_setup_notices).
    instructions = stack.instructions
    if harness == "claude":
        emit.write_claude_md(profile_dir, instructions)
    elif harness == "antigravity":
        emit.write_antigravity_identity(profile_dir, instructions)
    elif harness in ("codex", "omp"):
        rules_dir = profile_dir / ".claude" / "rules"
        rule_files = sorted(rules_dir.rglob("*.md")) if rules_dir.is_dir() else []
        if harness == "codex":
            emit.write_codex_agents_md(profile_dir, instructions, rule_files)
        elif shared_identity:
            emit.write_omp_identity(profile_dir, stack.name, instructions, rule_files)
        # else: the host backend renders the same content WHOLE into its per-stack agent dir
        # (launcher._plan_host_omp) — see `shared_identity` above.

    # stdio children are baked into the harness/stack image and spawned by the in-container hatago
    # (hatago-consolidation); kept for reporting. No separate baked-servers.json is written.
    baked = [s for s in servers if s.is_stdio_child]

    # Stamp the profile with a hash of its catalog inputs (stack.yaml + recipe dirs) so a later
    # `harnessed launch`/`test` can detect that a recipe was renamed/removed/edited out from under a
    # previously-built stack (staleness.check_profile_fresh). Written last: the profile is complete.
    staleness.write_stamp(profile_dir, staleness.compute_stamp(root, stack, recipes))

    return AssembleResult(
        stack=stack,
        harness=harness,
        recipes=recipes,
        profile_dir=profile_dir,
        servers=servers,
        baked=baked,
    )
