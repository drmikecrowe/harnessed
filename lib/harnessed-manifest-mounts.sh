#!/usr/bin/env bash
# harnessed — data-driven mount helper (MNT2-06 surgical profile mount + history surfacing).
# Reads lib/manifests/<harness>.yaml (yq, already in base image) and appends -v flags to
# MOUNT_ARGS for: (1) per-harness profile config files (ro), (2) history dirs (rw),
# (3) omp per-slug session dir (rw, Pitfall 2), (4) MNT2-02 path mirroring bind.
# The caller declares `MOUNT_ARGS=()`; this function only appends.
#
# Usage: harnessed_manifest_mounts "$harness" "$profile_dir" "$project_path" "$relpath"
#   harness      — one of: claude omp opencode gemini antigravity codex
#   profile_dir  — absolute path to profiles/<stack>/ on the host
#   project_path — absolute host path to the project directory
#   relpath      — HOST $HOME-relative project path (e.g. "Programming/Personal/code-container")

harnessed_manifest_mounts() {
    local harness="$1" profile_dir="$2" project_path="$3" relpath="$4"
    local manifest="$HARNESSED_DIR/lib/manifests/${harness}.yaml"

    if [ ! -f "$manifest" ]; then
        print_warning "No manifest for harness: $harness (skipping manifest mounts)"
        return 0
    fi

    # Profile config files — mount each filename from profile_dir into the container ro.
    # Target path is harness-aware per D-03 and Pitfall 4 (09-RESEARCH.md):
    #   claude, omp, opencode  → ~/.claude/<f>  (consume Claude-canonical profile)
    #   gemini, antigravity, codex → config is image-baked; skip (do not overwrite image config)
    local f yq_out
    yq_out="$(yq '.profile_files[]' "$manifest")" || {
        print_warning "Failed to read profile_files from $manifest (yq exit $?)"; return 1; }
    while IFS= read -r f; do
        [ -z "$f" ] || [ "$f" = "null" ] && continue
        local src="$profile_dir/$f"
        local dst
        if [ "$harness" = "claude" ] || [ "$harness" = "omp" ] || [ "$harness" = "opencode" ]; then
            dst="$CONTAINER_HOME/.claude/$f"
        else
            # gemini / antigravity / codex: baked in image — do not overwrite
            continue
        fi
        if [ -f "$src" ]; then
            MOUNT_ARGS+=( -v "$src:$dst:ro" )
        else
            print_warning "Profile file not found (stack may need rebuild): $src"
        fi
    done <<< "$yq_out"

    # History dirs — rw-mount each $HOME-relative path from host to container.
    # mkdir -p before every bind to avoid root-owned dir creation in DooD mode (Pitfall 1
    # in shared patterns; see also harnessed-isolated-config.sh mkdir -p pattern).
    local d yq_hist_out
    yq_hist_out="$(yq '.history_dirs[]' "$manifest")" || {
        print_warning "Failed to read history_dirs from $manifest (yq exit $?)"; return 1; }
    while IFS= read -r d; do
        [ -z "$d" ] || [ "$d" = "null" ] && continue
        local host_dir="$HOME/$d"
        local container_dir="$CONTAINER_HOME/$d"
        mkdir -p "$host_dir"
        MOUNT_ARGS+=( -v "$host_dir:$container_dir:rw" )
    done <<< "$yq_hist_out"

    # omp: history surfaced at a per-project slug subdir (MNT2-04).
    # Slug MUST be computed from HOST $relpath (not container HOME) — Pitfall 2 in 09-RESEARCH.md.
    # relpath example: "Programming/Personal/code-container" → slug: "-Programming-Personal-code-container"
    if [ "$harness" = "omp" ]; then
        local omp_slug="-${relpath//\//'-'}"
        local host_omp="$HOME/.omp/agent/sessions/$omp_slug"
        local ctr_omp="$CONTAINER_HOME/.omp/agent/sessions/$omp_slug"
        mkdir -p "$host_omp"
        MOUNT_ARGS+=( -v "$host_omp:$ctr_omp:rw" )
    fi

    # MNT2-02 path mirroring — project must be accessible at its identical host absolute path
    # inside the container so Claude derives the same project slug as on the host (D-06).
    # The workdir override to $project_path is set by harnessed-isolated.sh (-w flag).
    MOUNT_ARGS+=( -v "$project_path:$project_path" )
}
