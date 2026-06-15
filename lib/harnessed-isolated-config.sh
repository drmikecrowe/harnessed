#!/usr/bin/env bash
# harnessed — isolated §4b auth seeding (ro credential + generated token-free .claude.json stub).
#
# Isolated mode carries NO host config layer. Auth is seeded by two mounts ONLY:
#   1. ~/.claude/.credentials.json mounted READ-ONLY — the real OAuth token (AUTH-02 / T-02-04).
#   2. a GENERATED minimal ~/.claude.json stub carrying onboarding/identity fields and NO token
#      (the host whole-file blob is NEVER mounted — carries Phase 1's MNT-03 / Pitfall 1 rule
#      forward; rw-mounting it races with host Claude and corrupts state — T-02-05).
#
# This is the isolated analog of lib/harnessed-claude-config.sh (transparent copy-on-start, D-09):
# transparent COPIES the host blob; isolated GENERATES a stub.
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
# Usage: harnessed_isolated_auth_mounts "<instance>"
harnessed_isolated_auth_mounts() {
    local instance="$1"

    # (1) ro credential mount — the real OAuth token. Never copied into the profile or an image
    # layer; only ever surfaced as a read-only bind mount (§7/§16, T-02-04).
    local host_cred="$HOME/.claude/.credentials.json"
    if [ -f "$host_cred" ]; then
        MOUNT_ARGS+=( -v "$host_cred:$CONTAINER_HOME/.claude/.credentials.json:ro" )
    else
        print_warning "No host credential at $host_cred — isolated auth will be unseeded (run 'claude login' on the host first)."
    fi

    # (2) generated minimal .claude.json stub (NO token) at a per-instance state dir
    # (same convention as harnessed-claude-config.sh:12).
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
