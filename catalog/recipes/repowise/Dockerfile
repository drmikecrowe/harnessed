# Recipe Dockerfile for: repowise
#
# Bakes the repowise CLI (repowise-dev/repowise, PyPI `repowise`, AGPL-3.0) into the AGENT image.
# hatago spawns it as a stdio child (`repowise mcp --transport stdio`) — see recipe.yaml.
#
# No `FROM` and no `ARG HARNESS` here — the assembler prepends `FROM harnessed-${HARNESS}:latest`
# and re-declares `ARG HARNESS` after it, so recipes stay harness-independent. `uv` is a mise
# global in harnessed-base (on PATH via the mise shims) and `~/.local/bin` is on PATH, so the
# baked `repowise` resolves at runtime with no extra PATH wiring.
USER harnessed
# Pin repowise to an exact version (PyPI artifact; canonical install per upstream docs). `==0.27.0`
# is an exact pin → passes validate_pin (no `@latest`/`:latest`/`--branch`). Build-time network
# fetches Python 3.13 + repowise's deps (tree-sitter grammars, sqlite-vec, …) — not firewalled at
# build time. Bump REPOWISE_VERSION to update.
ARG REPOWISE_VERSION=0.27.0
RUN uv tool install -p 3.13 "repowise==${REPOWISE_VERSION}"
