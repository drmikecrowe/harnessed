# Recipe Dockerfile for: context-mode
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Only the omp plugin install happens here. CONTEXT_MODE_DIR moved to recipe.yaml `env:` — as a
# Dockerfile ENV it was a container-absolute literal that a host launch could not use.
#
# The omp plugin. Under omp, the two hooks upstream marks REQUIRED are inert: the pre-installed
# omp-claude-hooks-bridge replays .claude/settings.json hooks but is a pure decision+side-effect
# bridge — it drops hookSpecificOutput.additionalContext, so the PreToolUse routing nudge and the
# SessionStart context re-injection never reach the model, and it maps no omp event to PreCompact
# at all. (Same wall the omp identity delivery already hit — see emit.py's write_omp_identity.)
# context-mode ships its own omp adapter (package.json `omp.extensions`), which registers
# session_start, tool_call (a HARD BLOCK on curl/wget/inline-HTTP in bash, not a nudge),
# tool_result, and session_before_compact — all four, natively. So on omp we install that and
# suppress the bridged hooks (recipe.yaml `hooks.skip_harnesses: [omp]`), which would otherwise
# double-write the session DB and spawn a node CLI per tool call for output nobody reads.
#
# This survives launch: the omp image bakes ~/.omp/{plugins,natives} and only ~/.omp/agent is
# bind-mounted over (launcher._omp_agent_mount), so an image-layer plugin install stands — the
# same path the bridge itself uses in Dockerfile.harnessed-omp.
#
# MCP needs nothing here: omp reads MCP from ~/.omp/agent/mcp.json, into which the launcher
# already seeds the hatago endpoint (_omp_mcp_seed_mount), so the ctx_* tools arrive once.
ARG CONTEXT_MODE_VERSION=1.0.169
RUN if [ "${HARNESS}" = "omp" ]; then \
      omp plugin install "context-mode@${CONTEXT_MODE_VERSION}"; \
    fi
