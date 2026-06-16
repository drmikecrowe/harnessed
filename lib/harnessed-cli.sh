#!/usr/bin/env bash
# harnessed — first-class CLI operations (design §13).
#
# Sourced by the `harnessed` launcher on the matching subcommand (list/stop/rm/new/install/
# uninstall). The legacy --list/--stop/--remove/--clean flags remain in the launcher for
# back-compat (they dispatch to the per-instance path in lib/harnessed-common.sh); these
# subcommands ADD the §13 surface and operate on stacks/instances BY NAME (CLI-01).
#
# Expects HARNESSED_DIR (exported by the bootstrap) + the common helpers already sourced:
# print_info/print_success/print_error, list_instances, stop_instance, remove_instance,
# generate_instance_name (lib/harnessed-common.sh). Host-native: every podman call runs on host.

# list_all: authored stacks (stacks/*/stack.yaml) THEN running instances (CLI-01).
list_all() {
    print_info "Stacks:"
    local f found=false
    for f in "$HARNESSED_DIR"/stacks/*/stack.yaml; do
        [ -f "$f" ] || continue
        found=true
        printf '  %s\n' "$(basename "$(dirname "$f")")"
    done
    [ "$found" = true ] || print_info "  (no authored stacks)"
    echo
    # list_instances (common.sh) prints its own "Harnessed instances:" header + the ps table.
    list_instances
}

# stop_stack <stack>: stop every RUNNING instance (pod) of a stack. Instance/pod names follow
# the harnessed-<stack>-<projhash> convention (generate_instance_name), so `harnessed-<stack>-`
# matches all of a stack's instances across projects (CLI-01). Filters to RUNNING pods so
# `pod stop` never lands on an already-stopped pod (which some podman versions error on under
# set -e); stop_instance then takes the pod path (stops the whole pod — harness + hatago).
stop_stack() {
    local stack="$1" pod matched=false
    while IFS= read -r pod; do
        [ -n "$pod" ] || continue
        matched=true
        stop_instance "$pod"
    done < <("$CONTAINER_RUNTIME" pod ls --filter "name=harnessed-${stack}-" \
              --filter status=running --format '{{.Name}}')
    [ "$matched" = true ] || print_info "No running instances for stack '$stack'"
}

# rm_stack <stack>: same prefix match, ALL pods (running or stopped) → remove_instance each
# (force-remove works on any state). One pod per instance, so no double-handling of members.
rm_stack() {
    local stack="$1" pod matched=false
    while IFS= read -r pod; do
        [ -n "$pod" ] || continue
        matched=true
        remove_instance "$pod"
    done < <("$CONTAINER_RUNTIME" pod ls --filter "name=harnessed-${stack}-" --format '{{.Name}}')
    [ "$matched" = true ] || print_info "No instances to remove for stack '$stack'"
}
