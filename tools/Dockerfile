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
    && apt-get install -y --no-install-recommends jq curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/harnessed-tools
COPY pyproject.toml ./
COPY harnessed/ ./harnessed/
RUN pip install --no-cache-dir .

# Supply-chain scanners (BLD-02): osv-scanner v2.3.8 + pip-audit (pip-audit comes via pyproject
# above). The static Go binary is the pinned GitHub release, checksum-verified against the release
# SHA256SUMS BEFORE chmod +x (threat T-03-05 — never trust an unverified download), and the offline
# OSV DB is pre-seeded so scans run deterministically with no osv.dev/deps.dev hit at scan time
# (Open Q3 LOCK; RESEARCH Pitfall 6).
ARG OSV_SCANNER_VERSION=2.3.8
RUN mkdir -p /tmp/osv-dl \
    && curl -fsSL -o /tmp/osv-dl/osv-scanner_linux_amd64 \
        "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64" \
    && curl -fsSL -o /tmp/osv-dl/osv-scanner_SHA256SUMS \
        "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_SHA256SUMS" \
    && cd /tmp/osv-dl \
    && grep ' osv-scanner_linux_amd64$' osv-scanner_SHA256SUMS | sha256sum -c - \
    && mv osv-scanner_linux_amd64 /usr/local/bin/osv-scanner \
    && chmod +x /usr/local/bin/osv-scanner \
    && osv-scanner --version \
    && osv-scanner --download-offline-databases \
    && rm -rf /tmp/osv-dl

# Match the host UID (paired with `--userns=keep-id` at run) so emitted files in the
# bind-mounted build dir are owned by the host user, not root.
RUN useradd --create-home --uid 1000 tools
# pnpm supply-chain config is intentionally NOT baked here. tools is emit-only Python with
# no JS installs, and its build context is tools/ (so lib/pnpm/config.yaml is outside it).
# Bake the policy when node deps actually land (phase-3 checkpoint 03-01 finding B).
USER tools
WORKDIR /work

# The console script installed from pyproject ([project.scripts] harnessed-tools).
ENTRYPOINT ["harnessed-tools"]
