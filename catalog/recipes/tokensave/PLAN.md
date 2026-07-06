# tokensave recipe — implementation plan

Goal: make `tokensave` available in a stack as a **pre-indexed semantic code knowledge graph** — 80+ MCP
tools over a libSQL graph in `.tokensave/`, 100% local, so the agent queries symbols/call-graphs/impact
instead of grepping files.

Upstream: <https://github.com/aovestdipaperino/tokensave> · Rust · MIT · current release **v7.0.2**
(`Cargo.toml` `version = "7.0.2"`, latest GitHub release tag `v7.0.2`, 2026-06-24). Single ~24 MB native
binary, all 50+ tree-sitter grammars bundled, zero runtime deps. (The stress-test's "`0.8.0`" is obsolete
pre-restructure; everything below is re-derived from the live source.)

> [!IMPORTANT]
> **Contingent on the hatago consolidation**
> ([docs/todos/2026-06-29-hatago-consolidation.md](../../todos/2026-06-29-hatago-consolidation.md)).
> tokensave is a stdio MCP server that indexes the project. hatago is the MCP interface — it wraps
> stdio→HTTP ([emit.py:160-171](../../src/harnessed/emit.py)) — so tokensave is a plain stdio child. The
> only dependency is landing hatago in the harness container so the stdio child sees the project mount.
> Until that lands, this recipe is correct in shape but cannot index (no project) — do not ship it.

## Recipe shape

```
   harness container  (hatago in-container; project bind-mounted)
     hatago  ──stdio──►  tokensave serve   (sees the project; .tokensave/ lands in it)
     hatago serves one Streamable-HTTP endpoint :3535  ──►  agent connects
```

tokensave is a stdio server that hatago spawns as a child. It runs in the harness container, so `tokensave
serve` inherits the project as cwd and indexes it. Recipes already bake into the harness image
(`Dockerfile.harnessed-<stack>`), so the binary install is an ordinary recipe Dockerfile step. **No skill
is shipped** — upstream offers none; the 80+ tools are discovered via the native tool surface.

```
catalog/recipes/tokensave/
  recipe.yaml
  Dockerfile                # bake pinned v7.0.2 binary + vendored git-hook scripts
  hooks/                    # OPTIONAL — needs startup-hooks; see "Freshness" below
    new-session.sh          # tokensave init (when .tokensave/ absent) + git-hook install
    post-commit             # vendored upstream script — runs `tokensave sync`
    post-checkout           # vendored upstream script — runs `tokensave init` on fresh clone
  PLAN.md
```

### recipe.yaml

```yaml
name: tokensave
description: tokensave — pre-indexed semantic code knowledge graph (80+ tools, 50+ languages, 100% local).
expect:
  mcp: [tokensave]
mcp:
  servers:
    - name: tokensave
      command: tokensave
      args: [serve]
      # transport: stdio (default). hatago spawns it in-container → it sees the project.
# hooks:                    # OPTIONAL freshness enhancement (needs startup-hooks, not the consolidation).
#   new_session:
#     script: hooks/new-session.sh
#     when_missing: .tokensave
```

The MCP server itself needs **no** startup-hooks — hatago spawns the stdio child. Only the optional
git-hook install (below) needs startup-hooks.

### Dockerfile

Primary install decision — prebuilt **release binary + sha256 verify**. tokensave bundles 50+ C
tree-sitter grammars into one ~24 MB binary; `cargo install` would recompile all of them (slow, needs
Rust in the build image). The prebuilt path needs **no Rust at build or runtime**. Pin to the exact tag —
no `@latest` / `:latest` / `--branch` (assembler rejects floating refs).

Verified values for v7.0.2 (release API `assets[].digest`):

- x86_64-linux: `tokensave-v7.0.2-x86_64-linux.tar.gz` →
  `d35519fe698a24d2e2bb5622e94b3bdb4794dc1e36acffc980260b50afb40460`
- aarch64-linux: `tokensave-v7.0.2-aarch64-linux.tar.gz` →
  `69c88d0617036d44f2620f5779cd8578fad77664c2373d64de632b8e346ad334`

```dockerfile
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
# Vendored upstream git-hook scripts (scripts/post-commit, scripts/post-checkout) — see Freshness.
COPY hooks/post-commit hooks/post-checkout /opt/tokensave/hooks/
RUN chmod 0755 /opt/tokensave/hooks/post-commit /opt/tokensave/hooks/post-checkout
USER harnessed
```

> **Verify at first build:** (a) the tarball extracts a top-level `tokensave` binary (confirm the internal
> path; adjust the `install` source if nested); (b) `tokensave --version` / `tokensave doctor` run on the
> harnessed base; (c) `Cargo.toml` pulls `ort … ["load-dynamic"]`; tokensave's search is keyword-based (no
> embeddings), so `libonnxruntime` is almost certainly *not* required for the core graph tools — confirm
> `tokensave status` doesn't demand it.
>
> Alternative tokensave install (only if prebuilt is unsuitable): `cargo install tokensave
> --version ${TOKENSAVE_VERSION}` (pinned) — slow (recompiles 50+ grammars), needs Rust in the build image.

## Freshness (OPTIONAL — git hooks, needs startup-hooks)

`tokensave serve` self-freshens without any hooks: it does an on-demand staleness check on every MCP call
(30 s cooldown) plus catch-up sync on connect. So the graph stays current by itself once the server is up.

The **git hooks** (`post-commit` → `tokensave sync`; `post-checkout` → `tokensave init` on fresh clone)
add an explicit immediate re-index after a commit. They are an enhancement, not required for the MCP tools
to work. Installing them into the project's `.git/hooks/` needs the **startup-hooks** feature
([docs/todos/2026-06-29-startup-hooks.md](../../todos/2026-06-29-startup-hooks.md)) — a *separate,
lighter* dependency from the consolidation. Until it lands, the agent (or the user) can install the hooks
manually, or simply rely on the on-demand staleness check.

`hooks/new-session.sh` (sketch, for when startup-hooks lands):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Runs once (when .tokensave/ is absent), cwd = project root. Idempotent.
tokensave init
if [ -d .git/hooks ]; then
  cp /opt/tokensave/hooks/post-commit   .git/hooks/post-commit
  cp /opt/tokensave/hooks/post-checkout .git/hooks/post-checkout
  chmod +x .git/hooks/post-commit .git/hooks/post-checkout
fi
```

Vendored hook scripts (copied verbatim from upstream `scripts/`, 458 B + 529 B):

- `hooks/post-commit` — `if command -v tokensave … && [ -d ".tokensave" ]; then tokensave sync &; fi`
- `hooks/post-checkout` — on `PREV_HEAD = 000…0` (fresh clone): `tokensave init &`. (Irrelevant in the
  harness — the project is bind-mounted, not cloned — but harmless on branch switches and matches upstream.)

> **Do NOT run the full `tokensave install` in the harness.** It writes MCP registration, Claude tool-hooks,
> CLAUDE.md and a *global* `core.hooksPath`, all of which fight harnessed's profile assembly. Install only
> the two git-hook scripts per-repo, as above.

## Data model

- **`.tokensave/`** in the project root — the libSQL graph DB (`tokensave.db`, WAL), created by
  `tokensave init`, updated incrementally by `tokensave sync`. Per-project. Persists on the host via the
  project bind-mount; gitignore it.
- **`~/.tokensave/`** (harnessed HOME) — `global.db` (per-call `savings_ledger`), `pricing.json`
  (24 h-cached LiteLLM pricing), `config.toml`.

No service, no volume, no external DB — libSQL is embedded (WAL, async). Single-writer file lock: one
instance per project is fine; two instances on the same project dir contend.

## Test stack

```yaml
# catalog/stacks/claude_tokensave/stack.yaml
name: claude_tokensave
harness: claude
recipes: [tokensave]
```

## Build / test lifecycle

```bash
harnessed build claude_tokensave   # assemble + build derived image (pin gate + sha256 verify)
harnessed claude_tokensave         # launch; hatago spawns tokensave serve as a stdio child
harnessed test  claude_tokensave   # capability report: ✓ tokensave (mcp) connected
```

Gated on the consolidation. Manual verification (the capability test only checks the MCP is connected;
verify *behaviour*):

- After launch against a fresh project, `.tokensave/` exists **on the host** (bind-mount) and
  `tokensave status` reports indexed files.
- The agent sees `tokensave_*` MCP tools through hatago and `tokensave_context`/`search` return
  **project-scoped** results (proves the stdio child is indexing the mounted project).
- A commit inside the instance (with the optional git hooks installed) triggers a background
  `tokensave sync`; the next `tokensave_status` reflects it.

## Risks / checks

- **cwd / project access:** confirm hatago spawns the stdio child with cwd = project root so `.tokensave/`
  lands in the project (resolve as part of the consolidation). tokensave `serve` resolves its index from
  cwd; an absolute path can be passed if needed.
- **Pin gate / checksum:** `releases/download/v7.0.2/…` must pass ASM-02 pin validation; the per-arch
  sha256 digests are verified in-image. Bumping `TOKENSAVE_VERSION` requires updating both digests (from
  the release API `assets[].digest`).
- **Don't run the full `tokensave install` in the harness.** It writes MCP registration, Claude tool-hooks,
  CLAUDE.md and a *global* `core.hooksPath`, all of which fight harnessed's profile assembly. Install only
  the two git-hook scripts per-repo.
- **`ort` load-dynamic.** `Cargo.toml` uses `ort … ["load-dynamic"]`; confirm the core graph tools run
  without `libonnxruntime.so` (expected — search is keyword-based). Add the lib only if `tokensave status`
  demands it.
- **Concurrency.** libSQL embedded mode is single-writer (file lock). One instance per project is fine; two
  contend.
