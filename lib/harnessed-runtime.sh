#!/usr/bin/env bash
# lib/harnessed-runtime.sh — container-runtime abstraction (provider-agnostic isolated mode).
#
# harnessed targets multiple OCI runtimes. They diverge on two things this lib hides behind a small
# provider-neutral vocabulary so the launchers/CLI stay runtime-independent:
#
#   1. How a multi-container "group" that SHARES a network namespace is expressed. The isolated
#      stack = harness container + hatago sharing localhost:$HATAGO_PORT (the harness's MCP config
#      points at http://localhost:3535/mcp).
#        - podman → a POD (`pod create` + `run --pod`); rootless uid via `--userns=keep-id` on the pod.
#        - docker → a SHARED NETNS: run hatago FIRST, then run the harness with
#          `--network container:<hatago>` so it joins hatago's netns (same localhost). Rootless docker
#          remaps uids daemon-side; `--userns=keep-id` does not exist there and is omitted.
#   2. Small CLI-surface differences (`network exists`/`volume exists` are podman-only → docker uses
#      `inspect`; group enumeration is `pod ls` on podman vs name-filtered `ps` on docker).
#
# Apple `container` has NO shared-netns / pod equivalent (one VM + IP per container); it needs a
# named-network + dynamic MCP endpoint and is tracked as a separate follow-up — NOT handled here.
#
# Expects CONTAINER_RUNTIME (set by detect_runtime in harnessed-common.sh) and, for placement
# helpers, HATAGO member naming convention "<instance>-hatago".

# True when the runtime expresses groups as first-class pods (podman) rather than shared-netns.
rt_uses_pods() { [ "${CONTAINER_RUNTIME:-}" = "podman" ]; }

# uid-mapping run args for host-uid ownership of bind mounts. Echoes 0+ tokens; expand UNQUOTED.
#   podman rootless: --userns=keep-id maps the container user → the host uid.
#   docker rootless: the daemon remaps uids; --userns=keep-id is invalid → emit nothing.
rt_userns_args() {
    case "${CONTAINER_RUNTIME:-}" in
        podman) printf '%s' "--userns=keep-id" ;;
        *) : ;;
    esac
}

# Create the shared-netns "group" for an isolated instance.
#   podman: a pod (carries the userns + the optional network); members join with --pod.
#   docker: no-op — the netns is owned by the hatago member (created first by the caller).
# Usage: rt_group_create <instance> <pod> [extra pod/net args...]
rt_group_create() {
    local instance="$1" pod="$2"; shift 2
    if rt_uses_pods; then
        "$CONTAINER_RUNTIME" pod create --name "$pod" --userns=keep-id "$@" >/dev/null
    fi
}

# Placement args for the HATAGO member (the netns owner under docker). Echoes tokens; expand unquoted.
#   podman: --pod <pod>
#   docker: optional --network <HARNESSED_NET> (else the default bridge)
# Usage: rt_hatago_placement <instance> <pod>
rt_hatago_placement() {
    local instance="$1" pod="$2"
    if rt_uses_pods; then
        printf '%s %s' "--pod" "$pod"
    elif [ -n "${HARNESSED_NET:-}" ]; then
        printf '%s %s' "--network" "$HARNESSED_NET"
    fi
}

# Placement args for the HARNESS member. Echoes tokens; expand unquoted.
#   podman: --pod <pod>
#   docker: --network container:<instance>-hatago  → joins hatago's netns (localhost:3535 reaches it)
# Usage: rt_harness_placement <instance> <pod>
rt_harness_placement() {
    local instance="$1" pod="$2"
    if rt_uses_pods; then
        printf '%s %s' "--pod" "$pod"
    else
        printf '%s %s' "--network" "container:${instance}-hatago"
    fi
}

# Tear down an isolated instance's group (all members). Idempotent; swallows absence.
# Usage: rt_group_teardown <instance> <pod>
rt_group_teardown() {
    local instance="$1" pod="$2"
    if rt_uses_pods; then
        "$CONTAINER_RUNTIME" pod rm -f "$pod" >/dev/null 2>&1 || true
        "$CONTAINER_RUNTIME" rm -f "$instance" >/dev/null 2>&1 || true
    else
        "$CONTAINER_RUNTIME" rm -f "$instance" "${instance}-hatago" >/dev/null 2>&1 || true
    fi
}

# Network/volume existence (podman has `... exists`; docker uses `inspect`).
rt_network_exists() {
    if rt_uses_pods; then "$CONTAINER_RUNTIME" network exists "$1" 2>/dev/null
    else "$CONTAINER_RUNTIME" network inspect "$1" >/dev/null 2>&1; fi
}
rt_volume_exists() {
    if rt_uses_pods; then "$CONTAINER_RUNTIME" volume exists "$1" 2>/dev/null
    else "$CONTAINER_RUNTIME" volume inspect "$1" >/dev/null 2>&1; fi
}

# Enumerate the PRIMARY harness-member names for a stack (the instances, NOT the -hatago members),
# newline-separated. Used by `harnessed list/stop/rm`. Pass "running" as the 2nd arg to restrict to
# running groups (so `pod stop`/`stop` never lands on an already-stopped group under set -e).
#   podman: pods are named after the instance (members live inside) → `pod ls`.
#   docker: containers are flat → `ps` filtered by the instance name prefix, minus the -hatago peers.
# Usage: rt_group_names <name-prefix> [running]   (e.g. "harnessed-<stack>-")
rt_group_names() {
    local prefix="$1" only="${2:-}"
    local statusflt=()
    [ "$only" = "running" ] && statusflt=(--filter status=running)
    if rt_uses_pods; then
        "$CONTAINER_RUNTIME" pod ls --filter "name=${prefix}" "${statusflt[@]}" --format '{{.Name}}'
    else
        "$CONTAINER_RUNTIME" ps -a --filter "name=${prefix}" "${statusflt[@]}" --format '{{.Names}}' \
            | grep -v -- '-hatago$' || true
    fi
}
