#!/usr/bin/env bash
# harnessed — ~/.claude.json safety (copy-on-start) + CLAUDE_CONFIG_DIR scope probe.
#
# ~/.claude.json is a single, constantly-rewritten whole-file blob. Rw-bind-mounting it races with
# the host's Claude and corrupts state (PITFALLS Pitfall 1 / design §4b). Instead, copy the host file
# ONCE into a per-instance writable file and mount THAT — the host file is never bind-mounted.

# Append the copy-on-start .claude.json mount to MOUNT_ARGS (caller declares `MOUNT_ARGS=()`).
# Usage: harnessed_claude_json_copy_mount "<instance>"
harnessed_claude_json_copy_mount() {
    local instance="$1"
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/harnessed/$instance"
    mkdir -p "$state_dir"
    local copy="$state_dir/.claude.json"
    # Seed once from host state; never clobber an existing per-instance copy (preserves instance state).
    if [ ! -f "$copy" ]; then
        if [ -f "$HOME/.claude.json" ]; then
            cp "$HOME/.claude.json" "$copy"
        else
            echo '{}' > "$copy"
        fi
    fi
    MOUNT_ARGS+=( -v "$copy:$CONTAINER_HOME/.claude.json:rw" )
}

# Empirical probe (non-fatal): does CLAUDE_CONFIG_DIR relocate the top-level ~/.claude.json, or only
# the ~/.claude/ dir? If it cleanly relocates the file, both modes could point Claude at a per-instance
# config dir instead of copy-on-start (D-02). Until verified upstream (#14313/#3833), copy-on-start is
# the default (D-01).
harnessed_probe_claude_config_dir_scope() {
    print_info "[probe] CLAUDE_CONFIG_DIR top-level .claude.json relocation is unverified upstream (#14313/#3833)."
    print_info "[probe] Default: copy-on-start .claude.json. Switch to CLAUDE_CONFIG_DIR only if a check confirms clean relocation."
}
