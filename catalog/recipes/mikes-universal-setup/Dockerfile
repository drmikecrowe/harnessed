# Recipe Dockerfile for: mikes-universal-setup
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# The recipe is otherwise pure content (rules + skills, no build step). This Dockerfile exists for
# one thing: put `gitleaks-guard` on PATH so the recipe's PreToolUse hook can invoke it. The
# gitleaks binary itself needs no Dockerfile — it comes from the pinned `tools:` mise layer
# (gitleaks@8.30.1) and lands on PATH the same way.
#
# Why a PreToolUse hook and not a git hook: a git hook is bypassable with `--no-verify`, and would
# have to be installed into each project's .git — which the pod SHARES with the host, so a recipe
# has no business mutating it. The harness hook cannot be bypassed by the agent: the Bash tool call
# itself is refused. The HOST half (the user's own `git commit` in a terminal) is what the recipe's
# `setup:` notice nags about — harnessed cannot install onto the host.
USER root

# jq (used to parse the hook payload) comes from the base's mise extra-tools layer — it is in
# catalog/base/extra-tools.default.txt. But that file is a TEMPLATE: the effective list is the
# user-owned ~/.config/harnessed/extra-tools.txt, which they may trim. So jq is not GUARANTEED, and
# the guard fails closed (denies with a clear reason) if it is ever absent, rather than silently
# waving commits through. Nothing to install here.
#
# The build context is the harnessed SOURCE ROOT (`podman build … -f <derived Dockerfile> <hdir>`,
# launcher._build_derived), not this recipe's dir — the assembler inlines recipe Dockerfile bodies
# into one derived Dockerfile and does not rewrite relative paths. So COPY must be root-relative.
# This is the first COPY in any recipe; the consequence of the context rule is that a recipe living
# in the USER overlay (~/.config/harnessed/catalog) could not COPY at all — it is outside the
# context. Fine here: this recipe ships in the repo catalog.
COPY catalog/recipes/mikes-universal-setup/gitleaks-guard /usr/local/bin/gitleaks-guard
RUN chmod 0755 /usr/local/bin/gitleaks-guard

USER harnessed
