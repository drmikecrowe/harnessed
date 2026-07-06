# Recipe Dockerfile for: tokensave
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Primary install decision: prebuilt RELEASE BINARY + sha256 verify. tokensave bundles 50+ C
# tree-sitter grammars into one ~24 MB native binary; `cargo install` would recompile all of them
# (slow, and needs Rust in the build image). The prebuilt path needs NO Rust at build or runtime.
# Pin to the exact tag — no @latest / :latest / --branch (the assembler pin gate rejects floating refs).
#
# CONTINGENT on the hatago consolidation: the binary install itself is an ordinary recipe Dockerfile
# step and builds fine standalone, but `tokensave serve` can only index once the project is bind-mounted
# into the harness container by hatago.
#
# The optional upstream git-hook scripts (post-commit/post-checkout) are NOT baked here: installing
# them per-repo needs the startup-hooks feature, which is a separate, not-yet-landed dependency.
USER root
ARG TOKENSAVE_VERSION=7.0.2
RUN set -euo pipefail; \
    case "$(uname -m)" in \
      x86_64)  arch=x86_64;  sum=d35519fe698a24d2e2bb5622e94b3bdb4794dc1e36acffc980260b50afb40460 ;; \
      aarch64) arch=aarch64; sum=69c88d0617036d44f2620f5779cd8578fad77664c2373d64de632b8e346ad334 ;; \
      *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    asset="tokensave-v${TOKENSAVE_VERSION}-${arch}-linux.tar.gz"; \
    url="https://github.com/aovestdipaperino/tokensave/releases/download/v${TOKENSAVE_VERSION}/${asset}"; \
    curl -fsSL "$url" -o "/tmp/${asset}"; \
    echo "${sum}  /tmp/${asset}" | sha256sum -c -; \
    tar -xzf "/tmp/${asset}" -C /tmp; \
    install -m 0755 /tmp/tokensave /usr/local/bin/tokensave; \
    rm -rf "/tmp/${asset}" /tmp/tokensave; \
    tokensave --version
USER harnessed
