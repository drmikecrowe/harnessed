# harnessed-tools — the build-time assembler image (EMIT ONLY).
#
# Holds all assembly logic in Python (parse/validate recipe.yaml/stack.yaml, fan
# skills/commands, merge hatago.config.json, derive the harness .mcp.json) and writes
# the result into a bind-mounted build dir. It NEVER invokes podman/docker and never
# mounts a daemon socket (design §15, D-12, threat T-02-03); the HOST runs `podman build`
# on the emitted artifacts.
#
# Run by `harnessed build <stack>`:
#   podman run --rm --userns=keep-id -v <build-dir>:<build-dir> -w <build-dir> \
#       harnessed-tools assemble <stack> --build-dir <build-dir>

FROM python:3.13-slim

# jq is available in-image for JSON shaping/inspection of emitted artifacts (design STACK).
RUN apt-get update \
    && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/harnessed-tools
COPY pyproject.toml ./
COPY harnessed/ ./harnessed/
RUN pip install --no-cache-dir .

# Match the host UID (paired with `--userns=keep-id` at run) so emitted files in the
# bind-mounted build dir are owned by the host user, not root.
RUN useradd --create-home --uid 1000 tools
# Managed pnpm supply-chain config (Phase 3 / BLD-01). COPY as root into the tools
# user's pnpm global config path (before USER tools) so any future vendored node deps
# honor minimumReleaseAge/strictDepBuilds/allowBuilds. (osv-scanner/pip-audit = plan 03-02.)
RUN mkdir -p /home/tools/.config/pnpm
COPY lib/pnpm/config.yaml /home/tools/.config/pnpm/config.yaml
RUN chown -R tools:tools /home/tools/.config
USER tools
WORKDIR /work

# The console script installed from pyproject ([project.scripts] harnessed-tools).
ENTRYPOINT ["harnessed-tools"]
