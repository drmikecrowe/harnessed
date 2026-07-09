# rtk recipe — implementation plan

Goal: bake the `rtk` ("Rust Token Killer") CLI into a stack so an agent routes high-output
dev commands (`git status`, `cargo test`, `pytest`, …) through rtk and reads 60–90% smaller
output, **without** modelling rtk as an MCP server or a service.

Upstream: <https://github.com/rtk-ai/rtk> · Rust · Apache-2.0 · single static binary.
Latest release **v0.43.0** (2026-06-28) — the README body's "0.28.2" example is stale doc text;
use the releases page as the source of truth for the pin.

> rtk is absent from `docs/todos/2026-06-27-recipe-stress-test.md` (postdates it). The closest
> analogue there is **headroom** (#3, a compression proxy) — but headroom is modelled as a stdio
> **MCP** server. rtk is *not* an MCP server (there is no `rtk mcp`/`rtk serve`); it is a **CLI
> filter + an agent-level command-rewrite mechanism**. So rtk's recipe shape is its own: a Dockerfile
> (bake the CLI) + rtk's own `RTK.md` guidance (no authored skill), with the auto-rewrite hook as a phased enhancement.

## How rtk intercepts output (the load-bearing question)

rtk is a proxy you invoke explicitly (`rtk git status`, `rtk cargo test`, `rtk read file.rs`) that
runs the underlying command and re-emits a filtered/compacted form (smart filtering, grouping,
truncation, dedup). The README's "How It Works" is unambiguous: it sits between the agent and the
shell, not between the agent and the LLM provider.

The **automatic** path — "Auto-Rewrite Hook" — transparently rewrites a Bash command (`git status` →
`rtk git status`) before the shell runs it. The "Supported AI Tools" table is explicit about the
mechanism per agent:

| Agent | Mechanism |
| --- | --- |
| **Claude Code** | **PreToolUse hook (bash)** — `rtk init -g` writes it into `~/.claude/settings.json` |
| Copilot / Cursor / Gemini | PreToolUse / BeforeTool hooks (agent-native hook files) |
| Codex | `AGENTS.md` + `RTK.md` instructions (no hook) |
| OpenCode / Hermes | plugin TS / python (tool-call mutation) |
| Windsurf / Cline / Kilo / Antigravity | project-scoped rules files (`.windsurfrules`, …) |

Two facts that fix the recipe shape:

1. **For Claude Code the mechanism is a Claude-tool-hook (PreToolUse), not a shell/PATH shim.** The
   README documents no aliasing/shimming of `cargo`/`pytest`/etc.; the rewrite happens at the *agent
   Bash-tool* layer. So a `new-session` **launcher** startup-hook cannot replicate rtk's intended
   behaviour by shimming `PATH` (rtk has no such mode, and non-interactive `bash -c` aliases don't
   expand without `shopt -s expand_aliases`). Do not conflate the two hook kinds.
2. **The hook only fires on Bash tool calls.** Claude Code's built-in `Read`/`Grep`/`Glob` bypass it,
   so even with the hook those workflows need explicit `rtk read` / `rtk grep` / `rtk find`. **The
   explicit `rtk` prefixing is needed regardless of the hook** — it is not merely a fallback.

### Is the Claude hook blocked by GAP 2? No — but with caveats

GAP 2 (`docs/todos/2026-06-27-recipe-stress-test.md` "Architecture Gaps") is the absence of a
**declarative recipe `hooks:` field** that the assembler merges into `settings.json`. rtk does **not**
need that field: it ships its own installer (`rtk init -g`) that writes `~/.claude/settings.json`
directly. harnessed already honours installer-baked settings today:

- `emit.merge_settings` (`emit.py:117`) treats the **image-baked** `settings.json` as authoritative
  and only surgically re-applies harnessed's hatago grant. A top-level `hooks` key baked by rtk's
  installer is preserved (the merge mutates only `allow`/`deny`).
- The launcher reads the baked file post-build (`launcher._merge_baked_settings`, `launcher.py:371`,
  via `<rt> cp`) and mounts the merged result `:ro` at `~/.claude/settings.json`
  (`launcher.py:530-532`).
- The profile `.claude` tree is mounted **subdirectory-by-subdirectory** — only `skills/commands/
  agents/hooks/rules` that exist as profile dirs (`launcher.py:536-540`) — **not** as a whole-dir
  overlay. So a baked `~/.claude/RTK.md` is *not* masked, and `~/.claude/hooks/` is masked only if
  *some* recipe in the stack ships a profile `hooks/` dir (none does today).

So the hook is bakeable **today** via `rtk init -g --auto-patch` in the Dockerfile — this is the
image-baked-settings.json path, a distinct mechanism from GAP 2. **However**, the full correctness
(hook entry surviving merge, rewrite script not masked, non-interactive `--auto-patch` working with
no TTY at build) is reasoned from code-reading, not a passing test — it is gated behind a build-time
verification (see "Phasing"/"Risks"). Explicit `rtk` prefixing (Phase 1) is the unconditionally-working baseline either way.

> ⚠️ **`hooks:` namespace collision (flag).** Two unrelated proposals both want the recipe `hooks:`
> field: GAP 2 wants it for **Claude tool-hooks** (`PreToolUse`/`PostToolUse` → `settings.json`); the
> startup-hooks design (`docs/todos/2026-06-29-startup-hooks.md`) wants the same field name for
> **launcher lifecycle hooks** (`new_session`/`pre_agent`/`pre_session`). rtk needs the *former*; the
> startup-hooks feature builds the *latter*. If both land under `hooks:`, they must be namespaced
> apart (e.g. `tool_hooks:` vs `hooks:`) or rtk's declarative form collides with beads' launcher
> hook. Today rtk sidesteps this entirely by baking via its own installer (no recipe `hooks:` field).

## Recipe shape

Dockerfile recipe (bake the pinned `rtk` binary). **No skill shipped** — rtk's own `RTK.md` guidance (baked by `rtk init -g`) + the binary are the surface; a user may add a skill later.
**No MCP, no service, no `mcp:` block, no startup hook** — rtk has no MCP surface and writes nothing
into the project dir, so there is no per-project state to bootstrap (unlike beads/serena).

```
catalog/recipes/rtk/
  recipe.yaml            # name, description
  Dockerfile             # bake the pinned rtk binary (Phase 2: rtk init branched on ${HARNESS})
  PLAN.md                # this file
```

### recipe.yaml

```yaml
name: rtk
description: rtk (Rust Token Killer) — compress dev-command output 60-90% before it reaches the LLM.
```

- No `mcp:`, no `service:`. rtk is a CLI the agent shells out to, not a server.
- No `expect.skills` (no skill shipped). There is no `expect` kind for "a binary runs", so the
  capability is verified manually — `rtk --version` inside the instance (see lifecycle).

### Dockerfile (bake `rtk`)

Primary decision — **pinned release binary** (deterministic; matches beads/codebase-memory guidance;
avoids needing a Rust toolchain at build and sidesteps the crates.io name-collision — another
"rtk" = "Rust Type Kit" exists, so `cargo install rtk` from crates.io gets the *wrong* package).

The Linux x86_64 asset is **musl-static** (`rtk-x86_64-unknown-linux-musl.tar.gz`) → zero runtime
deps, ideal regardless of the base image's glibc. aarch64 hosts fall back to the gnu asset
(`rtk-aarch64-unknown-linux-gnu.tar.gz` — there is no aarch64-musl).

```dockerfile
USER root
ARG RTK_VERSION=0.43.0
# Download the PINNED release tarball (musl-static = zero runtime deps). The version in the URL is the
# reproducibility anchor — no @latest / :latest / floating ref (the assembler pin gate rejects those).
# If the release ships a checksums file, sha256-verify against it; otherwise verify the version post-install.
RUN set -euo pipefail; \
    arch="$(uname -m)"; \
    case "$arch" in \
      x86_64)  asset="rtk-x86_64-unknown-linux-musl.tar.gz" ;; \
      aarch64) asset="rtk-aarch64-unknown-linux-gnu.tar.gz" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/rtk.tgz \
      "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/${asset}"; \
    # [optional, if checksums.txt ships:] curl -fsSL -o /tmp/checksums.txt \
    #   "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/checksums.txt" \
    #   && grep " ${asset}\$" /tmp/checksums.txt | sha256sum -c - ; \
    tar xzf /tmp/rtk.tgz -C /tmp; \
    install -m 0755 /tmp/rtk /usr/local/bin/rtk; \
    rm -rf /tmp/rtk*; \
    rtk --version   # sanity: prints "rtk ${RTK_VERSION}"
USER harnessed
```

Alternatives (documented, not primary):
- `RUN cargo install --git https://github.com/rtk-ai/rtk --tag v${RTK_VERSION}` — `--tag` pins
  (avoids the crates.io collision), but needs a Rust toolchain in the build image (heavier).
- `brew install rtk` — not a build path (Homebrew on a Linux container is the wrong tool; floating).

> **Phase 2 (auto-rewrite hook) — append under `USER harnessed`, branched on `${HARNESS}` (the build
> arg the assembler re-declares).** Only the agents that consume `~/.claude/settings.json`
> (claude/omp/opencode per `launcher.py:531`) get the hook; others fall back to explicit `rtk` prefixing (no skill shipped):
> ```dockerfile
> USER harnessed
> # Bake rtk's PreToolUse rewrite hook into ~/.claude/settings.json for settings.json-based agents.
> # The launcher preserves installer-baked settings via _merge_baked_settings (emit.merge_settings keeps
> # the baked `hooks` key, re-applying only harnessed's hatago grant). Gated on verification (see Risks).
> RUN case "${HARNESS}" in \
>       claude)        rtk init -g --auto-patch ;; \
>       omp|opencode)  rtk init -g --auto-patch --opencode ;; \
>       *)             echo "rtk: no auto-rewrite for harness '${HARNESS}'; explicit-prefix mode" ;;
>     esac
> ```
> `--auto-patch` is rtk's documented non-interactive/CI flag. **Verify at build** that it does not
> require a TTY and that `rtk init --show` confirms the hook + `RTK.md` landed.

## Data model / state

rtk keeps **no project-dir state** (unlike beads/serena/solidspec) — nothing is written into the
bind-mounted project, so **no `new-session` startup hook is needed** to bootstrap anything. State
lives under the `harnessed` user's home:

- **Config:** `~/.config/rtk/config.toml` — `[hooks] exclude_commands`, `[tee] enabled/mode`.
- **Tee logs + analytics:** `~/.local/share/rtk/` — `tee/<ts>_<cmd>.log` (full output on failure) and
  the `rtk gain` stats / `rtk session` / `rtk discover` aggregates.

Because the instance is long-lived (PID-1 `sleep infinity`; agent = re-attachable exec), these persist
across re-attaches **within an instance's lifetime** but are lost on `--fresh`/recreate. That is
fine: they are analytics/cache/recovery logs, not load-bearing. The recipe does **not** mount a named
volume for them (ephemeral is acceptable; if a user wants durable `rtk gain` history, that's a
user-overlay concern). Telemetry is **opt-in, off by default** (`rtk telemetry enable`); a defensive
`RTK_TELEMETRY_DISABLED=1` may be set in the config to guarantee no collection in-harness.

## Test stack

```yaml
# catalog/stacks/claude_rtk/stack.yaml
name: claude_rtk
harness: claude
recipes: [rtk]
```

## Build / test lifecycle

```bash
harnessed build claude_rtk    # assemble + build derived image (supply-chain pin gate runs here)
harnessed claude_rtk          # launch the instance (no startup hook for rtk)
harnessed test  claude_rtk    # (no skill; verify `rtk --version` manually)
```

Manual verification (no skill is asserted — verify the *behaviour* directly):

- `rtk --version` prints `rtk 0.43.0` and `rtk gain` runs (correct package — not "Rust Type Kit").
- `rtk git status` / `rtk ls .` inside the instance produce compacted output with a smaller token
  footprint than the raw command; exit codes propagate.
- *(Phase 2 only)* `rtk init --show` lists the installed PreToolUse hook; after a Claude Code
  session a plain `git status` (no `rtk` prefix) returns rtk-compacted output — confirming the baked
  hook survived `_merge_baked_settings` and fires on Bash tool calls.
- *(Phase 2 only)* `Read`/`Grep` outputs are **not** auto-compacted (expected — Bash-only scope);
  explicit `rtk read`/`rtk grep` is required there.

## Phasing

1. **Ship now (robust, harness-agnostic):** `recipe.yaml` + `Dockerfile` (pinned binary). The rtk
   binary is available; the agent prefixes high-output commands with `rtk` (learns the surface from
   `rtk --help` / `RTK.md`). Zero core-feature dependency, works on every harness, covers the
   Bash-bypass gap. Captures the per-command savings; only the *automation* (100% transparent
   adoption) is missing.
2. **Phase 2 — auto-rewrite hook (gated on build verification):** add the `${HARNESS}`-branched
   `rtk init -g --auto-patch` block to the Dockerfile for claude/omp/opencode. Gives transparent
   Bash-command rewriting (the README's "most effective" mode). Unblocks on confirming: (a) the
   PreToolUse entry survives `emit.merge_settings`, (b) rtk's rewrite script is not masked by a
   profile `hooks/` mount (true for an rtk-only stack; fragile in a multi-recipe stack that ships a
   `hooks/` dir — flag), (c) `--auto-patch` is truly non-interactive with no TTY at build.
3. **Not needed / out of scope:** a recipe `hooks:` *declarative* field (GAP 2) — rtk bakes via its
   own installer, so the declarative field is unnecessary for rtk. Track the `hooks:` namespace
   collision (GAP-2 tool-hooks vs startup-hooks launcher hooks) separately; do not let rtk depend on
   its resolution.

## Risks / checks

- **Pin determinism (main build risk).** The version-in-URL pin must pass the assembler pin gate (no
  floating refs). Confirm at `harnessed build`: a checksums file may or may not ship with the release
  — verify against it if present, else rely on the version pin + `rtk --version` post-install.
  Resolve which at build.
- **Name collision.** `cargo install rtk` (crates.io) yields the wrong package. The primary path
  (release binary) avoids this entirely; if the cargo alternative is used it MUST be
  `--git … --tag v<x>` (never bare `cargo install rtk`).
- **Phase-2 hook viability (unverified).** The image-baked-settings.json path exists today, but rtk's
  multi-file init (`settings.json` + `RTK.md` + rewrite script) against harnessed's managed profile
  is reasoned, not tested. Gate Phase 2 on the three checks in step 2 above. If any fails, **stay on
  Phase 1** (explicit-prefix) — it loses only automation, not compression.
- **Bash-only scope.** Even with the hook, `Read`/`Grep`/`Glob` are uncompressed. The explicit
  `rtk read/grep/find` path is first-class (the agent learns it from RTK.md / `rtk --help`); do not
  promise 100% coverage.
- **Harness branching.** `rtk init -g` is Claude-shaped; omp/opencode use `--opencode`; gemini/codex/
  antigravity use rules-files/plugins that are project-scoped or plugin-native (not settings.json) and
  are out of scope for the Dockerfile-bake path — those harnesses get the binary only (explicit `rtk` prefixing).

## References

- Upstream README + "How It Works" / "Auto-Rewrite Hook" / "Supported AI Tools":
  <https://github.com/rtk-ai/rtk>
- Install reference: `INSTALL.md` (<https://github.com/rtk-ai/rtk/blob/develop/INSTALL.md>)
- Releases (pin source of truth): <https://github.com/rtk-ai/rtk/releases>
- harnessed settings.json handling: `src/harnessed/emit.py` (`merge_settings`/`write_settings_json`),
  `src/harnessed/launcher.py` (`_merge_baked_settings`, `_build_mount_args` `.claude` mount)
- Closest analogue + GAP 2: `docs/todos/2026-06-27-recipe-stress-test.md` (headroom #3, GAP 2)
- Recipe model: `docs/guides/recipe-authoring.md`; quality-bar reference: `catalog/recipes/beads-team/README.md`
