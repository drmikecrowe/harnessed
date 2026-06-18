#!/usr/bin/env bash
# harnessed — shared helpers (runtime detection, image build, logging, instance lifecycle).
# Sourced by the `harnessed` bootstrap and stack launchers.
# Host-native: every podman/docker command runs on the HOST. No daemon-in-container, no API socket.
#
# Expects HARNESSED_DIR (the resolved repo dir) to be exported by the bootstrap before use.

# --- Colors / logging ------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# --- Identity --------------------------------------------------------------
HARNESSED_BASE_IMAGE="harnessed-base:latest"
HARNESSED_CLAUDE_IMAGE="harnessed-claude:latest"
# omp harness image (FROM harnessed-base + omp + pre-installed claude-hooks-bridge; design §6/§8).
# Lazy-built by ensure_omp_image ONLY for omp stacks (plan 04-03 / HRN-01) — claude-only users
# are never forced to build omp.
HARNESSED_OMP_IMAGE="harnessed-omp:latest"
# hatago MCP hub image (baked hub + light stdio servers; design §6 / D-06).
HARNESSED_HATAGO_IMAGE="harnessed-hatago:latest"
# Build-time assembler image (emit-only; design §15 / D-12). Built on first `harnessed build <stack>`.
HARNESSED_TOOLS_IMAGE="harnessed-tools:latest"
# In-container home — the legible session-slug root (design §15 / D-06).
CONTAINER_HOME="/home/harnessed"
NO_FIREWALL="${NO_FIREWALL:-false}"

# --- Runtime detection (prefer podman, fall back to docker) ----------------
detect_runtime() {
    if command -v podman >/dev/null 2>&1; then
        CONTAINER_RUNTIME="podman"
    elif command -v docker >/dev/null 2>&1; then
        CONTAINER_RUNTIME="docker"
    else
        print_error "Neither podman nor docker found on PATH. Install podman (recommended) or docker."
        exit 1
    fi
}

# --- Images (built and run on the HOST) ------------------------------------
image_exists() { "$CONTAINER_RUNTIME" image inspect "$1" >/dev/null 2>&1; }

# Build the base, claude, then hatago image via host `podman build`. $1=force (true|false).
build_images() {
    local force="${1:-false}"

    # Seed extra-tools.txt from the default on first build (mirrors container.sh).
    if [ ! -f "$HARNESSED_DIR/extra-tools.txt" ]; then
        if [ -f "$HARNESSED_DIR/extra-tools.default.txt" ]; then
            cp "$HARNESSED_DIR/extra-tools.default.txt" "$HARNESSED_DIR/extra-tools.txt"
            print_info "Created extra-tools.txt from default. Edit it to customize installed tools."
        else
            : > "$HARNESSED_DIR/extra-tools.txt"
            print_info "Created empty extra-tools.txt."
        fi
    fi

    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_BASE_IMAGE"; then
        print_info "Building $HARNESSED_BASE_IMAGE ..."
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_BASE_IMAGE" \
            -f "$HARNESSED_DIR/base/Dockerfile.harnessed-base" "$HARNESSED_DIR"
    fi
    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_CLAUDE_IMAGE"; then
        print_info "Building $HARNESSED_CLAUDE_IMAGE ..."
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_CLAUDE_IMAGE" \
            -f "$HARNESSED_DIR/base/Dockerfile.harnessed-claude" "$HARNESSED_DIR"
    fi
    if [ "$force" = "true" ] || ! image_exists "$HARNESSED_HATAGO_IMAGE"; then
        print_info "Building $HARNESSED_HATAGO_IMAGE ..."
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_HATAGO_IMAGE" \
            -f "$HARNESSED_DIR/base/Dockerfile.hatago" "$HARNESSED_DIR"
    fi
    print_success "harnessed images ready"
}

# Ensure the emit-only assembler image exists; build it from tools/Dockerfile on first use.
ensure_tools_image() {
    if ! image_exists "$HARNESSED_TOOLS_IMAGE"; then
        print_info "Building $HARNESSED_TOOLS_IMAGE ..."
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_TOOLS_IMAGE" \
            -f "$HARNESSED_DIR/tools/Dockerfile" "$HARNESSED_DIR/tools"
    fi
}

# Assemble a stack into a committed profile + build its hatago image (design §15, D-12).
#   1. ensure the emit-only assembler image exists
#   2. run it (mounted build dir) to EMIT profiles/<stack>/ + hatago.config.json — never the daemon
#   3. host `podman build` the hatago image from the emitted/baked Dockerfile
# $1 = stack name. ROOT (${HARNESSED_ROOT:-$HARNESSED_DIR}) resolves stacks/ + recipes/ and is the
# profile build dir. --root lets a fixture stack exercise the full wired path without polluting the
# real stacks/ + recipes/ (PORT-01 / BLOCKER-2(b)).
build_stack() {
    local stack="$1"
    local ROOT="${HARNESSED_ROOT:-$HARNESSED_DIR}"
    if [ -z "$stack" ]; then print_error "build_stack: stack name required"; return 1; fi
    if [ ! -f "$ROOT/stacks/$stack/stack.yaml" ]; then
        print_error "Unknown stack: $stack (no $ROOT/stacks/$stack/stack.yaml)"; return 1
    fi
    ensure_tools_image

    print_info "Assembling stack '$stack' (emit-only) under $ROOT ..."
    # EMIT step: the assembler only reads/writes the mounted ROOT; it never drives podman.
    # Fail-fast: a recipe lint / collision abort (non-zero) propagates via errexit before emit.
    "$CONTAINER_RUNTIME" run --rm --userns=keep-id \
        -v "$ROOT":"$ROOT" -w "$ROOT" \
        "$HARNESSED_TOOLS_IMAGE" assemble "$stack" --root "$ROOT" --build-dir "$ROOT"

    # [BLD-02a] SCOPED source/Python scan (emit-compatible): the tools image scans THIS stack's
    # recipe dirs + emitted profile only — never the whole repo — so a committed fixture cannot
    # red-line an unrelated build. Capture the exit safely: the launcher runs set -euo pipefail, so
    # a bare scanner pipeline would abort on osv-scanner's non-zero exit (Constraint 9 / a963a69).
    print_info "Running supply-chain source scan for stack '$stack' ..."
    local src_rc=0
    # [SEC-02] Forward scanner tokens ONLY when set in the launcher env (raw env, varlock-resolved,
    # or ~/.config/configstore). `${VAR:-}` is set -euo pipefail-safe (a bare $SNYK_TOKEN aborts on
    # unset — Constraint 9); the tools image's scan.py does the env-presence gate (warn-and-skip on
    # absence). NEVER prompt for a token (SEC-02 contract).
    local TOKEN_ARGS=()
    [ -n "${SNYK_TOKEN:-}" ] && TOKEN_ARGS+=( -e "SNYK_TOKEN=$SNYK_TOKEN" )
    [ -n "${SOCKET_SECURITY_API_KEY:-}" ] && TOKEN_ARGS+=( -e "SOCKET_SECURITY_API_KEY=$SOCKET_SECURITY_API_KEY" )
    "$CONTAINER_RUNTIME" run --rm --userns=keep-id \
        "${TOKEN_ARGS[@]}" \
        -v "$ROOT":"$ROOT" -w "$ROOT" \
        "$HARNESSED_TOOLS_IMAGE" scan "$stack" --root "$ROOT" --build-dir "$ROOT" || src_rc=$?
    if [ "$src_rc" -ne 0 ]; then
        print_error "supply-chain source scan failed for stack '$stack' (HIGH+ finding)"
        return 1
    fi

    # BUILD step: the HOST builds the hatago image from base/Dockerfile.hatago (always the real repo).
    print_info "Building $HARNESSED_HATAGO_IMAGE for stack '$stack' ..."
    "$CONTAINER_RUNTIME" build -t "$HARNESSED_HATAGO_IMAGE" \
        -f "$HARNESSED_DIR/base/Dockerfile.hatago" "$HARNESSED_DIR"

    # [BLD-02b] Image scan (host-driven, mirrors `harnessed test`): podman save → osv image scan in
    # a throwaway tools container. No daemon socket mounted; the save tar is temp + cleaned up.
    print_info "Running supply-chain image scan for $HARNESSED_HATAGO_IMAGE ..."
    local img_tar img_rc=0
    img_tar="$(mktemp --suffix=.tar)"
    "$CONTAINER_RUNTIME" save "$HARNESSED_HATAGO_IMAGE" -o "$img_tar"
    "$CONTAINER_RUNTIME" run --rm -v "$img_tar":"$img_tar":ro \
        "$HARNESSED_TOOLS_IMAGE" scan-image "$img_tar" || img_rc=$?
    rm -f "$img_tar"
    if [ "$img_rc" -ne 0 ]; then
        print_error "supply-chain image scan failed for $HARNESSED_HATAGO_IMAGE (HIGH+ finding)"
        return 1
    fi

    print_success "Stack '$stack' assembled → profiles/$stack/ + $HARNESSED_HATAGO_IMAGE (scans clean)"
}

# Build images on first run if missing (auto-build; D-04). Ensures BOTH the claude harness image
# and the hatago hub image, so an isolated stack's pod has its hatago member available.
ensure_images() {
    if ! image_exists "$HARNESSED_CLAUDE_IMAGE" || ! image_exists "$HARNESSED_HATAGO_IMAGE"; then
        print_warning "harnessed images not found. Building (first run)…"
        build_images false
    fi
}

# Ensure the omp harness image exists; build it from base/Dockerfile.harnessed-omp on first use.
# LAZY (plan 04-03 / HRN-01): called by the isolated launcher ONLY for `harness: omp` stacks, so
# claude-only users are never forced to build omp (which pulls omp + the bridge over the network).
# Mirrors ensure_tools_image. The base image is a prerequisite — build_images covers it.
ensure_omp_image() {
    if ! image_exists "$HARNESSED_OMP_IMAGE"; then
        if ! image_exists "$HARNESSED_BASE_IMAGE"; then
            print_warning "harnessed-base not found. Building base first…"
            build_images false
        fi
        print_info "Building $HARNESSED_OMP_IMAGE ..."
        "$CONTAINER_RUNTIME" build -t "$HARNESSED_OMP_IMAGE" \
            -f "$HARNESSED_DIR/base/Dockerfile.harnessed-omp" "$HARNESSED_DIR"
    fi
}

# --- Instance lifecycle ----------------------------------------------------
container_exists()  { "$CONTAINER_RUNTIME" container inspect "$1" >/dev/null 2>&1; }
container_running() { [ "$("$CONTAINER_RUNTIME" container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }
# Isolated stacks run as a pod named after the instance (harnessed-<stack>-<projhash>); transparent
# has no pod. `pod exists` is a podman concept (docker has none) — the 2>/dev/null swallows the
# docker error so the caller cleanly falls through to the single-container path.
pod_exists() { "$CONTAINER_RUNTIME" pod exists "$1" 2>/dev/null; }

# Stable instance name: harnessed-<stack>-<projhash>.
generate_instance_name() {
    local stack="$1" project_path="${2%/}" hash
    if command -v shasum >/dev/null 2>&1; then
        hash=$(echo -n "$project_path" | shasum | cut -c1-8)
    elif command -v sha1sum >/dev/null 2>&1; then
        hash=$(echo -n "$project_path" | sha1sum | cut -c1-8)
    else
        print_error "Neither shasum nor sha1sum available; cannot derive instance name"
        exit 1
    fi
    echo "harnessed-${stack}-${hash}"
}

# Legible project relpath under the host $HOME → /home/harnessed/<relpath> (D-06).
project_relpath() {
    local p="${1%/}"
    if [[ "$p" == "$HOME/"* ]]; then echo "${p#"$HOME"/}"; else basename "$p"; fi
}

list_instances() {
    print_info "Harnessed instances:"
    "$CONTAINER_RUNTIME" ps -a --filter "name=harnessed-" \
        --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}"
}

stop_instance() {
    local name="$1"
    # Isolated: the pod shares the instance name and bundles the harness + hatago members.
    if pod_exists "$name"; then
        print_info "Stopping pod: $name"
        "$CONTAINER_RUNTIME" pod stop -t 0 "$name" >/dev/null
        print_success "Pod stopped"
        return 0
    fi
    container_exists "$name" || { print_error "Instance does not exist: $name"; exit 1; }
    if container_running "$name"; then
        print_info "Stopping instance: $name"
        "$CONTAINER_RUNTIME" stop -t 0 "$name"
        print_success "Instance stopped"
    else
        print_warning "Instance is not running: $name"
    fi
}

remove_instance() {
    local name="$1"
    # Isolated: removing the pod tears down all members (harness + hatago + infra).
    if pod_exists "$name"; then
        print_info "Removing pod: $name"
        "$CONTAINER_RUNTIME" pod rm -f "$name" >/dev/null
        print_success "Pod removed"
        return 0
    fi
    container_exists "$name" || { print_error "Instance does not exist: $name"; exit 1; }
    container_running "$name" && "$CONTAINER_RUNTIME" stop -t 0 "$name"
    print_info "Removing instance: $name"
    "$CONTAINER_RUNTIME" rm "$name"
    print_success "Instance removed"
}

clean_instances() {
    print_info "Removing all stopped harnessed instances..."
    local ids
    ids=$("$CONTAINER_RUNTIME" ps -a --filter "name=harnessed-" --filter "status=exited" --quiet)
    if [ -z "$ids" ]; then print_info "No stopped harnessed instances to remove"; return; fi
    # shellcheck disable=SC2086
    "$CONTAINER_RUNTIME" rm $ids
    print_success "Cleanup complete"
}

# Stop the instance only if no other interactive sessions for the project are attached.
stop_if_last_session() {
    local instance="$1" relpath="$2" other
    other=$(ps ax -o command= | awk \
        -v name="$instance" -v runtime="$CONTAINER_RUNTIME" -v chome="$CONTAINER_HOME" -v rel="$relpath" '
        BEGIN { count=0 }
        {
            if (index($0, runtime " exec") && index($0, "-it") && index($0, name) &&
                index($0, "-w " chome "/" rel)) { count++ }
        }
        END { print count }')
    if [ "${other:-0}" -eq 0 ]; then
        "$CONTAINER_RUNTIME" stop -t 0 "$instance" >/dev/null 2>&1 &
        disown 2>/dev/null || true
    else
        print_info "Skipping stop; $other other session(s) still attached"
    fi
}

# Apply the egress firewall inside an instance (idempotent via /run flag file).
apply_firewall() {
    local instance="$1"; shift
    local extra=("$@")
    [ "$NO_FIREWALL" = "true" ] && return 0
    "$CONTAINER_RUNTIME" exec "$instance" test -f /run/egress-firewall-active 2>/dev/null && return 0
    print_info "Applying egress firewall..."
    "$CONTAINER_RUNTIME" exec --user root "$instance" \
        /bin/bash /usr/local/sbin/egress-firewall "${extra[@]+"${extra[@]}"}" \
        || print_warning "Egress firewall failed to apply (missing NET_ADMIN?)"
}
