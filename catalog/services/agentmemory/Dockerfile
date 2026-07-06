# Service image: agentmemory — the shared REST memory store (plan agentmemory / design §9).
#
# Built by `harnessed svc up agentmemory` (or `podman build -t harnessed-agentmemory:latest`).
# Unlike a RECIPE Dockerfile, a SERVICE carries its own full FROM/USER/CMD — it is a complete
# image, not appended onto harnessed-${HARNESS}.
#
# The store is REST-only :3111 (+ viewer :3113). No MCP adapter, no bridge — the recipe's
# stdio shim is the MCP adapter. Two processes at runtime: the Node app + the iii-engine it
# self-spawns (pinned, pre-baked below so first start is deterministic and network-free).
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
        && rm -rf /var/lib/apt/lists/*
# pnpm everywhere (NEVER npm/npx). corepack ships pnpm on node:20-slim.
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

RUN useradd --create-home --uid 1000 harnessed
USER harnessed
ENV PNPM_HOME="/home/harnessed/.local/share/pnpm"
ENV PATH="/home/harnessed/.local/share/pnpm:${PATH}"
WORKDIR /home/harnessed

# 1) the store (REST :3111 + viewer :3113), pinned (no @latest). Lands the `agentmemory` bin.
ARG AGENTMEMORY_VERSION=0.9.27
RUN mkdir -p "$PNPM_HOME/bin" && pnpm add -g "@agentmemory/agentmemory@${AGENTMEMORY_VERSION}"

# 2) Pre-bake the pinned iii-engine binary so first start is deterministic and network-free
#    (the store self-manages the engine; placing it where agentmemory looks — ~/.agentmemory/bin —
#    makes it skip the runtime download). The engine runs as `harnessed` — sidestepping the
#    distroless UID-65532 + iii-init chown dance the upstream compose needs.
ARG III_VERSION=0.11.2
RUN mkdir -p /home/harnessed/.agentmemory/bin \
    && curl -fsSL "https://github.com/iii-hq/iii/releases/download/iii/v${III_VERSION}/iii-x86_64-unknown-linux-gnu.tar.gz" \
       | tar -xz -C /home/harnessed/.agentmemory/bin \
    && chmod +x /home/harnessed/.agentmemory/bin/iii
ENV AGENTMEMORY_III_VERSION=${III_VERSION}

# 3) Entrypoint: start the store and wait for livez (foreground = PID 1).
COPY --chown=harnessed:harnessed entrypoint.sh /home/harnessed/entrypoint.sh
EXPOSE 3111
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -sf http://localhost:3111/agentmemory/livez || exit 1
CMD ["bash", "/home/harnessed/entrypoint.sh"]
