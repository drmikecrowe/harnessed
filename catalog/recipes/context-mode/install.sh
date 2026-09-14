#!/usr/bin/env bash
# install.sh — context-mode upstream skills (every harness) + omp plugin (container+omp only).
#
# Three deliverables:
#   1. context-mode CLI/MCP binary — `tools:` in recipe.yaml, both modes. Not this script.
#   2. upstream's own skill suite — copied out of that pinned package, both modes, every harness.
#   3. omp extension — container+omp only: `omp plugin install` (see omp section below).
#
# Env this file may rely on (emit.install_env — same keys host and container):
#   HARNESS, HARNESSED_MODE, HARNESSED_RECIPE_DIR, HARNESSED_CONFIG_DIR, HARNESSED_INSTALL_CACHE
#   HARNESSED_BIN_DIR  the stack bin dir (host) or base image ~/.local/bin (container)
# PROJECT_DIR and friends are absent by design — a build has no project mounted.
#
# The version is NOT declared in this file (AC-1). `tools:` in recipe.yaml owns it and the one use
# below derives it from mise, so the "keep these in lockstep" comment this replaces is gone, and
# with it the drift it invited — #323 is the same shape in another recipe.
set -euo pipefail

# --- CLI install: NOT here -----------------------------------------------------------------------
# `tools: [npm:context-mode@…]` delivers the CLI in BOTH modes now (bd harnessed-1t4.3). It used to
# cover the container only, so this script carried a host-mode `pnpm add -g` branch; a host launch
# applies the same pinned tool spec, so that branch is gone rather than duplicated.

# --- Skill layer: install upstream's suite, do not vendor it ---------------------------------------
# A marketplace install of context-mode carries a `skills/` tree (its plugin.json points at it). The
# recipe wires the MCP server and the hooks directly, so that tree never arrived. This section
# delivers it, for every harness and both modes.
#
# INSTALLED, never vendored. The pin in `tools:` already puts the exact package on disk, so copying
# its skills into the repo would fork upstream prose at a version nothing re-checks — the drift shape
# #323 describes. Copying them out of the pinned package here means the skills and the binary can
# never disagree about the version, and `harnessed update` still has one place to bump.
#
# No `cache:` for the same reason: there is nothing to fetch. `tools:` is the fetch.
: "${HARNESSED_CONFIG_DIR:?install.sh requires HARNESSED_CONFIG_DIR}"

# mise owns the package root. Ask it rather than composing a path from the version — the version
# lives in recipe.yaml alone (AC-1) and must not be restated here.
CM_HOME="$(mise where npm:context-mode 2>/dev/null || true)"
if [ -z "${CM_HOME}" ] || [ ! -d "${CM_HOME}" ]; then
    echo "error: install (context-mode): mise reports no install root for npm:context-mode." \
         "The 'tools:' entry in recipe.yaml is what installs it — the skills ship inside that same" \
         "package and cannot be copied without it." >&2
    exit 1
fi

# The layout UNDER that root is the package manager's, not mise's, and this recipe cannot pin either:
# the base image installs mise unpinned (`curl https://mise.run`), and the npm backend shells out to
# whichever manager `npm.package_manager` names — pnpm in a harnessed build, the default elsewhere.
# Measured against mise 2026.9.1 with the default backend: <root>/node_modules/<pkg>. The other
# globs cover the shapes the same backend has used — `npm install -g --prefix` (lib/node_modules),
# pnpm's versioned global dir (<root>/<n>/node_modules), and pnpm's CONTENT-ADDRESSED one, which
# nests a second level: <root>/v11/<hash>/node_modules. That fourth shape is what mise 2026.9.1
# actually writes today on both linux and macOS, so the three-candidate ladder matched nothing and
# aborted every launch of this recipe. Probed in order, and the failure below names all four rather
# than reporting a bare "not found".
#
# `[ -d ]` and not `find -type d`: pnpm links the package into node_modules as a SYMLINK into its
# store, so a type test that does not follow links rejects the very directory being looked for.
SKILLS_SRC=""
for candidate in \
    "${CM_HOME}"/node_modules/context-mode/skills \
    "${CM_HOME}"/lib/node_modules/context-mode/skills \
    "${CM_HOME}"/*/node_modules/context-mode/skills \
    "${CM_HOME}"/*/*/node_modules/context-mode/skills; do
    if [ -d "${candidate}" ]; then
        SKILLS_SRC="${candidate}"
        break
    fi
done
if [ -z "${SKILLS_SRC}" ]; then
    echo "error: install (context-mode): the pinned package has no skills/ dir under ${CM_HOME}." \
         "Looked in node_modules/, lib/node_modules/, */node_modules/ and */*/node_modules/ for" \
         "context-mode/skills. Upstream moved it, or the npm backend changed layout again." >&2
    exit 1
fi

mkdir -p "${HARNESSED_CONFIG_DIR}/skills"
# Named, not globbed. `ctx-upgrade` is upstream's own skill and is DELIBERATELY not installed: it
# pulls latest from GitHub, rebuilds, and updates the npm global. That unpins the binary `tools:`
# pinned, mid-session, inside a stack whose whole build contract is that downloads are pinned. The
# user upgrades by bumping `tools:` in recipe.yaml and rebuilding.
#
# Two upstream strings assume a marketplace plugin install, and both are wrong in a stack, so each
# copied SKILL.md is rewritten in place:
#   1. `/context-mode:ctx-foo` — a plugin-namespaced slash command. Here each skill is fanned
#      standalone into .claude/skills/, so the name is `/ctx-foo`.
#   2. `mcp__context-mode__ctx_foo` — the tool name a direct plugin install produces. Here the
#      server sits behind the hatago hub, so that literal names nothing. The rest of the same
#      corpus already uses the bare `ctx_foo` form, which resolves either way.
# The rewrite is scoped to the dir just copied. Never to the whole skills tree — other recipes fan
# their own skills in there and this recipe does not own their bytes.
#
# `sed` to a temp file and `mv`, never `sed -i`. This script runs on the HOST too, and BSD sed —
# macOS — requires an argument to `-i`, so `sed -i 's#…#…#'` takes the script as the backup suffix
# and then fails on the filename. GNU's `-i` and BSD's `-i ''` cannot both be written as one
# portable invocation, so neither is used.
for skill in context-mode ctx-doctor ctx-index ctx-insight ctx-purge ctx-search ctx-stats; do
    dest="${HARNESSED_CONFIG_DIR}/skills/${skill}"
    rm -rf "${dest}"
    cp -r "${SKILLS_SRC}/${skill}" "${dest}"
    sed 's#/context-mode:ctx-#/ctx-#g; s#mcp__context-mode__ctx_#ctx_#g' \
        "${dest}/SKILL.md" > "${dest}/SKILL.md.tmp"
    mv "${dest}/SKILL.md.tmp" "${dest}/SKILL.md"
done

# --- omp only -------------------------------------------------------------------------------------
# Under omp the bridged Claude hooks are inert for THIS recipe's purposes. As of bridge 0.4.0 the
# SessionStart half would in fact bridge (queued to the next prompt), but PreToolUse
# additionalContext — which is exactly what the routing nudge is — stays unbridged at every version,
# because omp's tool_call result has no context field. 0.4.1 changed only updatedInput and 0.5.0
# added PreCompact (via session_before_compact), so neither moves the nudge; PreCompact is now
# skipped for double-fire with the native extension rather than for being inert. recipe.yaml's
# every hook entry's `skip_harnesses: [omp]` therefore suppresses them, and upstream's own omp extension —
# installed below — takes over, covering session_start / tool_call / tool_result /
# session_before_compact natively. Every other harness uses the hooks and needs nothing here.
if [ "${HARNESS:-}" != "omp" ]; then
    exit 0
fi

# --- container only, and LOUD about it --------------------------------------------------------------
# `omp plugin install` writes into ~/.omp/plugins. Container-side that is an image layer, and it
# SURVIVES launch because the launcher bind-mounts only ~/.omp/agent over it (launcher._omp_agent_mount)
# — the same path Dockerfile.harnessed-omp uses for the hooks bridge itself.
#
# Host-side the same command would write into the USER'S OWN omp installation. That is not harnessed's
# to mutate: ~/.omp is deliberately SHARED host state on a host launch (omp keeps auth, usage, and
# sessions together there, which is why the launcher mounts it read-WRITE rather than isolating it),
# there is no per-stack omp plugin root to redirect the install into, and anything installed would
# persist after the stack is gone — a write outside $HARNESSED_CONFIG_DIR and outside the install
# cache, i.e. exactly the class of side effect a host launch must not have. So: skipped on host, and
# announced. Never silently (bd harnessed-8px.1).
#
# Consequence, stated plainly: `harnessed launch --host` with HARNESS=omp gets context-mode's MCP
# server and CLI (via install.sh above) but NOT the native omp extension, so the four omp-native
# event handlers are absent in that combination. Run the stack in a container to get them.
if [ "${HARNESSED_MODE:-}" != "container" ]; then
    echo "WARNING install (context-mode): 'omp plugin install context-mode@<tools: pin>'" \
         "SKIPPED on a host launch — it writes into your own ~/.omp/plugins, which harnessed does" \
         "not own or mutate. Run this stack in a container to get the native omp extension." >&2
    exit 0
fi

# Derived HERE, at the ONLY point of use — not at the top of the script. Deriving it up front made
# every harness and both modes depend on mise being present, including the two paths that never
# install the plugin at all. The tests caught that immediately.
#
# `mise current <tool>` prints the resolved version alone: no jq (the base image ships none) and no
# column parsing. FAIL CLOSED on empty — for a tool it does not know, mise warns to stderr, prints
# NOTHING and exits 0, so an unguarded read would run `omp plugin install context-mode@` and leave
# omp to interpret that. Silence must not become an empty version.
CONTEXT_MODE_VERSION="$(mise current npm:context-mode 2>/dev/null || true)"
if [ -z "${CONTEXT_MODE_VERSION}" ]; then
    echo "error: install (context-mode): mise reports no installed version for npm:context-mode." \
         "The 'tools:' entry in recipe.yaml is what installs it — the omp plugin cannot be pinned" \
         "without it." >&2
    exit 1
fi

omp plugin install "context-mode@${CONTEXT_MODE_VERSION}"

# --- VERIFY it landed -----------------------------------------------------------------------------
# `omp plugin install` exiting 0 is not proof the extension is present, and a half-installed one is
# INVISIBLE downstream: recipe.yaml's per-entry `skip_harnesses: [omp]` suppresses the bridged Claude
# hooks precisely BECAUSE this extension replaces them, so if it is missing, context-mode runs with
# its MCP server and none of its four native handlers — no routing steering, no session continuity.
#
# Nothing else catches that. `expect:` cannot: `expect.plugins` probes ~/.claude/plugins (Claude
# plugins), not ~/.omp/plugins, and `expect: mcp: [context-mode]` only proves the hub connected,
# which it does either way. Observed live in an omp pod whose `omp plugin list` carried only the
# hooks bridge while `harnessed test` stayed green.
#
# Pure-shell `case` rather than grep/rg: the base image ships neither reliably (same reason the
# version read above avoids jq).
INSTALLED_PLUGINS="$(omp plugin list 2>/dev/null || true)"
case "${INSTALLED_PLUGINS}" in
    *context-mode*) ;;
    *)
        echo "error: install (context-mode): 'omp plugin install" \
             "context-mode@${CONTEXT_MODE_VERSION}' reported success but the plugin is ABSENT from" \
             "'omp plugin list'. Its four omp-native handlers (session_start / tool_call /" \
             "tool_result / session_before_compact) would be silently missing, and the bridged" \
             "Claude hooks are suppressed on omp by design, so the recipe would deliver its MCP" \
             "server with no steering and no session continuity." >&2
        exit 1
        ;;
esac
