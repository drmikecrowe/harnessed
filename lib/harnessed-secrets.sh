#!/usr/bin/env bash
# harnessed — opt-in secrets (varlock + 1Password) + scanner-token auth (plan 05-02 / SEC-01, SEC-03).
#
# Two functions:
#   resolve_secret_env  — detect ~/.config/harnessed/.env.schema (INERT when absent: a single
#                         `[ -f ]` test; no schema ⇒ return 0 ⇒ varlock NEVER invoked, today's
#                         behavior unchanged bit-for-bit). When present, resolve `op://` refs ON
#                         THE HOST via `varlock load --format env`. This is load-bearing: the
#                         1Password desktop app authorizes the `op` CLI by CALLING APPLICATION
#                         (your terminal), so app-auth (`@initOp(allowAppAuth=true)`) works on the
#                         host but CANNOT work inside the throwaway container — there the desktop
#                         app has no host app to bind the grant to and `op` fails with "cannot
#                         connect to 1Password app" no matter which socket is mounted (the agent
#                         socket is the SSH agent, NOT the op app-auth transport). Matches design
#                         §16 ("wrap the launch in `varlock run --`"). Writes the resolved dotenv
#                         to a mode-0600 temp env-file; echoes its path (caller unlinks after
#                         launch, T-05-06). Hosts WITHOUT varlock fall back to in-container
#                         resolution, which then requires OP_SERVICE_ACCOUNT_TOKEN (bearer auth —
#                         no desktop app). varlock on the host is opt-in; the no-secrets path
#                         stays podman-only.
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

# resolve_secret_env — detect-and-resolve the host-level .env.schema (see header for WHY host).
# Stdout: the path to a mode-0600 temp env-file holding the resolved dotenv (caller unlinks
# after launch), or empty when no schema is present (the inert path) / when varlock emitted
# nothing. Returns non-zero only on resolution FAILURE (a present schema that won't resolve).
resolve_secret_env() {
    # INERTNESS GUARANTEE: no schema ⇒ return 0 immediately; varlock is NEVER invoked.
    [ -f "$HARNESSED_SCHEMA" ] || return 0

    print_info "Resolving secrets via varlock (schema: $HARNESSED_SCHEMA) ..." >&2

    local envfile schema_dir raw errlog rc=0
    envfile="$(mktemp -t harnessed-env.XXXX --suffix=.env)"; chmod 600 "$envfile"
    raw="$(mktemp -t harnessed-secrets-raw.XXXX)"; chmod 600 "$raw"
    errlog="$(mktemp -t harnessed-secrets-err.XXXX)"
    schema_dir="$(dirname "$HARNESSED_SCHEMA")"

    if command -v varlock >/dev/null 2>&1; then
        # HOST resolution (the default). `op` app-auth works here because the desktop app
        # authorizes the calling terminal (header). The subshell `cd` keeps the launcher's cwd
        # intact; `|| rc=$?` captures the exit under the launcher's `set -euo pipefail`.
        ( cd "$schema_dir" && varlock load --format env ) >"$raw" 2>"$errlog" || rc=$?
    elif [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        # Headless fallback (no host varlock — e.g. the nightly timer / CI): resolve in a
        # throwaway tools container using the service-account token (HTTPS bearer auth — no
        # desktop app, no app-auth, no socket). --rm ⇒ no image layer holds the resolved env.
        # The scratch dir is mounted as $CONTAINER_HOME so varlock's plugin can write its data
        # ($HOME/.config) under a host-owned, --userns=keep-id-writable path.
        local tmpdir
        tmpdir="$(mktemp -d -t harnessed-secrets.XXXX)"
        cp "$HARNESSED_SCHEMA" "$tmpdir/.env.schema"
        mkdir -m 700 "$tmpdir/.config"
        "$CONTAINER_RUNTIME" run --rm $(rt_userns_args) \
            -e "HOME=$CONTAINER_HOME" \
            -e "OP_SERVICE_ACCOUNT_TOKEN=$OP_SERVICE_ACCOUNT_TOKEN" \
            -v "$tmpdir":"$CONTAINER_HOME":rw \
            --entrypoint bash \
            "$HARNESSED_TOOLS_IMAGE" \
            -lc "export PATH=\"$_HARNESSED_TOOLS_NODE_PATH:\$PATH\"; cd \"\$HOME\" && varlock load --format env" \
            >"$raw" 2>"$errlog" || rc=$?
        rm -rf "$tmpdir"
    else
        rm -f "$envfile" "$raw" "$errlog"
        print_error "secret resolution needs host 'varlock' (1Password desktop app-auth) OR OP_SERVICE_ACCOUNT_TOKEN (headless)." >&2
        print_error "Install varlock on the host (e.g. \`npm i -g varlock\`) for the desktop-app flow, or export a scoped service-account token. See docs/guides/secrets.md." >&2
        return 1
    fi

    if [ "$rc" -ne 0 ]; then
        rm -f "$envfile" "$raw"
        print_error "varlock resolution failed (exit $rc):" >&2
        sed 's/^/    /' "$errlog" >&2
        rm -f "$errlog"
        if command -v varlock >/dev/null 2>&1; then
            print_error "Is the 1Password desktop app running, unlocked, and CLI integration authorized for this terminal?" >&2
            print_error "(1Password → Settings → Developer → 'Integrate with 1Password CLI'; the first run prompts to Authorize.) See docs/guides/secrets.md." >&2
        else
            print_error "Check OP_SERVICE_ACCOUNT_TOKEN and the op:// refs in the schema. See docs/guides/secrets.md." >&2
        fi
        return 1
    fi
    rm -f "$errlog"

    # Unquote varlock's dotenv (KEY="value" → KEY=value) so podman --env-file reads the value,
    # not the literal quotes. Result is mode-0600; the caller spreads it via --env-file and
    # unlinks after launch (T-05-06).
    local final=""
    if [ -s "$raw" ]; then
        sed -E 's/^([^=]+)="(.*)"$/\1=\2/' "$raw" > "$envfile"
        final="$envfile"
    else
        # varlock succeeded but emitted nothing — schema valid but resolves no env. Treat as
        # inert (no --env-file to spread); warn so the operator notices.
        print_warning "varlock resolved no env from $HARNESSED_SCHEMA (empty dotenv)" >&2
        rm -f "$envfile"
    fi
    rm -f "$raw"
    [ -n "$final" ] && echo "$final"
}

# discover_scanner_tokens — read SNYK_TOKEN and SOCKET_SECURITY_API_KEY from secondary host-
# readable sources WITHOUT requiring varlock or a container. Called from build_stack() after the
# raw-host-env pass to fill gaps before the varlock/op:// path.
#
# Source order (emits only tokens not yet found by the caller; caller guards with [ -z ]):
#   1. ~/.config/harnessed/.env   — plain dotenv (no quoting required; strips surrounding quotes)
#   2. ~/.config/configstore/snyk.json — token stored by `harnessed auth snyk` (.api field)
#      (socket CLI configstore path is model-specific; use the .env file for socket tokens)
#
# Stdout: zero or more KEY=value lines (no -e prefix; caller decides how to consume).
# Never fails (missing files are silently skipped). No container required — pure host bash + sed.
discover_scanner_tokens() {
    local _snyk="" _sock=""

    # Source 1: plain dotenv at ~/.config/harnessed/.env
    local _plain_env="$HOME/.config/harnessed/.env"
    if [ -f "$_plain_env" ]; then
        local _line _key _val
        while IFS= read -r _line; do
            case "$_line" in '#'*|'') continue ;; esac
            _key="${_line%%=*}"
            _val="${_line#*=}"
            # Strip surrounding double-quotes (KEY="value" → KEY=value).
            _val="${_val#\"}"; _val="${_val%\"}"
            case "$_key" in
                SNYK_TOKEN)              [ -z "$_snyk" ] && _snyk="$_val" ;;
                SOCKET_SECURITY_API_KEY) [ -z "$_sock" ] && _sock="$_val" ;;
            esac
        done < "$_plain_env"
    fi

    # Source 2: ~/.config/configstore/snyk.json (.api field written by `harnessed auth snyk`)
    if [ -z "$_snyk" ]; then
        local _snyk_cfg="$HOME/.config/configstore/snyk.json"
        if [ -f "$_snyk_cfg" ]; then
            # Simple sed extract — snyk.json is {"api":"<token>",...}; no host jq required (§15).
            _snyk="$(sed -n 's/.*"api"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$_snyk_cfg" 2>/dev/null | head -1)"
        fi
    fi

    [ -n "$_snyk" ] && echo "SNYK_TOKEN=$_snyk"
    [ -n "$_sock" ] && echo "SOCKET_SECURITY_API_KEY=$_sock"
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
    # `snyk auth` runs an OAuth flow: it starts a callback listener on 127.0.0.1:8080 INSIDE the
    # container, opens the host browser to snyk.io, then snyk redirects the browser back to
    # http://127.0.0.1:8080/authorization-code/callback?code=...  snyk binds the container's
    # LOOPBACK (127.0.0.1). Publishing the port does NOT work under rootless pasta: `-p
    # 127.0.0.1:8080:8080` is delivered to the container's outward interface, not its loopback, so
    # snyk's 127.0.0.1-only listener resets the forwarded connection (verified: "Connection reset
    # by peer"). The reliable fix is `--network=host`: the container shares the host net namespace,
    # so snyk's 127.0.0.1:8080 IS the host's loopback and the browser redirect lands directly
    # (verified: host GET → snyk 301 → app.snyk.io/authenticated). Host-net is scoped to this
    # one-shot interactive auth container only; snyk still binds loopback, so nothing is LAN-exposed.
    # `socket login` prompts for an API token (no browser callback) → no host networking needed.
    local cmd
    local -a net_args=()
    if [ "$tool" = "snyk" ]; then
        cmd="snyk auth"
        net_args=( --network=host )
    else
        cmd="socket login"
    fi

    local auth_rc=0
    "$CONTAINER_RUNTIME" run --rm -it $(rt_userns_args) \
        -e "HOME=$CONTAINER_HOME" \
        -v "$HOME/.config":"$CONTAINER_HOME/.config":rw \
        "${agent_args[@]}" \
        "${net_args[@]}" \
        --entrypoint bash \
        "$HARNESSED_TOOLS_IMAGE" \
        -lc "export PATH=\"$_HARNESSED_TOOLS_NODE_PATH:\$PATH\"; $cmd" || auth_rc=$?

    if [ "$auth_rc" -ne 0 ]; then
        print_error "$tool auth failed (exit $auth_rc)"
        return "$auth_rc"
    fi
    print_success "$tool auth complete — token persisted to host ~/.config (no image layer)"
}
