#!/usr/bin/env bash
# harnessed — isolated stack launcher.
#
# isolated = "clean room with exactly what I picked": the config layer (skills/commands/hooks/
# agents/rules/.mcp.json/settings.json) comes ONLY from the assembled, committed
# profiles/<stack>/.claude tree — NOTHING from host config (§2/§4b, MODE-03). Auth is seeded by
# a read-only ~/.claude/.credentials.json mount + a generated token-free .claude.json stub
# (lib/harnessed-isolated-config.sh, D-07/AUTH-02).
#
# The stack is a podman POD (harness container + hatago). Pod members
# share a netns, so the harness reaches hatago's single Streamable-HTTP endpoint at
# http://localhost:3535/mcp (the profile's .mcp.json; MCP-01/MCP-02, D-04).
#
# Mirrors lib/harnessed-transparent.sh's shape; reuses §4a mounts verbatim (D-16,
# harnessed_host_integration_mounts), apply_firewall, and the instance/lifecycle helpers from
# lib/harnessed-common.sh (D-15). Host-native: every podman call runs on the host, no DooD.
#
# Headless: set HARNESSED_HEADLESS=true to compose + start the pod WITHOUT the interactive
# `claude` attach — the members stay up (`sleep infinity`) for `podman exec` introspection. The
# capability test (plan 02-03) launches via this path (`--fresh` headless) and asserts against
# the live instance.

# Pod network: DEFAULT rootless (pasta) networking — NOT a bridge. Rootless bridges are
# unsupported on most hosts (netavark "create bridge: Operation not supported"), so pod
# members reach shared services via the host gateway `host.containers.internal:<port>`
# (plan 04-01 rootless fix). The `HARNESSED_NET` bridge is the opt-in for bridge-capable
# hosts (DNS-by-name, http://<service>:<port>). Members share a netns either way, so the
# harness always reaches hatago at localhost:$HATAGO_PORT.
HARNESSED_NET="${HARNESSED_NET:-}"
HATAGO_PORT="${HATAGO_PORT:-3535}"

# harnessed_isolated <stack> <project_path> [fresh]
harnessed_isolated() {
    local stack="$1" project_path="$2" fresh="${3:-false}"

    # Read the stack's harness (flat scalar grep — the manifest is authored). Default claude.
    # omp stacks run from harnessed-omp and attach via `omp --profile`; opencode stacks run from
    # harnessed-opencode and attach via `opencode` (TUI in the project cwd); claude stacks use
    # harnessed-claude + `claude --mcp-config` (plan 04-03 / HRN-01, HRN-02).
    local harness
    harness="$(sed -n 's/^harness:[[:space:]]*//p' "$HARNESSED_DIR/stacks/$stack/stack.yaml" | tr -d '[:space:]')"
    harness="${harness:-claude}"
    local harness_image="$HARNESSED_CLAUDE_IMAGE"
    [ "$harness" = "omp" ] && harness_image="$HARNESSED_OMP_IMAGE"
    [ "$harness" = "opencode" ] && harness_image="$HARNESSED_OPENCODE_IMAGE"
    [ "$harness" = "gemini" ] && harness_image="$HARNESSED_GEMINI_IMAGE"
    [ "$harness" = "antigravity" ] && harness_image="$HARNESSED_ANTIGRAVITY_IMAGE"
    [ "$harness" = "codex" ] && harness_image="$HARNESSED_CODEX_IMAGE"
    # LAZY: build a non-claude harness image only when such a stack actually launches (HRN-01..05).
    # The claude + hatago images are ensured by the bootstrap's ensure_images call before this.
    [ "$harness" = "omp" ] && ensure_omp_image
    [ "$harness" = "opencode" ] && ensure_opencode_image
    [ "$harness" = "gemini" ] && ensure_gemini_image
    [ "$harness" = "antigravity" ] && ensure_antigravity_image
    [ "$harness" = "codex" ] && ensure_codex_image

    . "$HARNESSED_DIR/lib/harnessed-mounts.sh"
    . "$HARNESSED_DIR/lib/harnessed-isolated-config.sh"
    . "$HARNESSED_DIR/lib/harnessed-services.sh"
    . "$HARNESSED_DIR/lib/harnessed-manifest-mounts.sh"

    [ -d "$project_path" ] || { print_error "Project directory does not exist: $project_path"; exit 1; }

    local profile_dir="$HARNESSED_DIR/profiles/$stack"
    [ -f "$profile_dir/.mcp.json" ] || {
        print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }

    local relpath instance pod headless
    relpath="$(project_relpath "$project_path")"
    instance="$(generate_instance_name "$stack" "$project_path")"
    pod="$instance"                                   # the pod takes the same base name (§13)
    headless="${HARNESSED_HEADLESS:-false}"

    local mise_init="source ~/.bashrc && mise trust -a 2>/dev/null"
    # Preserved as the literal default-name anchor (D-01/D-03); the live pod-network block
    # below reads ${HARNESSED_NET:-} directly, so $net is assigned-but-unused on this path.
    # KEPT per D-04 ("if unsure, leave it and add a clarifying comment").
    local net="${HARNESSED_NET:-harnessed-net}"

    # --fresh: tear down any existing pod/instance before recreate — no state bleed (D-11).
    if [ "$fresh" = "true" ]; then
        print_info "--fresh: tearing down existing pod/instance for $instance"
        rt_group_teardown "$instance" "$pod"
    fi

    # Re-attach to an already-running instance (interactive only; like transparent).
    if [ "$headless" != "true" ] && container_running "$instance"; then
        print_info "Attaching to running instance: $instance"
        if [ "$harness" = "omp" ]; then
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && omp --profile \"$instance\""
        elif [ "$harness" = "opencode" ]; then
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && opencode"
        elif [ "$harness" = "gemini" ]; then
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && gemini"
        elif [ "$harness" = "antigravity" ]; then
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && agy"
        elif [ "$harness" = "codex" ]; then
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && codex"
        else
            "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
                bash -l -c "$mise_init && claude"
        fi
        stop_if_last_session "$instance" "$relpath"
        return 0
    fi

    print_info "Creating isolated pod: $pod (harness + hatago)"
    print_info "Project: $project_path -> $CONTAINER_HOME/$relpath"

    # §4a host-integration mounts (reused verbatim — D-16): userns/firewall/agents/signing/project.
    local MOUNT_ARGS=()
    harnessed_host_integration_mounts "$project_path" "$relpath"
    # §4b isolated auth: harness-aware. claude/omp → ro ~/.claude/.credentials.json + token-free
    # .claude.json stub (D-07); opencode → ro ~/.local/share/opencode/auth.json (HRN-02).
    harnessed_isolated_auth_mounts "$instance" "$harness"
    # Config source = manifest-driven surgical mounts (MNT2-01/MNT2-06): per-harness profile
    # config files (ro), history dirs (rw), and path-mirroring bind (MNT2-02). The old
    # whole-dir copy-and-mount block is replaced by a single harnessed_manifest_mounts call.
    harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"

    # Pod network: DEFAULT rootless (pasta) networking — NOT a bridge. Rootless bridges are
    # unsupported on most hosts (netavark "create bridge: Operation not supported"), so shared
    # services publish their port to 0.0.0.0 and pod members reach them via the host gateway
    # `host.containers.internal:<port>` (plan 04-01 rootless fix). Members still reach hatago at
    # localhost:3535 (shared pod netns). HARNESSED_NET is an explicit opt-in bridge override for
    # hosts that DO support rootless bridges.
    local pod_net_args=()
    if [ -n "${HARNESSED_NET:-}" ]; then
        ensure_named_net "$HARNESSED_NET"
        pod_net_args=( --network "$HARNESSED_NET" )
    fi

    # Compose the pod (harness + hatago share the netns). keep-id maps the container user to the
    # host UID so mounted project/profile/credential paths are owned correctly. userns is a
    # POD-level property (set on the infra container); pod MEMBERS must NOT pass --userns, so it
    # is stripped from the member args below.
    rt_group_create "$instance" "$pod" "${pod_net_args[@]}"

    # Auto-start the stack's declared shared services (plan 04-01 / SVC-02, design §9: an instance
    # starts it if absent; it outlives instances). The service is a STANDALONE container on the
    # shared network, NOT a pod member — its lifecycle is independent of this pod. This runs
    # after pod create and before the members so the service is up when hatago tries to proxy it.
    local svc_line svc
    svc_line="$(sed -n 's/^services: *//p' "$HARNESSED_DIR/stacks/$stack/stack.yaml")"
    svc_line="${svc_line#[}"          # strip inline-array brackets: [a, b] → a, b
    svc_line="${svc_line%]}"
    for svc in $svc_line; do
        svc="${svc%,}"
        [ -n "$svc" ] && ensure_service_up "$svc"
    done

    # [SEC-01 / plan 05-02] Opt-in secret resolution: when ~/.config/harnessed/.env.schema is
    # present, resolve op:// refs via varlock in a throwaway tools container (Pattern 1) into a
    # mode-0600 temp env-file, then spread --env-file into BOTH pod members so resolved secrets
    # reach the pod as env only (never the profile or an image layer — T-05-05). Inert when no
    # schema (resolve_secret_env returns 0 with empty stdout → env_args is empty). The temp
    # file is unlinked after launch (T-05-06) — see the two return paths below.
    . "$HARNESSED_DIR/lib/harnessed-secrets.sh"
    local secret_env resolve_rc=0
    secret_env="$(resolve_secret_env)" || resolve_rc=$?
    if [ "$resolve_rc" -ne 0 ]; then
        print_error "secret resolution failed; aborting launch"
        rt_group_teardown "$instance" "$pod"
        return 1
    fi
    local -a env_args=()
    [ -n "$secret_env" ] && env_args=( --env-file "$secret_env" )
    # T-05-06 full coverage: wipe the resolved-secret temp env-file on ANY return from here
    # (a `set -e` abort on either member launch / apply_firewall / the readiness wait, or an
    # early return) — not only the two happy-path unlinks at the tail below. A RETURN trap is
    # scoped to this function (bash restores the prior trap on return), so this is the single
    # source of cleanup; the explicit `rm -f`s at the tail remain as harmless happy-path belts.
    [ -n "$secret_env" ] && trap 'rm -f "${secret_env:-}" 2>/dev/null || true' RETURN
    # hatago member: serve ONE Streamable-HTTP endpoint on :3535 from the mounted per-stack
    # config (which baked stdio servers to expose; the image CMD is overridden to add --config).
    "$CONTAINER_RUNTIME" run -d $(rt_hatago_placement "$instance" "$pod") --name "${instance}-hatago" \
        "${env_args[@]}" \
        -v "$profile_dir/hatago.config.json:$CONTAINER_HOME/hatago.config.json:ro" \
        "$HARNESSED_HATAGO_IMAGE" \
        hatago serve --http --port "$HATAGO_PORT" --config "$CONTAINER_HOME/hatago.config.json" >/dev/null

    # harness member: the harness container (claude or omp) — profile-only config, §4a + isolated
    # §4b mounts. omp stacks run harnessed-omp (the bridge auto-loads — pre-installed in the image).
    # Strip --userns=keep-id from the member args (inherited from the pod; illegal on a member).
    local member_args=() _arg
    for _arg in "${MOUNT_ARGS[@]}"; do
        [ "$_arg" = "--userns=keep-id" ] && continue
        member_args+=( "$_arg" )
    done
    "$CONTAINER_RUNTIME" run -d $(rt_harness_placement "$instance" "$pod") --name "$instance" "${member_args[@]}" \
        "${env_args[@]}" \
        "$harness_image" sleep infinity >/dev/null

    # Egress firewall on the harness container (NET_ADMIN); shared pod netns → covers hatago too.
    apply_firewall "$instance"

    # Wait for hatago to be ready before attaching: it connects its stdio children, fires
    # tools/list_changed, THEN binds :$HATAGO_PORT (~a few seconds). Attaching claude before the
    # port is up yields an empty/failed MCP connection for the session.
    print_info "Waiting for hatago hub on :$HATAGO_PORT ..."
    local _i
    for _i in $(seq 1 30); do
        "$CONTAINER_RUNTIME" exec "$instance" bash -lc "timeout 1 bash -c 'echo > /dev/tcp/127.0.0.1/$HATAGO_PORT'" >/dev/null 2>&1 && break
        sleep 1
    done

    # Headless (capability test, 02-03): leave the pod running for podman-exec introspection.
    if [ "$headless" = "true" ]; then
        print_success "Isolated pod running headless: $instance (hatago: ${instance}-hatago)"
        [ -n "$secret_env" ] && rm -f "$secret_env"
        return 0
    fi

    # Interactive attach (host-native TTY). The harness attach command branches on stack.harness
    # (plan 04-03): claude loads ONLY the profile's hatago MCP endpoint via --mcp-config +
    # --strict-mcp-config (a profile-only ~/.claude/.mcp.json is otherwise NOT read by claude, and
    # --strict-mcp-config keeps isolation — account-synced servers never leak in); omp consumes the
    # Claude-canonical profile via the pre-installed bridge and isolates the session with --profile
    # (the bridge auto-loads — no per-launch -e). omp's MCP wiring to hatago is resolved in the
    # checkpoint (P-04-11; same localhost:3535 endpoint, shared pod netns).
    local mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"
    if [ "$harness" = "omp" ]; then
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && omp --profile \"$instance\""
    elif [ "$harness" = "opencode" ]; then
        # opencode reads the SAME profile's .claude/skills natively and reaches hatago via its baked
        # ~/.config/opencode config (it ignores .mcp.json), so a bare `opencode` in the project cwd
        # is the attach (no MCP flags); shared pod netns → same localhost:3535 endpoint.
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && opencode"
    elif [ "$harness" = "gemini" ]; then
        # gemini reaches hatago via its baked ~/.gemini/settings.json (mcpServers → localhost:3535);
        # a bare `gemini` in the project cwd is the attach. Claude skills/commands are not natively
        # consumed (its native assets differ) — the profile is still mounted for parity.
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && gemini"
    elif [ "$harness" = "antigravity" ]; then
        # antigravity (agy) reaches hatago via its baked ~/.gemini/config/mcp_config.json
        # (serverUrl → localhost:3535); a bare `agy` in the project cwd is the attach.
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && agy"
    elif [ "$harness" = "codex" ]; then
        # codex reaches hatago via its baked ~/.codex/config.toml ([mcp_servers.hatago] url, native
        # streamable-HTTP); a bare `codex` in the project cwd is the attach. Reads AGENTS.md but not
        # Claude skills/commands — the profile is still mounted for parity.
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && codex"
    else
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && claude --mcp-config '$mcp_cfg' --strict-mcp-config"
    fi
    stop_if_last_session "$instance" "$relpath"
    [ -n "$secret_env" ] && rm -f "$secret_env"
    print_success "Instance session ended"
}
