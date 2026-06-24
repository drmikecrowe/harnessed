#!/usr/bin/env bash
# harnessed — isolated §4b auth seeding (ro credential + generated token-free .claude.json stub).
#
# Isolated mode carries NO host config layer. Auth is seeded by two mounts ONLY:
#   1. ~/.claude/.credentials.json mounted READ-ONLY — the real OAuth token (AUTH-02 / T-02-04).
#   2. a GENERATED minimal ~/.claude.json stub carrying onboarding/identity fields and NO token
#      (the host whole-file blob is NEVER mounted — carries Phase 1's MNT-03 / Pitfall 1 rule
#      forward; rw-mounting it races with host Claude and corrupts state — T-02-05).
#
# RESEARCH Pitfall A (HIGHEST RISK): the exact field set Claude gates onboarding on is [INFERENCE].
# The candidate set generated below is:
#     hasCompletedOnboarding  (primary onboarding gate, corroborated)
#     firstStartTime          (likely gate — first-run timestamp)
#     numStartups             (likely gate — > 0 means "not a first start")
#     oauthAccount, userID    (OAuth IDENTITY metadata, copied ro from the host file — NOT a token)
# It contains ZERO token/credential values (the token lives only in the ro .credentials.json).
# This set is PROVEN only by the headless no-prompt acceptance test (02-02 operator checkpoint)
# and is then pinned as a committed snapshot fixture. A Claude upgrade that adds a gate fails the
# headless test loudly. CLAUDE_CODE_OAUTH_TOKEN remains a documented fallback if file auth regresses.

# Append the isolated auth mounts to MOUNT_ARGS (caller declares `MOUNT_ARGS=()`).
# Usage: harnessed_isolated_auth_mounts "<instance>" "<harness>"
# claude/omp seed Claude Code auth (ro credential + token-free .claude.json stub); opencode seeds
# its own credential store (ro ~/.local/share/opencode/auth.json) — opencode has no .claude.json
# onboarding gate (HRN-02).
harnessed_isolated_auth_mounts() {
    local instance="$1" harness="${2:-claude}"

    # opencode: seed the host opencode credential store read-only at its XDG data path. opencode
    # reads $XDG_DATA_HOME/opencode/auth.json (sst/opencode auth/index.ts) — mounting the host file
    # there is sufficient (no stub, no onboarding gate). Provider env vars (e.g. ANTHROPIC_API_KEY)
    # or OPENCODE_AUTH_CONTENT remain documented fallbacks if file auth is unavailable.
    if [ "$harness" = "opencode" ]; then
        local oc_auth="$HOME/.local/share/opencode/auth.json"
        if [ -f "$oc_auth" ]; then
            MOUNT_ARGS+=( -v "$oc_auth:$CONTAINER_HOME/.local/share/opencode/auth.json:ro" )
        else
            print_warning "No host opencode credential at $oc_auth — isolated opencode auth will be unseeded (run 'opencode auth login' on the host, or set ANTHROPIC_API_KEY)."
        fi
        return 0
    fi

    # gemini: seed the host gemini-cli OAuth credential cache read-only under ~/.gemini. gemini-cli
    # stores OAuth at ~/.gemini/oauth_creds.json (+ account info in google_accounts.json); mounting
    # those ro alongside the image-baked ~/.gemini/settings.json is sufficient. GEMINI_API_KEY /
    # GOOGLE_API_KEY remain documented env fallbacks (HRN-03).
    if [ "$harness" = "gemini" ]; then
        local seeded=false g f
        for f in oauth_creds.json google_accounts.json; do
            g="$HOME/.gemini/$f"
            if [ -f "$g" ]; then
                MOUNT_ARGS+=( -v "$g:$CONTAINER_HOME/.gemini/$f:ro" )
                seeded=true
            fi
        done
        [ "$seeded" = false ] && print_warning "No host gemini credential under ~/.gemini — isolated gemini auth will be unseeded (run 'gemini' to log in on the host, or set GEMINI_API_KEY)."
        return 0
    fi

    # antigravity (agy): authenticates via Google OAuth into the OS system keyring (Secret Service),
    # with NO documented API-key env-var or mountable credential file. A clean-room container has no
    # keyring daemon, so agy prompts for an interactive (printed-URL) login on first launch and does
    # not persist across recreates. Nothing to seed here — surface the limitation (HRN-04).
    if [ "$harness" = "antigravity" ]; then
        print_warning "antigravity (agy) uses interactive Google OAuth (system keyring) — not pre-seeded in isolated mode; agy will print a login URL on first launch (see docs/guides)."
        return 0
    fi

    # codex: seed the host codex credential store read-only at ~/.codex/auth.json (written by
    # `codex login` — ChatGPT-account OAuth or an API key). Mounting it ro alongside the image-baked
    # ~/.codex/config.toml is sufficient. OPENAI_API_KEY remains a documented env fallback. With no
    # subscription/key the file is absent → unseeded (codex prompts to log in on launch) (HRN-05).
    if [ "$harness" = "codex" ]; then
        local cx_auth="$HOME/.codex/auth.json"
        if [ -f "$cx_auth" ]; then
            MOUNT_ARGS+=( -v "$cx_auth:$CONTAINER_HOME/.codex/auth.json:ro" )
        else
            print_warning "No host codex credential at $cx_auth — isolated codex auth will be unseeded (run 'codex login' on the host, or set OPENAI_API_KEY)."
        fi
        return 0
    fi

    # (1) ro credential mount — the real OAuth token. Never copied into the profile or an image
    # layer; only ever surfaced as a read-only bind mount (§7/§16, T-02-04).
    local host_cred="$HOME/.claude/.credentials.json"
    if [ -f "$host_cred" ]; then
        MOUNT_ARGS+=( -v "$host_cred:$CONTAINER_HOME/.claude/.credentials.json:ro" )
    else
        print_warning "No host credential at $host_cred — isolated auth will be unseeded (run 'claude login' on the host first)."
    fi

    # (2) generated minimal .claude.json stub (NO token) at a per-instance state dir.
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$instance"
    mkdir -p "$state_dir"
    local stub="$state_dir/claude.json"

    if ! command -v jq >/dev/null 2>&1; then
        print_error "jq is required to generate the isolated .claude.json stub"; return 1
    fi

    # Copy ONLY the OAuth identity fields from the host ~/.claude.json (read, NEVER mounted).
    # `|| echo …` so a missing/malformed host file never aborts under `set -e`.
    local host_json="$HOME/.claude.json" oauth_account='{}' user_id='""'
    if [ -f "$host_json" ]; then
        oauth_account="$(jq -c '.oauthAccount // {}' "$host_json" 2>/dev/null || echo '{}')"
        user_id="$(jq -c '.userID // ""' "$host_json" 2>/dev/null || echo '""')"
    fi

    # Build the stub. ZERO token keys: only onboarding/identity fields (RESEARCH Pitfall A).
    jq -n \
        --argjson oauthAccount "$oauth_account" \
        --argjson userID "$user_id" \
        --arg firstStartTime "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" \
        '{
            hasCompletedOnboarding: true,
            firstStartTime: $firstStartTime,
            numStartups: 1,
            oauthAccount: $oauthAccount,
            userID: $userID
        }' > "$stub"

    MOUNT_ARGS+=( -v "$stub:$CONTAINER_HOME/.claude.json:rw" )
}
