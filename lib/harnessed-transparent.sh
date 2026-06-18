#!/usr/bin/env bash
# harnessed — transparent stack launcher.
#
# transparent = "my laptop, sandboxed": the host harness configs are mounted LIVE (today's `container`,
# now delivered through the harnessed engine). Host-native: runs podman on the host and attaches with a
# host-native TTY — no pod, no hatago, no DooD. The degenerate stack (harness container only).

# harnessed_transparent <project_path> [use_claude] [use_zai]
harnessed_transparent() {
    local project_path="$1" use_claude="${2:-false}" use_zai="${3:-false}"

    . "$HARNESSED_DIR/lib/harnessed-mounts.sh"
    . "$HARNESSED_DIR/lib/harnessed-claude-config.sh"

    [ -d "$project_path" ] || { print_error "Project directory does not exist: $project_path"; exit 1; }

    local relpath instance
    relpath="$(project_relpath "$project_path")"
    instance="$(generate_instance_name transparent "$project_path")"

    # Shared per-harness config dirs for the non-claude harnesses (mirrors container.sh).
    mkdir -p "$HARNESSED_DIR/.codex" "$HARNESSED_DIR/.opencode" "$HARNESSED_DIR/.gemini"

    # Determine the in-container command + env (default: drop into bash).
    local exec_cmd="/bin/bash"
    local exec_env=( -e "TERM=xterm-256color" )
    local mise_init="source ~/.bashrc && mise trust -a 2>/dev/null"

    # --claude: launch Claude Code in YOLO mode.
    [ "$use_claude" = "true" ] && exec_cmd="claude --dangerously-skip-permissions"

    # --zai: launch Claude with Z.AI/GLM models in YOLO mode.
    local extra_hosts=()
    if [ "$use_zai" = "true" ]; then
        local zai_config="$HOME/.zai.json"
        [ -f "$zai_config" ] || { print_error "Z.AI config not found: $zai_config"; exit 1; }
        command -v jq >/dev/null 2>&1 || { print_error "jq is required on the host for --zai"; exit 1; }
        local api_url api_key haiku_model sonnet_model opus_model
        api_url=$(jq -r '.apiUrl // ""' "$zai_config") || true
        api_key=$(jq -r '.apiKey // ""' "$zai_config") || true
        haiku_model=$(jq -r '.haikuModel // "glm-4.5-air"' "$zai_config") || true
        sonnet_model=$(jq -r '.sonnetModel // "glm-5.0"' "$zai_config") || true
        opus_model=$(jq -r '.opusModel // "glm-5.0"' "$zai_config") || true
        [ -n "$api_url" ] && [ -n "$api_key" ] || { print_error "apiUrl/apiKey missing in $zai_config"; exit 1; }
        print_info "Z.AI: endpoint=$api_url | haiku=$haiku_model | sonnet=$sonnet_model | opus=$opus_model | key=${api_key:0:4}...${api_key: -4}"
        exec_env+=( -e "ANTHROPIC_BASE_URL=$api_url" -e "ANTHROPIC_AUTH_TOKEN=$api_key" \
                    -e "ANTHROPIC_DEFAULT_HAIKU_MODEL=$haiku_model" \
                    -e "ANTHROPIC_DEFAULT_SONNET_MODEL=$sonnet_model" \
                    -e "ANTHROPIC_DEFAULT_OPUS_MODEL=$opus_model" )
        exec_cmd="claude --dangerously-skip-permissions"
    fi

    # Always whitelist the Z.AI egress host if a config is present.
    if [ -f "$HOME/.zai.json" ] && command -v jq >/dev/null 2>&1; then
        local zai_host
        zai_host=$(jq -r '.apiUrl // ""' "$HOME/.zai.json" 2>/dev/null | sed 's|https\?://||' | cut -d'/' -f1) || true
        [ -n "$zai_host" ] && extra_hosts+=("$zai_host")
    fi

    # Attach to a running instance, or start a stopped one.
    if container_running "$instance"; then
        print_info "Attaching to running instance: $instance"
        apply_firewall "$instance" "${extra_hosts[@]+"${extra_hosts[@]}"}"
        "$CONTAINER_RUNTIME" exec -it "${exec_env[@]}" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && $exec_cmd"
        stop_if_last_session "$instance" "$relpath"
        return
    fi
    if container_exists "$instance"; then
        print_info "Starting existing instance: $instance"
        "$CONTAINER_RUNTIME" start "$instance" >/dev/null
        apply_firewall "$instance" "${extra_hosts[@]+"${extra_hosts[@]}"}"
        "$CONTAINER_RUNTIME" exec -it "${exec_env[@]}" -w "$CONTAINER_HOME/$relpath" "$instance" \
            bash -l -c "$mise_init && $exec_cmd"
        stop_if_last_session "$instance" "$relpath"
        return
    fi

    # Create a new instance.
    print_info "Creating transparent instance: $instance"
    print_info "Project: $project_path -> $CONTAINER_HOME/$relpath"

    local MOUNT_ARGS=()
    harnessed_host_integration_mounts "$project_path" "$relpath"

    # Transparent config source (§4b): live host harness configs.
    mkdir -p "$HOME/.claude"
    MOUNT_ARGS+=( -v "$HOME/.claude:$CONTAINER_HOME/.claude:rw" )   # dir tree: append-mostly, low race risk
    harnessed_claude_json_copy_mount "$instance"                   # whole-file blob: copy-on-start (NEVER rw-mount the host file)
    MOUNT_ARGS+=( -v "$HARNESSED_DIR/.codex:$CONTAINER_HOME/.codex" )
    MOUNT_ARGS+=( -v "$HARNESSED_DIR/.opencode:$CONTAINER_HOME/.config/opencode" )
    MOUNT_ARGS+=( -v "$HARNESSED_DIR/.gemini:$CONTAINER_HOME/.gemini" )

    # [SEC-01] Opt-in secret resolution — the SAME host-side path as the isolated launcher
    # (resolve_secret_env runs varlock on the HOST; inert when no ~/.config/harnessed/.env.schema).
    # Spread --env-file into the instance so resolved op:// secrets reach the transparent session
    # as env only (never a profile/image/file — T-05-05). The RETURN trap wipes the mode-0600 temp
    # on ANY exit (T-05-06). Only the create path resolves; a re-attach reuses the env baked at create.
    . "$HARNESSED_DIR/lib/harnessed-secrets.sh"
    local secret_env resolve_rc=0
    secret_env="$(resolve_secret_env)" || resolve_rc=$?
    if [ "$resolve_rc" -ne 0 ]; then
        print_error "secret resolution failed; aborting launch"
        return 1
    fi
    local -a env_args=()
    [ -n "$secret_env" ] && env_args=( --env-file "$secret_env" )
    [ -n "$secret_env" ] && trap 'rm -f "${secret_env:-}" 2>/dev/null || true' RETURN

    "$CONTAINER_RUNTIME" run -d --name "$instance" "${MOUNT_ARGS[@]}" \
        "${env_args[@]}" \
        "$HARNESSED_CLAUDE_IMAGE" sleep infinity >/dev/null

    apply_firewall "$instance" "${extra_hosts[@]+"${extra_hosts[@]}"}"
    "$CONTAINER_RUNTIME" exec -it "${exec_env[@]}" -w "$CONTAINER_HOME/$relpath" "$instance" \
        bash -l -c "$mise_init && $exec_cmd"
    stop_if_last_session "$instance" "$relpath"
    print_success "Instance session ended"
}
