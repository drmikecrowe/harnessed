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

# new_stack <stack> [harness] [recipes]: scaffold stacks/<stack>/stack.yaml (CLI-02).
# Validates harness ∈ {claude, omp} (hard error otherwise — P-04-09), refuses to overwrite an
# existing stack (P-04-08), and writes the tracer-time manifest shape (name/config/harness/
# recipes). Recipes need NOT pre-exist (warn, don't fail) — a recipe can be authored after the
# stack, so absence is a warning, not an error (P-04-09).
new_stack() {
    local stack="$1" harness="${2:-claude}" recipes="${3:-}"
    case "$harness" in
        claude|omp) ;;
        *) print_error "unknown harness: $harness (claude|omp)"; exit 1 ;;
    esac
    local stack_dir="$HARNESSED_DIR/stacks/$stack"
    [ -f "$stack_dir/stack.yaml" ] && { print_error "stack '$stack' already exists"; exit 1; }
    mkdir -p "$stack_dir"
    # Comma-joined "a,b,c" → inline-array "a, b, c" (the stack.yaml convention; normalize
    # spacing first so "a, b" and "a ,b" all land as "a, b"). Empty → "[]".
    local r="$recipes"
    r="${r//, /,}"; r="${r// ,/,}"
    local recipes_yaml="[]"
    [ -n "$r" ] && recipes_yaml="[${r//,/, }]"
    cat > "$stack_dir/stack.yaml" <<EOF
# Stack: $stack — scaffolded by harnessed new.
name: $stack
config: isolated      # isolated (default) | transparent
harness: $harness     # claude | omp  (exactly one)
recipes: $recipes_yaml
EOF
    # Warn (don't fail) on recipes that don't exist yet — authorable after the stack.
    local rec
    for rec in ${r//,/ }; do
        [ -d "$HARNESSED_DIR/recipes/$rec" ] || print_warning "recipe '$rec' not found under recipes/ (author it before building)"
    done
    print_success "scaffolded stacks/$stack/stack.yaml"
}
