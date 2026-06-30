# Recipe Dockerfile for: serena
#
# Bakes the serena CLI (oraios/serena, PyPI `serena-agent`, MIT) into the AGENT image. hatago
# spawns it as a stdio child (`serena start-mcp-server …`) — see recipe.yaml.
#
# No `FROM` and no `ARG HARNESS` here — the assembler prepends `FROM harnessed-${HARNESS}:latest`
# and re-declares `ARG HARNESS` after it, so recipes stay harness-independent. `uv` is a mise
# global in harnessed-base (on PATH via the mise shims) and `~/.local/bin` is on PATH, so the
# baked `serena` resolves at runtime with no extra PATH wiring.
USER harnessed
# Pin serena to an exact version (PyPI artifact; canonical install per upstream docs). `==1.5.3`
# is an exact pin → passes validate_pin (no `@latest`/`:latest`/`--branch`). Build-time network
# fetches Python 3.13 + serena's deps (anthropic, pydantic, flask, starlette, tiktoken, …) — not
# firewalled at build time. Bump SERENA_VERSION to update.
ARG SERENA_VERSION=1.5.3
RUN uv tool install -p 3.13 "serena-agent==${SERENA_VERSION}"
