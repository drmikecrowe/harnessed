#!/usr/bin/env bash
# harnessed — opt-in secrets (varlock + 1Password) + scanner-token auth (plan 05-02 / SEC-01, SEC-03).
#
# Two functions:
#   resolve_secret_env  — detect ~/.config/harnessed/.env.schema (INERT when absent: a single
#                         `[ -f ]` test; no schema ⇒ return 0 ⇒ varlock NEVER invoked, today's
#                         behavior unchanged bit-for-bit). When present, run a throwaway
#                         harnessed-tools container that mounts a writable scratch dir as
#                         $CONTAINER_HOME (the schema ro + the resolved env-file rw + the op
#                         agent socket + the .config data dir), exports `-e HOME=$CONTAINER_HOME`
#                         so `op` resolves the agent socket at the mounted
#                         $CONTAINER_HOME/.1password/agent.sock, runs `varlock load --format env`,
#                         and writes the resolved dotenv to the env-file. Echoes the env-file path
#                         (mode 0600); the caller unlinks it after launch (T-05-06). The host
#                         stays podman-only — varlock/`op` live in the tools image (Pattern 1).
#   auth_scanner        — `harnessed auth snyk|socket` handler. A `--rm -it` tools container with
#                         `-e HOME=$CONTAINER_HOME` + `~/.config` rw-mounted drives the vendor
#                         CLI's own auth so the token writes to the mounted host path (e.g.
#                         ~/.config/configstore/snyk.json). `--rm` guarantees no image layer
#                         captures the token (T-05-07); the HOME override is load-bearing —
#                         without it snyk writes to the unmounted /home/tools/.config and the
#                         token is lost on `--rm` exit.
#
# Host-native: every podman/docker call runs on the HOST. Sourced just-in-time by the launcher
# (`harnessed` `auth)` path) and by `harnessed_isolated` / `build_stack` for `resolve_secret_env`.
#
# Expects CONTAINER_RUNTIME + HARNESSED_DIR + HARNESSED_TOOLS_IMAGE + CONTAINER_HOME (all set by
# lib/harnessed-common.sh, sourced by the launcher before this lib).

# Schema location (XDG). Absent ⇒ INERT (varlock never invoked). Overridable for tests.
: "${HARNESSED_SCHEMA:=$HOME/.config/harnessed/.env.schema}"
export HARNESSED_SCHEMA

# Internal: the mise-managed node install lives in the image at /home/tools; under the
# overridden HOME ($CONTAINER_HOME) the image's mise shims cannot resolve (mise reads
# $HOME/.config/mise/config.toml, which doesn't exist at /home/harnessed). Prepending the
# install dir directly lets the pnpm-global CLIs (varlock/snyk/socket — Node scripts) find
# node without going through mise. No host Node is required (the §15 "podman-only host"
# invariant holds); this just re-points PATH inside the throwaway container.
_HARNESSED_TOOLS_NODE_PATH="/home/tools/.local/share/mise/installs/node/latest/bin"

# resolve_secret_env — detect-and-resolve the host-level .env.schema.
# Stdout: the path to a mode-0600 temp env-file holding the resolved dotenv (caller unlinks
# after launch), or empty when no schema is present (the inert path) / when varlock emitted
# nothing. Returns non-zero only on resolution FAILURE (a present schema that won't resolve).
resolve_secret_env() {
    # INERTNESS GUARANTEE: no schema ⇒ return 0 immediately; varlock is NEVER invoked.
    [ -f "$HARNESSED_SCHEMA" ] || return 0

    print_info "Resolving secrets via varlock (schema: $HARNESSED_SCHEMA) ..." >&2

    # Writable host scratch dir → mounted as $CONTAINER_HOME. Podman otherwise creates
    # /home/harnessed as root (uid 0), which blocks varlock's plugin data writes
    # ($HOME/.config). A host-owned scratch dir + --userns=keep-id gives the container's
    # tools user (uid 1000 == host uid) full write access. Holds the ro schema copy + the rw
    # env-file + the .config data dir + the .1password socket mountpoint.
    local tmpdir
    tmpdir="$(mktemp -d -t harnessed-secrets.XXXX)"
    cp "$HARNESSED_SCHEMA" "$tmpdir/.env.schema"
    : > "$tmpdir/.env.resolved"
    chmod 600 "$tmpdir/.env.resolved"
    mkdir -m 700 "$tmpdir/.config"
    # Pre-create the .1password dir so the agent-socket bind-mount target's parent is host-
    # owned (podman would otherwise create it as root, breaking `rm -rf "$tmpdir"` on cleanup).
    mkdir -m 700 "$tmpdir/.1password"

    # The 1Password agent socket — same transport as lib/harnessed-mounts.sh:22-27 (app-auth,
    # allowAppAuth=true). varlock's @initOp reads SSH_AUTH_SOCK and connects to the desktop app.
    local op_agent="$HOME/.1password/agent.sock"
    local -a agent_args=()
    if [ -S "$op_agent" ]; then
        agent_args+=( -v "$op_agent:$CONTAINER_HOME/.1password/agent.sock" )
        agent_args+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.1password/agent.sock" )
    fi

    # Headless fallback (CLAUDE.md caution: scope narrowly; never export in a shell profile).
    # Forwarded ONLY when already in the launcher env — never prompt, never echo.
    local -a svcacct_args=()
    if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        svcacct_args+=( -e "OP_SERVICE_ACCOUNT_TOKEN=$OP_SERVICE_ACCOUNT_TOKEN" )
    fi

    # Throwaway tools container (Pattern 1, mirrors lib/harnessed-common.sh:106-108):
    #   --rm             → no image layer holds the resolved env (T-05-05)
    #   --userns=keep-id → the scratch-dir files are writable by the tools uid (host uid)
    #   -e HOME=$CONTAINER_HOME → `op` resolves the agent socket at the mounted
    #                       $CONTAINER_HOME/.1password/agent.sock (NOT /home/tools/.1password/…)
    #   varlock load --format env → dotenv (podman --env-file compatible); NOT --format shell,
    #                       whose KEY='value'/`export KEY=…` lines podman parses as literal text
    # The PATH prepend (above) keeps the pnpm-global CLIs resolvable under the new HOME.
    local rc=0 errout
    errout="$("$CONTAINER_RUNTIME" run --rm --userns=keep-id \
        -e "HOME=$CONTAINER_HOME" \
        -v "$tmpdir":"$CONTAINER_HOME":rw \
        "${agent_args[@]}" \
        "${svcacct_args[@]}" \
        --entrypoint bash \
        "$HARNESSED_TOOLS_IMAGE" \
        -lc "export PATH=\"$_HARNESSED_TOOLS_NODE_PATH:\$PATH\"; cd \"\$HOME\" && varlock load --format env | sed -E 's/^([^=]+)=\\\"(.*)\\\"\$/\\1=\\2/' > \"\$HOME/.env.resolved\"")" 2>&1 || rc=$?

    if [ "$rc" -ne 0 ]; then
        rm -rf "$tmpdir"
        print_error "varlock resolution failed (exit $rc):" >&2
        printf '%s\n' "$errout" >&2
        print_error "Confirm the 1Password desktop app is running (agent socket: $op_agent)" >&2
        print_error "or set OP_SERVICE_ACCOUNT_TOKEN (headless). See docs/guides/secrets.md." >&2
        return 1
    fi

    # Move the resolved env out of the scratch dir to a stable path the caller unlinks (T-05-06).
    local final=""
    if [ -s "$tmpdir/.env.resolved" ]; then
        final="$(mktemp -t harnessed-env.XXXX --suffix=.env)"
        chmod 600 "$final"
        mv "$tmpdir/.env.resolved" "$final"
    else
        # varlock succeeded but emitted nothing — schema is valid but resolves no env. Treat
        # as inert (no --env-file to spread); warn so the operator notices.
        print_warning "varlock resolved no env from $HARNESSED_SCHEMA (empty dotenv)" >&2
    fi
    rm -rf "$tmpdir"
    [ -n "$final" ] && echo "$final"
}

# auth_scanner <tool> — `harnessed auth snyk|socket` (SEC-03). Drives the vendor CLI's own auth
# inside a `--rm` tools container so the token persists to the rw-mounted host ~/.config (e.g.
# ~/.config/configstore/snyk.json for snyk). `--rm` ⇒ no image layer captures the token
# (T-05-07). The HOME override is load-bearing — see header.
auth_scanner() {
    local tool="$1"
    case "$tool" in
        snyk|socket) ;;
        *) print_error "auth requires snyk|socket (got: ${tool:-<none>})"; return 1 ;;
    esac

    print_info "Running $tool auth in a throwaway container (token persists to host ~/.config)"

    ensure_tools_image

    local op_agent="$HOME/.1password/agent.sock"
    local -a agent_args=()
    if [ -S "$op_agent" ]; then
        agent_args+=( -v "$op_agent:$CONTAINER_HOME/.1password/agent.sock" )
        agent_args+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.1password/agent.sock" )
    fi

    # Ensure the host config dir exists (snyk/socket write under $HOME/.config/configstore/…).
    mkdir -p "$HOME/.config"

    # `snyk auth` opens a browser flow at a TTY; the token writes to
    # $HOME/.config/configstore/snyk.json. With HOME=$CONTAINER_HOME and ~/.config mounted rw
    # there, that path is the HOST ~/.config/configstore/snyk.json. `socket login` prompts for
    # the API token and stores it under the socket CLI's config dir the same way. `--rm -it`:
    # one-shot + interactive TTY; --userns=keep-id makes the rw-mounted host config writable by
    # the tools uid (host uid). The PATH prepend keeps the vendor CLIs resolvable (mise shims
    # break under the non-native HOME — see resolve_secret_env).
    local cmd
    if [ "$tool" = "snyk" ]; then
        cmd="snyk auth"
    else
        cmd="socket login"
    fi

    local auth_rc=0
    "$CONTAINER_RUNTIME" run --rm -it --userns=keep-id \
        -e "HOME=$CONTAINER_HOME" \
        -v "$HOME/.config":"$CONTAINER_HOME/.config":rw \
        "${agent_args[@]}" \
        --entrypoint bash \
        "$HARNESSED_TOOLS_IMAGE" \
        -lc "export PATH=\"$_HARNESSED_TOOLS_NODE_PATH:\$PATH\"; $cmd" || auth_rc=$?

    if [ "$auth_rc" -ne 0 ]; then
        print_error "$tool auth failed (exit $auth_rc)"
        return "$auth_rc"
    fi
    print_success "$tool auth complete — token persisted to host ~/.config (no image layer)"
}
