#!/usr/bin/env bash
# harnessed — shared service lifecycle (plan 04-01 / SVC-01, SVC-03).
#
# A shared service is its OWN image/container/volume on a host-published port (reachable via
# `host.containers.internal:<port>`; or by DNS name over the `HARNESSED_NET` bridge on
# bridge-capable hosts), with a lifecycle independent of any instance (design §3/§9).
# `svc up|down|list` manages them by name; isolated stacks auto-start declared services
# via ensure_service_up.
#
# Service-scoped persistence: the named volume `<service>-data` survives `svc down` by
# default (that's the value — one memory across instances). `--purge` is the explicit destroy.
#
# Host-native: every podman/docker command runs on the HOST. No --privileged, no daemon
# socket, no DooD (T-04-04). Service images are scanned by BLD-02 on first build (T-04-02).
#
# Expects CONTAINER_RUNTIME + HARNESSED_DIR (set by harnessed-common.sh, sourced by the
# launcher before this lib).

# Ensure a named container network exists (idempotent). Used by ensure_harnessed_net and the
# isolated launcher's HARNESSED_NET override (plan 04-01 Task 3).
ensure_named_net() {
    local net="$1"
    "$CONTAINER_RUNTIME" network exists "$net" 2>/dev/null \
        || "$CONTAINER_RUNTIME" network create "$net" >/dev/null
}

# Ensure the default shared bridge exists (harnessed-net). Idempotent.
ensure_harnessed_net() {
    ensure_named_net harnessed-net
}

# Read a scalar value from services/<name>/service.yaml (flat `key: value` pairs).
# The manifest is flat scalars, so a lightweight sed parse keeps the host dependency-free
# (no YAML lib needed on the host).
_svc_yaml_val() {
    local service="$1" key="$2"
    sed -n "s/^${key}: *//p" "$HARNESSED_DIR/services/$service/service.yaml" 2>/dev/null | head -1 | tr -d '"' | tr -d "'"
}

# Build a service image from services/<name>/Dockerfile + run the BLD-02 image scan (T-04-02).
build_service_image() {
    local service="$1"
    local SVC_DIR="$HARNESSED_DIR/services/$service"
    local image
    image="$(_svc_yaml_val "$service" image)"
    [ -n "$image" ] || { print_error "service '$service': no image in service.yaml"; return 1; }
    print_info "Building service image: $image"
    "$CONTAINER_RUNTIME" build -t "$image" -f "$SVC_DIR/Dockerfile" "$SVC_DIR"

    # [BLD-02b] Image scan (T-04-02): podman save → scan-image in the tools container.
    ensure_tools_image
    local img_tar img_rc=0
    img_tar="$(mktemp --suffix=.tar)"
    "$CONTAINER_RUNTIME" save "$image" -o "$img_tar"
    "$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro \
        "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar" || img_rc=$?
    rm -f "$img_tar"
    if [ "$img_rc" -ne 0 ]; then
        print_error "supply-chain image scan failed for $image (HIGH+ finding)"
        return 1
    fi
    print_success "Service image built + scanned: $image"
}

# svc_up <service> — start a service-scoped shared sidecar (idempotent).
#
# Ensures the image (builds from services/<name>/Dockerfile if absent), creates the named
# volume if absent, publishes its port to 0.0.0.0 (rootless; peers reach it via
# `host.containers.internal:<port>`) with `--label harnessed-service=<name>` +
# `--userns=keep-id`, then waits for the healthcheck.
svc_up() {
    local service="$1"
    local SVC_DIR="$HARNESSED_DIR/services/$service"
    [ -f "$SVC_DIR/service.yaml" ] \
        || { print_error "unknown service: $service (no $SVC_DIR/service.yaml)"; return 1; }

    local image volume data_path
    image="$(_svc_yaml_val "$service" image)"
    volume="$(_svc_yaml_val "$service" volume)"
    [ -n "$volume" ] || volume="${service}-data"
    data_path="$(_svc_yaml_val "$service" data_path)"
    [ -n "$data_path" ] || data_path="/data"

    # Idempotent: no-op if already running.
    if container_running "$service"; then
        print_info "service '$service' already running"
        return 0
    fi

    # Ensure image (build from Dockerfile if absent; BLD-02 scan on build).
    image_exists "$image" || build_service_image "$service"

    # Ensure the named volume (service-scoped persistence).
    "$CONTAINER_RUNTIME" volume exists "$volume" 2>/dev/null \
        || "$CONTAINER_RUNTIME" volume create "$volume" >/dev/null

    local port
    port="$(_svc_yaml_val "$service" port)"

    print_info "Starting service: $service"
    # Rootless service model (plan 04-01 fix): publish the port to 0.0.0.0 — NO bridge. Rootless
    # bridges are unsupported on most hosts (netavark "create bridge: Operation not supported"),
    # so peer instances/pods reach this service via the host gateway `host.containers.internal:<port>`.
    # The service is a standalone container (not a pod member); its lifecycle is independent of any
    # instance (design §9). HARNESSED_NET remains an explicit opt-in bridge for hosts that support it.
    # [SEC-01] Per-service secret resolution (design §16): a per-service schema at
    # ~/.config/<service>/.env.schema resolves on the HOST via the shared resolve_secret_env
    # (inert when absent). Spread --env-file into the sidecar so op:// secrets reach it as env
    # only; the mode-0600 temp is unlinked right after the -d create reads it (T-05-06).
    . "$HARNESSED_DIR/lib/harnessed-secrets.sh"
    local svc_secret_env svc_resolve_rc=0
    svc_secret_env="$(HARNESSED_SCHEMA="$HOME/.config/$service/.env.schema" resolve_secret_env)" || svc_resolve_rc=$?
    if [ "$svc_resolve_rc" -ne 0 ]; then
        print_error "secret resolution failed for service '$service'; not starting"
        return 1
    fi
    local -a svc_env_args=()
    [ -n "$svc_secret_env" ] && svc_env_args=( --env-file "$svc_secret_env" )
    local svc_run_rc=0
    "$CONTAINER_RUNTIME" run -d \
        -p "$port:$port" \
        --name "$service" \
        --label harnessed-service="$service" \
        --userns=keep-id \
        -v "$volume:$data_path" \
        "${svc_env_args[@]}" \
        "$image" >/dev/null || svc_run_rc=$?
    # [T-05-06] Unlink the resolved env temp right after the -d create reads it (any outcome).
    [ -n "$svc_secret_env" ] && rm -f "$svc_secret_env"
    if [ "$svc_run_rc" -ne 0 ]; then
        print_error "Service '$service' failed to start (run exit $svc_run_rc)"
        return 1
    fi

    # Wait for the healthcheck to pass (up to 30s). If the image has no HEALTHCHECK,
    # fall back to checking the container is running.
    print_info "Waiting for service '$service' healthcheck..."
    local _i status
    for _i in $(seq 1 30); do
        status="$("$CONTAINER_RUNTIME" inspect -f '{{.State.Health.Status}}' "$service" 2>/dev/null || true)"
        case "$status" in
            healthy) break ;;
            "") container_running "$service" && break ;;
        esac
        sleep 1
    done

    if container_running "$service"; then
        print_success "Service '$service' is up (volume: $volume)"
    else
        print_error "Service '$service' failed to start"
        return 1
    fi
}

# svc_down <service> [purge] — stop + remove the container.
#
# The named volume SURVIVES by default (service-scoped persistence — the whole point).
# Pass --purge to remove the volume explicitly.
svc_down() {
    local service="$1" purge="${2:-}"
    local volume
    volume="$(_svc_yaml_val "$service" volume)"
    [ -n "$volume" ] || volume="${service}-data"

    "$CONTAINER_RUNTIME" rm -f "$service" >/dev/null 2>&1 || true

    if [ "$purge" = "--purge" ]; then
        "$CONTAINER_RUNTIME" volume rm "$volume" >/dev/null 2>&1 || true
        print_success "Service '$service' removed (volume '$volume' purged)"
    else
        print_success "Service '$service' stopped (volume '$volume' kept)"
    fi
}

# svc_list — enumerate running harnessed-managed services (by the harnessed-service label).
svc_list() {
    local out
    out="$("$CONTAINER_RUNTIME" ps --filter label=harnessed-service \
        --format '{{.Names}}\t{{.Status}}' 2>/dev/null || true)"
    if [ -z "$out" ]; then
        print_info "No harnessed services running"
        return 0
    fi
    print_info "Harnessed services:"
    printf '%s\n' "$out" | while IFS=$'\t' read -r name status; do
        echo "  $name  $status"
    done
}

# ensure_service_up <service> — thin idempotent wrapper for the isolated launcher.
# An instance starts the declared service if absent; it outlives instances (design §9).
ensure_service_up() {
    svc_up "$1"
}
