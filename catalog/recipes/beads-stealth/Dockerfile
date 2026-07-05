# Recipe Dockerfile for: beads-stealth
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Bake the `bd` CLI (https://github.com/gastownhall/beads): a single native binary that bundles
# embedded Dolt — local-first, git-free persistent task memory for agents. Primary install path =
# the pinned release binary, verified against the release checksums.txt (deterministic; matches
# beads' own security guidance, and avoids pnpm postinstall fragility).
#
# Alternative (npm path): `RUN pnpm add -g @beads/bd@${BEADS_VERSION}` as USER harnessed. pnpm may
# skip the package's binary-fetch postinstall, so a build using that path MUST verify `bd` runs and
# that pnpm's global bin is on PATH for the harnessed user. (The emit lint rejects raw npm/npx — use
# pnpm.) Not used here; the release binary is the deterministic primary path.
USER root
# Pin to the exact release tag (no @latest / :latest / --branch — the assembler pin gate rejects
# floating refs). Verify the downloaded tarball against the release's checksums.txt before install.
# Asset naming verified against the real release (goreleaser-style `beads_<ver>_<os>_<arch>.tar.gz`,
# not the musl-triple naming this Dockerfile originally assumed): v1.0.5 does not exist upstream
# (404) — v1.0.4 is the actual latest tag as of this fix.
ARG BEADS_VERSION=1.0.4
RUN set -eu; \
    case "$(uname -m)" in \
      x86_64)  asset="beads_${BEADS_VERSION}_linux_amd64.tar.gz" ;; \
      aarch64) asset="beads_${BEADS_VERSION}_linux_arm64.tar.gz" ;; \
      *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    base="https://github.com/gastownhall/beads/releases/download/v${BEADS_VERSION}"; \
    cd /tmp; \
    curl -fsSL "${base}/${asset}" -o "${asset}"; \
    curl -fsSL "${base}/checksums.txt" -o checksums.txt; \
    grep -F "${asset}" checksums.txt > expected.sha256; \
    sha256sum -c expected.sha256; \
    tar -xzf "${asset}"; \
    install -m 0755 bd /usr/local/bin/bd; \
    rm -rf /tmp/*
# Smoke test: a runnable binary also catches an arch/libc mismatch the checksum cannot (e.g. a glibc
# build landing on a musl base, or the wrong arch). Fails the build loudly instead of at first run.
RUN bd --version
# Bake a harness-aware `bd setup` wrapper. `bd init --stealth` (run once per project, see recipe.yaml)
# only configures git-exclude — per beads' own docs/SETUP.md, wiring the SessionStart hook + minimal
# CLAUDE.md/AGENTS.md section is a SEPARATE step: `bd setup <tool> --stealth`. recipe.yaml's
# `init.run` is one fixed string shared by every harness a stack might use, so it can't branch on
# $HARNESS at runtime — this is the one place that may (per the harness-independent-recipes
# convention): ${HARNESS} is a build-time ARG, resolved once here into a tiny wrapper on PATH.
#
# --project (not global): ~/.claude/settings.json inside the container is harnessed's own read-only
# profile mount (see launcher.py's settings.json bind-mount) — bd can't write hooks there. `--project`
# writes .claude/settings.local.json into the bind-mounted project root instead, which is writable
# and persists on the host like any other project file.
RUN case "${HARNESS}" in \
      claude) printf '#!/bin/sh\nexec bd setup claude --project --stealth\n' > /usr/local/bin/bd-setup-agent ;; \
      *) printf '#!/bin/sh\n# no bd setup recipe for harness "%s" yet (see beads docs/SETUP.md)\n' "${HARNESS}" > /usr/local/bin/bd-setup-agent ;; \
    esac; \
    chmod +x /usr/local/bin/bd-setup-agent
USER harnessed
# BEADS_DIR is now a static ENV pointing at the host-persisted project-scoped bind-mount
# ($HOME/.beads → $XDG_DATA_HOME/harnessed/persist/beads/<git-common-dir-hash>/.beads/).
# Because the mount target is a fixed container path (not $PWD-relative), the ENV is safe
# to bake here — it won't vary across projects. The bd binary writes its embedded Dolt DB
# to this path; `bd init --quiet --stealth` (run once via `harnessed init`) creates it.
ENV BEADS_DIR=/home/harnessed/.beads
