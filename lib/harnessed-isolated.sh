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

# Pod network: harnessed-net is the DEFAULT for isolated stacks (plan 04-01 / SVC-02) so pod
# members resolve shared services by DNS name (http://<service>:<port>). Set HARNESSED_NET=<name>
# to override the network name (advanced/multi-network). Members share a netns either way, so
# the harness always reaches hatago at localhost:$HATAGO_PORT.
HARNESSED_NET="${HARNESSED_NET:-}"
HATAGO_PORT="${HATAGO_PORT:-3535}"

# harnessed_isolated <stack> <project_path> [fresh]
harnessed_isolated() {
    local stack="$1" project_path="$2" fresh="${3:-false}"

    . "$HARNESSED_DIR/lib/harnessed-mounts.sh"
    . "$HARNESSED_DIR/lib/harnessed-isolated-config.sh"
    . "$HARNESSED_DIR/lib/harnessed-services.sh"

    [ -d "$project_path" ] || { print_error "Project directory does not exist: $project_path"; exit 1; }

    local profile_dir="$HARNESSED_DIR/profiles/$stack"
    [ -d "$profile_dir/.claude" ] || {
        print_error "Stack '$stack' has no assembled profile (run: harnessed build $stack)"; exit 1; }

    local relpath instance pod headless
    relpath="$(project_relpath "$project_path")"
    instance="$(generate_instance_name "$stack" "$project_path")"
    pod="$instance"                                   # the pod takes the same base name (§13)
    headless="${HARNESSED_HEADLESS:-false}"

    local mise_init="source ~/.bashrc && mise trust -a 2>/dev/null"
    local net="${HARNESSED_NET:-harnessed-net}"

    # --fresh: tear down any existing pod/instance before recreate — no state bleed (D-11).
    if [ "$fresh" = "true" ]; then
        print_info "--fresh: tearing down existing pod/instance for $instance"
        "$CONTAINER_RUNTIME" pod rm -f "$pod" >/dev/null 2>&1 || true
        "$CONTAINER_RUNTIME" rm -f "$instance" >/dev/null 2>&1 || true
    fi

    # Re-attach to an already-running instance (interactive only; like transparent).
    if [ "$headless" != "true" ] && container_running "$instance"; then
        print_info "Attaching to running instance: $instance"
        "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && claude"
        stop_if_last_session "$instance" "$relpath"
        return 0
    fi

    print_info "Creating isolated pod: $pod (harness + hatago)"
    print_info "Project: $project_path -> $CONTAINER_HOME/$relpath"

    # §4a host-integration mounts (reused verbatim — D-16): userns/firewall/agents/signing/project.
    local MOUNT_ARGS=()
    harnessed_host_integration_mounts "$project_path" "$relpath"
    # §4b isolated auth: ro credential + generated token-free stub (D-07).
    harnessed_isolated_auth_mounts "$instance"
    # Config source = the committed profile ONLY (no host config layer — unlike transparent).
    # Copy-on-start into a per-instance state dir and mount THAT rw: the committed profile is the
    # immutable template, so the running harness never writes runtime state (projects/, backups/,
    # caches) or the ro-credential mountpoint stub back into the version-controlled tree
    # (reproducibility + credential hygiene, T-02-07/T-02-04). Refreshed every (re)create.
    local run_claude="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$instance/.claude"
    rm -rf "$run_claude"
    mkdir -p "$(dirname "$run_claude")"
    cp -a "$profile_dir/.claude" "$run_claude"
    MOUNT_ARGS+=( -v "$run_claude:$CONTAINER_HOME/.claude:rw" )

    # Pod network: harnessed-net is the DEFAULT for isolated stacks (plan 04-01 / SVC-02) so
    # pod members resolve shared services by DNS name. The $net var honors the override env if
    # set, otherwise defaults to harnessed-net. Members still reach hatago at
    # localhost:3535 (shared pod netns) — the named bridge is ADDITIVE, not a replacement.
    ensure_named_net "$net"
    local pod_net_args=( --network "$net" )

    # Compose the pod (harness + hatago share the netns). keep-id maps the container user to the
    # host UID so mounted project/profile/credential paths are owned correctly. userns is a
    # POD-level property (set on the infra container); pod MEMBERS must NOT pass --userns, so it
    # is stripped from the member args below.
    "$CONTAINER_RUNTIME" pod create --name "$pod" --userns=keep-id "${pod_net_args[@]}" >/dev/null

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

    # hatago member: serve ONE Streamable-HTTP endpoint on :3535 from the mounted per-stack
    # config (which baked stdio servers to expose; the image CMD is overridden to add --config).
    "$CONTAINER_RUNTIME" run -d --pod "$pod" --name "${instance}-hatago" \
        -v "$profile_dir/hatago.config.json:$CONTAINER_HOME/hatago.config.json:ro" \
        "$HARNESSED_HATAGO_IMAGE" \
        hatago serve --http --port "$HATAGO_PORT" --config "$CONTAINER_HOME/hatago.config.json" >/dev/null

    # harness member: the claude container — profile-only config, §4a + isolated §4b mounts.
    # Strip --userns=keep-id from the member args (inherited from the pod; illegal on a member).
    local member_args=() _arg
    for _arg in "${MOUNT_ARGS[@]}"; do
        [ "$_arg" = "--userns=keep-id" ] && continue
        member_args+=( "$_arg" )
    done
    "$CONTAINER_RUNTIME" run -d --pod "$pod" --name "$instance" "${member_args[@]}" \
        "$HARNESSED_CLAUDE_IMAGE" sleep infinity >/dev/null

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
        return 0
    fi

    # Interactive attach (host-native TTY). Load ONLY the profile's hatago MCP endpoint via
    # --mcp-config + --strict-mcp-config: this is what makes claude actually connect to hatago
    # (a profile-only ~/.claude/.mcp.json is otherwise NOT read by claude) AND keeps isolation —
    # --strict-mcp-config ignores every other MCP source, so the user's account-synced servers
    # (claude.ai remote MCP) never leak into the isolated instance.
    local mcp_cfg="$CONTAINER_HOME/.claude/.mcp.json"
    "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
        bash -l -c "$mise_init && claude --mcp-config '$mcp_cfg' --strict-mcp-config"
    stop_if_last_session "$instance" "$relpath"
    print_success "Instance session ended"
}
