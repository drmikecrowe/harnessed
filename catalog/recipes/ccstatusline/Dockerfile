# Recipe Dockerfile for: ccstatusline
#
# No FROM and no `ARG HARNESS` — the assembler prepends `FROM harnessed-${HARNESS}:latest` and
# re-declares `ARG HARNESS` after it, so ${HARNESS} is available here and recipes stay
# harness-independent.
#
# Two layers:
#  1. Install the pinned `ccstatusline` npm CLI through mise's `npm:` backend. harnessed-base already
#     ships mise + shims on PATH and sets `npm.package_manager pnpm`, so the install routes through
#     the managed pnpm supply-chain config (no raw npm/npx). mise creates the bin shim at
#     ~/.local/share/mise/shims/ccstatusline — the exact path Claude Code's statusLine command points
#     at. Pinned via CCSTATUSLINE_VERSION (a floating @latest would fail the assembler pin gate).
#  2. Bake the matching `statusLine` block into ~/.claude/settings.json. statusLine is a Claude Code
#     concept, so this is gated on ${HARNESS} = claude; other harnesses are unaffected. The launcher's
#     emit.merge_settings carries this baked key through verbatim while re-applying harnessed's own
#     required settings (the hatago grant), so the status line survives the post-build merge.
USER harnessed
ARG CCSTATUSLINE_VERSION=2.2.22
RUN mise use -g "npm:ccstatusline@${CCSTATUSLINE_VERSION}" \
 && mise install \
 && test -x "$HOME/.local/share/mise/shims/ccstatusline"

# statusLine is Claude-only: bake it into ~/.claude/settings.json for the claude harness, skip others.
# python (from base's mise python@3.12) does the merge — read existing-or-{}, set statusLine, write —
# so an already-baked settings.json (e.g. another recipe's) keeps its other keys.
RUN if [ "${HARNESS}" = "claude" ]; then \
      python3 -c 'import json,pathlib; p=pathlib.Path.home()/".claude"/"settings.json"; p.parent.mkdir(parents=True,exist_ok=True); d=(json.loads(p.read_text()) if (p.exists() and p.read_text().strip()) else {}); d["statusLine"]={"type":"command","command":"/home/harnessed/.local/share/mise/shims/ccstatusline","padding":0,"refreshInterval":10}; p.write_text(json.dumps(d,indent=2)+chr(10))'; \
    else \
      echo "ccstatusline: statusLine is Claude-only; skipped for HARNESS=${HARNESS}"; \
    fi
