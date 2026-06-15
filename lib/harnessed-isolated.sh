#!/usr/bin/env bash
# harnessed — isolated stack launcher.
#
# isolated = "clean room with exactly what I picked": the config layer (skills/commands/hooks/
# agents/rules/.mcp.json/settings.json) comes ONLY from the assembled, committed
# profiles/<stack>/.claude tree — NOTHING from host config (§2/§4b, MODE-03). Auth is seeded by
# a read-only ~/.claude/.credentials.json mount + a generated token-free .claude.json stub
# (lib/harnessed-isolated-config.sh, D-07/AUTH-02).
#
# The stack is a podman POD (harness container + hatago) on harnessed-net (D-05). Pod members
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

HARNESSED_NET="${HARNESSED_NET:-harnessed-net}"
HATAGO_PORT="${HATAGO_PORT:-3535}"

# harnessed_isolated <stack> <project_path> [fresh]
harnessed_isolated() {
    local stack="$1" project_path="$2" fresh="${3:-false}"

    . "$HARNESSED_DIR/lib/harnessed-mounts.sh"
    . "$HARNESSED_DIR/lib/harnessed-isolated-config.sh"

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

    print_info "Creating isolated pod: $pod (harness + hatago) on $HARNESSED_NET"
    print_info "Project: $project_path -> $CONTAINER_HOME/$relpath"

    # §4a host-integration mounts (reused verbatim — D-16): userns/firewall/agents/signing/project.
    local MOUNT_ARGS=()
    harnessed_host_integration_mounts "$project_path" "$relpath"
    # §4b isolated auth: ro credential + generated token-free stub (D-07).
    harnessed_isolated_auth_mounts "$instance"
    # Config source = the committed profile ONLY (mounted rw at the harness's config dir). Unlike
    # transparent, host config is never mounted here — the profile is the sole config layer.
    MOUNT_ARGS+=( -v "$profile_dir/.claude:$CONTAINER_HOME/.claude:rw" )

    # Ensure the pod network exists (shared netns → harness reaches hatago at localhost).
    "$CONTAINER_RUNTIME" network exists "$HARNESSED_NET" 2>/dev/null \
        || "$CONTAINER_RUNTIME" network create "$HARNESSED_NET" >/dev/null

    # Compose the pod (harness + hatago share the netns).
    "$CONTAINER_RUNTIME" pod create --name "$pod" --network "$HARNESSED_NET" >/dev/null

    # hatago member: serve ONE Streamable-HTTP endpoint on :3535 from the mounted per-stack
    # config (which baked stdio servers to expose; the image CMD is overridden to add --config).
    "$CONTAINER_RUNTIME" run -d --pod "$pod" --name "${instance}-hatago" \
        -v "$profile_dir/hatago.config.json:$CONTAINER_HOME/hatago.config.json:ro" \
        "$HARNESSED_HATAGO_IMAGE" \
        hatago serve --http --port "$HATAGO_PORT" --config "$CONTAINER_HOME/hatago.config.json" >/dev/null

    # harness member: the claude container — profile-only config, §4a + isolated §4b mounts.
    "$CONTAINER_RUNTIME" run -d --pod "$pod" --name "$instance" "${MOUNT_ARGS[@]}" \
        "$HARNESSED_CLAUDE_IMAGE" sleep infinity >/dev/null

    # Egress firewall on the harness container (NET_ADMIN); shared pod netns → covers hatago too.
    apply_firewall "$instance"

    # Headless (capability test, 02-03): leave the pod running for podman-exec introspection.
    if [ "$headless" = "true" ]; then
        print_success "Isolated pod running headless: $instance (hatago: ${instance}-hatago)"
        return 0
    fi

    # Interactive attach (host-native TTY). .mcp.json points at http://localhost:3535/mcp.
    "$CONTAINER_RUNTIME" exec -it -e "TERM=xterm-256color" -w "$CONTAINER_HOME/$relpath" "$instance" \
        bash -l -c "$mise_init && claude"
    stop_if_last_session "$instance" "$relpath"
    print_success "Instance session ended"
}
