#!/usr/bin/env bash
# harnessed — §4a host-integration mount layer (operational: auth/signing/agents/firewall).
# Shared by EVERY stack. Host-native: the launcher runs on the host, so sources are real host
# paths ($HOME, the project path) and targets live under $CONTAINER_HOME. Appends podman/docker
# run args to the MOUNT_ARGS array (the caller declares `MOUNT_ARGS=()`).
#
# Does NOT mount ~/.claude* — that is config-mode-specific (transparent vs isolated) and handled
# by the per-stack launcher. Ported from container.sh:start_new_container (37-146).

# Usage: harnessed_host_integration_mounts "<project_path>" "<project_relpath>"
harnessed_host_integration_mounts() {
    local project_path="$1" relpath="$2"

    # Base run flags: rootless UID mapping, NET_ADMIN (egress firewall), TERM, project + workdir.
    MOUNT_ARGS+=( --userns=keep-id --cap-add NET_ADMIN -e "TERM=xterm-256color" )
    MOUNT_ARGS+=( -w "$CONTAINER_HOME/$relpath" )
    MOUNT_ARGS+=( -v "$project_path:$CONTAINER_HOME/$relpath" )

    # Egress firewall script (applied per session by apply_firewall in harnessed-common.sh).
    MOUNT_ARGS+=( -v "$HARNESSED_DIR/lib/egress-firewall.sh:/usr/local/sbin/egress-firewall:ro" )

    # 1Password SSH agent socket.
    local op_agent="$HOME/.1password/agent.sock"
    if [ -S "$op_agent" ]; then
        MOUNT_ARGS+=( -v "$op_agent:$CONTAINER_HOME/.1password/agent.sock" )
        MOUNT_ARGS+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.1password/agent.sock" )
    fi

    # GPG agent SSH socket (YubiKey SSH auth).
    local gpg_ssh="/run/user/$(id -u)/gnupg/S.gpg-agent.ssh"
    if [ -S "$gpg_ssh" ]; then
        MOUNT_ARGS+=( -v "$gpg_ssh:$CONTAINER_HOME/.gnupg-sockets/S.gpg-agent.ssh" )
        # Only set SSH_AUTH_SOCK here if the 1Password agent didn't already claim it.
        [ -S "$op_agent" ] || MOUNT_ARGS+=( -e "SSH_AUTH_SOCK=$CONTAINER_HOME/.gnupg-sockets/S.gpg-agent.ssh" )
    fi

    # GPG configuration (YubiKey commit/SSH signing), read-only.
    [ -d "$HOME/.gnupg" ] && MOUNT_ARGS+=( -v "$HOME/.gnupg:$CONTAINER_HOME/.gnupg:ro" )

    # YubiKey USB device passthrough (Yubico vendor ID 1050).
    local yk_bus yk_dev yk_device
    yk_bus=$(lsusb 2>/dev/null | grep -i "yubico\|1050" | head -1 | awk '{print $2}') || true
    yk_dev=$(lsusb 2>/dev/null | grep -i "yubico\|1050" | head -1 | awk '{print $4}' | tr -d ':') || true
    if [ -n "$yk_bus" ] && [ -n "$yk_dev" ]; then
        yk_device="/dev/bus/usb/$yk_bus/$yk_dev"
        [ -e "$yk_device" ] && MOUNT_ARGS+=( --device "$yk_device" )
    fi

    # Z.AI config for GLM models, read-only.
    [ -f "$HOME/.zai.json" ] && MOUNT_ARGS+=( -v "$HOME/.zai.json:$CONTAINER_HOME/.zai.json:ro" )

    # Per-tool ~/.config/<tool> dirs for tools listed in extra-tools.txt.
    # Some tools use a config dir name that differs from their package name; "" means skip.
    local -A tool_cfg_map=( [neovim]=nvim [markdownlint-cli2]="" [ast-grep]="" )
    local tools_file="$HARNESSED_DIR/extra-tools.txt" tool cfg_name tool_cfg
    if [ -f "$tools_file" ]; then
        while IFS= read -r tool; do
            tool=$(echo "$tool" | sed 's|^npm:||; s|^github:[^@]*/||' | awk '{print $1}')
            [ -z "$tool" ] && continue
            cfg_name="$tool"
            if [[ -v tool_cfg_map[$tool] ]]; then
                cfg_name="${tool_cfg_map[$tool]}"
                [ -z "$cfg_name" ] && continue
            fi
            tool_cfg="$HOME/.config/$cfg_name"
            [ -d "$tool_cfg" ] && MOUNT_ARGS+=( -v "$tool_cfg:$CONTAINER_HOME/.config/$cfg_name" )
        done < <(grep -v '^\s*#' "$tools_file" | grep -v '^\s*$')
    fi

    # Git config (XDG location preferred, then legacy), read-only.
    if [ -d "$HOME/.config/git" ]; then
        MOUNT_ARGS+=( -v "$HOME/.config/git:$CONTAINER_HOME/.config/git:ro" )
    elif [ -f "$HOME/.gitconfig" ]; then
        MOUNT_ARGS+=( -v "$HOME/.gitconfig:$CONTAINER_HOME/.gitconfig:ro" )
    fi

    # Host machine-id — lets Claude Code see the same machine (avoids re-auth), read-only.
    [ -f /etc/machine-id ] && MOUNT_ARGS+=( -v "/etc/machine-id:/etc/machine-id:ro" )

    # SSH keys/config, read-only.
    [ -d "$HOME/.ssh" ] && MOUNT_ARGS+=( -v "$HOME/.ssh:$CONTAINER_HOME/.ssh:ro" )
}
