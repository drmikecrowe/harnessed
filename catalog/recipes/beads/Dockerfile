# Recipe Dockerfile for: beads
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
ARG BEADS_VERSION=1.0.5
RUN set -eu; \
    case "$(uname -m)" in \
      x86_64)  asset="bd-${BEADS_VERSION}-x86_64-unknown-linux-musl.tar.gz" ;; \
      aarch64) asset="bd-${BEADS_VERSION}-aarch64-unknown-linux-musl.tar.gz" ;; \
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
USER harnessed
