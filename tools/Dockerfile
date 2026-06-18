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
    && apt-get install -y --no-install-recommends jq curl ca-certificates gnupg \
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
# Fixed offline-DB cache location (XDG_CACHE_HOME). osv-scanner honors it, so the pre-seeded
# DB at /opt/osv-cache/osv-scanner/{PyPI,npm}/ is found at scan time regardless of the runtime
# user (owned by uid 1000 = the tools user). Seeded below from representative manifests.
# Phase-3 checkpoint 03-02 fix: the bare `osv-scanner --download-offline-databases` is rejected
# by v2.3.8 ("databases can only be downloaded when running in offline mode"); the DB is seeded
# per-ecosystem by a scan with --download-offline-databases against real manifests, and scans
# use `--offline --offline-vulnerabilities` (network OFF, local DB).
ENV XDG_CACHE_HOME=/opt/osv-cache
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
    && mkdir -p /tmp/osv-seed \
    && printf 'requests==2.19.0\n' > /tmp/osv-seed/requirements.txt \
    && printf '{"name":"osv-seed","version":"1.0.0","lockfileVersion":3,"packages":{"node_modules/left-pad":{"version":"1.3.0"}}}\n' > /tmp/osv-seed/package-lock.json \
    && (osv-scanner scan source --offline-vulnerabilities --download-offline-databases -r /tmp/osv-seed || true) \
    && rm -rf /tmp/osv-seed /tmp/osv-dl \
    && test -d "${XDG_CACHE_HOME}/osv-scanner" \
    && chown -R 1000:1000 "${XDG_CACHE_HOME}"

# [Phase 5 / SEC-01] 1Password CLI (`op`) — CLI only, NOT the desktop app (SEC-01 resolves op://
# refs via varlock at run; op is INERT in the image unless a .env.schema with op:// refs exists).
# Mirrors the apt key-ring + signed-by shape at base/Dockerfile.harnessed-base:27-33 (drops the
# `1password` desktop package — tools needs only the `op` binary). Installed as root before the
# `tools` user is created. gnupg (added above) provides `gpg --dearmor` for the key import.
RUN curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
    gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
    tee /etc/apt/sources.list.d/1password.list && \
    apt-get update && apt-get install -y --no-install-recommends 1password-cli && \
    rm -rf /var/lib/apt/lists/* && \
    op --version

# Match the host UID (paired with `--userns=keep-id` at run) so emitted files in the
# bind-mounted build dir are owned by the host user, not root.
RUN useradd --create-home --uid 1000 tools
# [Phase 5 / SEC-01+SEC-02] pnpm-workspace.yaml (project-scoped lifecycle allowlist). COPY'd as
# root then chowned to the tools user. pnpm v11 reads `allowBuilds` HERE, not from the global
# config.yaml (lib/pnpm/config.yaml:18-23 — the global config rejects it and silently ignores it).
# snyk's postinstall (wrapper_dist/bootstrap.js exec) needs `allowBuilds: {snyk: true}` under
# strictDepBuilds (RESEARCH Pitfall 3 / threat T-05-01). `pnpm add -g` runs from /home/tools so
# pnpm discovers this file for the global install.
COPY pnpm-workspace.yaml /home/tools/pnpm-workspace.yaml
RUN chown tools:tools /home/tools/pnpm-workspace.yaml
USER tools
ENV HOME=/home/tools
# pnpm global binaries (varlock/snyk/socket from `pnpm add -g`) land in PNPM_HOME; mise shims
# (node/pnpm/mise) complete the PATH (mirrors base/Dockerfile.harnessed-base:52).
ENV PNPM_HOME=/home/tools/.local/share/pnpm
ENV PATH="/home/tools/.local/share/pnpm:/home/tools/.local/share/mise/shims:/home/tools/.local/bin:${PATH}"

# [Phase 5] Managed pnpm supply-chain config (mirrors lib/pnpm/config.yaml:13-17). The tools
# build context is tools/ (lib/harnessed-common.sh:83) so lib/pnpm/config.yaml is NOT COPY-able;
# the five policy keys are inlined. allowBuilds lives in pnpm-workspace.yaml above (project-scoped).
RUN mkdir -p /home/tools/.config/pnpm && \
    printf 'minimumReleaseAge: 1440\nminimumReleaseAgeStrict: true\nblockExoticSubdeps: true\nverifyStoreIntegrity: true\nstrictDepBuilds: true\n' \
        > /home/tools/.config/pnpm/config.yaml

# [Phase 5 / SEC-01+SEC-02] mise (runtime manager) + Node@24 + pnpm@11 (the base-image precedent
# at base/Dockerfile.harnessed-base:50-80). npm.package_manager=pnpm routes the npm: tools through
# pnpm so the managed policy governs them (RESEARCH Pitfall 5). Installed as the tools user so
# shims + global bins land under /home/tools (paired with --userns=keep-id at run).
RUN curl -fsSL https://mise.run | bash
RUN cd /home/tools && \
    mise settings set experimental true && \
    mise settings set npm.package_manager pnpm && \
    mise use -g node@24 pnpm@11 && \
    mise install

# [Phase 5 / SEC-01+SEC-02] Secrets + scanner CLIs via pnpm (version-pinned, never @latest).
# All INERT in the image — varlock/op activate only when a .env.schema exists (SEC-01); snyk/socket
# only when their token is in the launcher env (SEC-02, scan.py env-gate). The snyk postinstall
# fetches its platform binary; allowBuilds:{snyk:true} in pnpm-workspace.yaml is the deliberate
# exception to strictDepBuilds (RESEARCH Pitfall 3 / PATTERNS — verified at the checkpoint build).
RUN cd /home/tools && \
    pnpm add -g varlock@1.7.1 @varlock/1password-plugin@1.2.0 snyk@1.1305.1 socket@1.1.122 && \
    varlock --version && \
    snyk --version && \
    socket --version
WORKDIR /work

# The console script installed from pyproject ([project.scripts] harnessed-tools).
ENTRYPOINT ["harnessed-tools"]
