#!/usr/bin/env bash
# harnessed — nightly image re-scan (plan 05-03 / SEC-04).
#
# harnessed_rescan_images — iterate installed harnessed-labelled images, `podman save` each to a
# temp tar, and re-scan it ONLINE (fresh osv.dev DB; NOT the build-time offline DB) via the
# scan-image-online subcommand in a throwaway harnessed-tools container. The critical detail
# (RESEARCH Pitfall 6): scan-image-online drops the --offline flags so osv-scanner sees
# newly-disclosed CVEs — the whole point of the nightly. Using the offline DB here would defeat
# the purpose (it only knows about CVEs at build time).
#
# A HIGH finding on one image surfaces (the tools container exits non-zero) but does NOT abort
# the scan of the remaining images — each image is scanned independently and the overall rc
# tracks any failure. Returns non-zero if ANY image had a HIGH.
#
# Driven by the launcher's `rescan)` dispatch (the manual trigger) AND by the nightly systemd
# user timer's ExecStart (`%h/.local/bin/harnessed rescan`). Mirrors the image-scan block in
# lib/harnessed-common.sh:155-167 (build_stack's BLD-02b step) but calls scan-image-online
# (online mode) instead of scan-image (offline), inside a per-image loop.
#
# Host-native: every podman/docker call runs on the HOST. Sourced just-in-time by the launcher
# (`harnessed` `rescan)` path). No daemon-in-container; no API socket mounted.
#
# Expects CONTAINER_RUNTIME + HARNESSED_DIR + HARNESSED_TOOLS_IMAGE (all set by
# lib/harnessed-common.sh, sourced by the launcher before this lib).

harnessed_rescan_images() {
    ensure_tools_image

    local rc=0 img tar img_rc
    # `reference='harnessed-*'` scopes to the harnessed image set (A6 — not ALL podman images).
    # The while+read loop handles repository names with spaces safely (a bare `for img in $(...)`
    # would word-split). `< <(...)` is process substitution — avoids a pipeline (whose body would
    # run in a subshell where `rc` mutations would not escape).
    while IFS= read -r img; do
        [ -n "$img" ] || continue
        print_info "Re-scanning $img (online) ..."
        tar="$(mktemp --suffix=.tar)"
        # Safe save under set -e: an image removed between list and save, or a transient podman
        # error, must NOT abort the whole nightly or leak the tar (the rm at loop-tail is
        # unreachable on failure). Mirror the scan step's finding-isolation: skip this image,
        # track the failure, keep scanning the rest.
        if ! "$CONTAINER_RUNTIME" save "$img" -o "$tar"; then
            print_error "Could not save $img for re-scan (removed?) — skipping; tar cleaned"
            rm -f "$tar"
            rc=1
            continue
        fi
        # Safe exit capture under set -euo pipefail (Constraint 9 / a963a69): a bare scanner
        # pipeline would abort the whole launcher on a HIGH exit. `|| img_rc=$?` swallows it so
        # the loop continues; the overall rc tracks any failure.
        img_rc=0
        "$CONTAINER_RUNTIME" run --rm -v "$tar":"$tar":ro \
            "$HARNESSED_TOOLS_IMAGE" scan-image-online "$tar" || img_rc=$?
        rm -f "$tar"
        if [ "$img_rc" -ne 0 ]; then
            print_error "Re-scan of $img found a HIGH+ finding (newly-disclosed CVE) — investigate"
            rc=1   # track overall failure; do NOT abort the loop (scan remaining images)
        fi
    done < <("$CONTAINER_RUNTIME" images --filter reference='harnessed-*' \
              --format '{{.Repository}}:{{.Tag}}')

    if [ "$rc" -eq 0 ]; then
        print_success "Re-scan complete — all installed harnessed images clean (online)"
    else
        print_error "Re-scan found HIGH+ finding(s) on one or more images — see above"
    fi
    return "$rc"
}
