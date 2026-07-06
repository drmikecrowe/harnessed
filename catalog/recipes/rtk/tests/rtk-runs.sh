#!/usr/bin/env bash
# Behavioral capability test for the rtk recipe (main-c98).
#
# rtk ships no skill/command/plugin/mcp surface — it is a baked binary the agent shells out to — so
# `expect:` has no kind that can verify it (recipe.yaml admits `rtk --version` was checked MANUALLY).
# This script is that manual check, automated: it actually INVOKES the binary inside the built
# instance and gates on exit code, which is exactly what a presence-only oracle cannot do.
#
# Contract: exit 0 == pass. Runs inside the live instance via `podman exec` (mise shims are on PATH
# in harnessed-base), so it sees the real baked binary.
set -euo pipefail

# 1. The binary must be resolvable and runnable.
if ! command -v rtk >/dev/null 2>&1; then
    echo "rtk not found on PATH" >&2
    exit 1
fi

# 2. `rtk --version` must succeed and name itself (guards against a wrong-"rtk" collision — the
#    Dockerfile deliberately avoids `cargo install rtk`, which is a different package).
version_output="$(rtk --version 2>&1)"
echo "rtk --version -> ${version_output}"
if ! grep -qi 'rtk' <<<"${version_output}"; then
    echo "rtk --version did not identify as rtk: ${version_output}" >&2
    exit 1
fi

# 3. `rtk gain` must work — the meta-command that distinguishes the real rtk (Rust Token Killer)
#    from the reachingforthejack/rtk (Rust Type Kit) name collision the recipe warns about.
if ! rtk gain >/dev/null 2>&1; then
    echo "rtk gain failed — wrong 'rtk' binary or broken install" >&2
    exit 1
fi

echo "rtk binary runs correctly"
