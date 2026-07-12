# Recipe Dockerfile for: context-mode
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Two things happen here, and only the second is harness-specific.
#
# 1. CONTEXT_MODE_DIR — pin the sessions/content store to ~/.context-mode on EVERY harness.
#    That is already the default for the hook/CLI path, but the omp plugin (below) resolves its
#    storage root through the same module (build/session/db.js, which reads CONTEXT_MODE_DIR) and
#    would otherwise root at ~/.omp/context-mode/ via its OMPAdapter. Only ~/.omp/agent is
#    bind-mounted from the host, so that dir would die with the pod. Setting it explicitly makes
#    both paths land in the one dir the recipe's `persist: .context-mode` entry mounts.
#
# 2. The omp plugin. Under omp, the two hooks upstream marks REQUIRED are inert: the pre-installed
#    omp-claude-hooks-bridge replays .claude/settings.json hooks but is a pure decision+side-effect
#    bridge — it drops hookSpecificOutput.additionalContext, so the PreToolUse routing nudge and the
#    SessionStart context re-injection never reach the model, and it maps no omp event to PreCompact
#    at all. (Same wall the omp identity delivery already hit — see emit.py's write_omp_identity.)
#    context-mode ships its own omp adapter (package.json `omp.extensions`), which registers
#    session_start, tool_call (a HARD BLOCK on curl/wget/inline-HTTP in bash, not a nudge),
#    tool_result, and session_before_compact — all four, natively. So on omp we install that and
#    suppress the bridged hooks (recipe.yaml `hooks.skip_harnesses: [omp]`), which would otherwise
#    double-write the session DB and spawn a node CLI per tool call for output nobody reads.
#
#    This survives launch: the omp image bakes ~/.omp/{plugins,natives} and only ~/.omp/agent is
#    bind-mounted over (launcher._omp_agent_mount), so an image-layer plugin install stands — the
#    same path the bridge itself uses in Dockerfile.harnessed-omp.
#
#    MCP needs nothing here: omp reads MCP from ~/.omp/agent/mcp.json, into which the launcher
#    already seeds the hatago endpoint (_omp_mcp_seed_mount), so the ctx_* tools arrive once.
ARG CONTEXT_MODE_VERSION=1.0.169
ENV CONTEXT_MODE_DIR=/home/harnessed/.context-mode
RUN if [ "${HARNESS}" = "omp" ]; then \
      omp plugin install "context-mode@${CONTEXT_MODE_VERSION}"; \
    fi
