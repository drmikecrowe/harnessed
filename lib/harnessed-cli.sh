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
    done < <(rt_group_names "harnessed-${stack}-" running)
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
    done < <(rt_group_names "harnessed-${stack}-")
    [ "$matched" = true ] || print_info "No instances to remove for stack '$stack'"
}

# new_stack <stack> [harness] [recipes]: scaffold stacks/<stack>/stack.yaml (CLI-02).
# Validates harness ∈ {claude, omp, opencode} (hard error otherwise — P-04-09), refuses to overwrite
# an existing stack (P-04-08), and writes the tracer-time manifest shape (name/config/harness/
# recipes). Recipes need NOT pre-exist (warn, don't fail) — a recipe can be authored after the
# stack, so absence is a warning, not an error (P-04-09).
new_stack() {
    local stack="$1" harness="${2:-claude}" recipes="${3:-}"
    case "$harness" in
        claude|omp|opencode|gemini|antigravity|codex) ;;
        *) print_error "unknown harness: $harness (claude|omp|opencode|gemini|antigravity|codex)"; exit 1 ;;
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
harness: $harness     # claude | omp | opencode | gemini | antigravity | codex  (exactly one)
recipes: $recipes_yaml
EOF
    # Warn (don't fail) on recipes that don't exist yet — authorable after the stack.
    local rec
    for rec in ${r//,/ }; do
        [ -d "$HARNESSED_DIR/recipes/$rec" ] || print_warning "recipe '$rec' not found under recipes/ (author it before building)"
    done
    print_success "scaffolded stacks/$stack/stack.yaml"
}

# install_stack <stack>: write an executable ~/.local/bin/<stack> launcher shim (CLI-03, design
# §13) so a stack is launchable by name from any cwd. The shim is generated from a FIXED template
# — only the stack name + the absolute path to `harnessed` are interpolated, so there is no
# injection vector (P-04-08); it is written with the user's umask (never forced world-writable).
# Re-running install regenerates it (the path is re-resolved, so a moved repo self-heals).
install_stack() {
    local stack="$1"
    [ -f "$HARNESSED_DIR/stacks/$stack/stack.yaml" ] || { print_error "unknown stack: $stack"; exit 1; }
    local BIN_DIR="${HARNESSED_BIN_DIR:-$HOME/.local/bin}"
    mkdir -p "$BIN_DIR"
    local harness_path="$HARNESSED_DIR/harnessed"
    cat > "$BIN_DIR/$stack" <<EOF
#!/usr/bin/env bash
# generated by harnessed install $stack
HARNESSED_PATH="$harness_path"
exec "\$HARNESSED_PATH" "$stack" "\$@"
EOF
    chmod +x "$BIN_DIR/$stack"
    print_success "installed $stack → $BIN_DIR/$stack"
}

# uninstall_stack <stack>: remove the launcher shim written by install_stack (CLI-03).
uninstall_stack() {
    local stack="$1"
    local BIN_DIR="${HARNESSED_BIN_DIR:-$HOME/.local/bin}"
    rm -f "$BIN_DIR/$stack"
    print_success "removed $BIN_DIR/$stack"
}
