# headroom recipe — implementation plan

Goal: expose headroom's **MCP compression tools** (`headroom_compress` / `headroom_retrieve`
/ `headroom_stats`) in a stack as a stdio MCP child of hatago, so the agent can shrink large tool
outputs, logs, and JSON **on demand** before reasoning over them.

Upstream: <https://github.com/headroomlabs-ai/headroom> · PyPI `headroom-ai` (latest **0.27.0**,
Apache-2.0, `requires_python >=3.10`). Python with a Rust/ONNX core; the published wheel is
`py3-none-any` (pure-Python — the heavy core loads at runtime, only when an ML compressor runs).

## Mode resolution (the nuance this recipe turns on)

Headroom ships **four** modes. Only one is in scope for harnessed today:

| Mode | What it is | In scope? |
| --- | --- | --- |
| **MCP server** — `headroom mcp serve` (stdio) / `--transport http` | Exposes `headroom_compress`/`retrieve`/`stats` as **tools the LLM calls explicitly**. Compression is local, on-demand; originals cached 1 h (CCR). | **YES — this recipe.** |
| **Proxy** — `headroom proxy --port 8787` + `ANTHROPIC_BASE_URL=…` | A network intermediary between the agent and the LLM provider; compresses *all* traffic in flight. | **NO — deferred** (GAP: network-intermediary model). |
| **Agent wrap** — `headroom wrap claude\|codex\|…` | Starts the proxy + rewrites the agent's base URL. Proxy under the hood. | **NO — deferred** (same proxy model). |
| **Library** — `compress(messages)` | Inline Python/TS call in an app. | n/a (no server to host). |

The stress-test doc is *internally consistent* once read carefully: its Tier-1 "headroom MCP"
entry is the MCP-server mode (clean fit); its Tier-4 "headroom proxy mode" is the proxy/wrap modes
(out of scope). **This recipe implements the MCP-server mode only.** The proxy/wrap modes need a
network-intermediary model harnessed does not have — see "Deferred: proxy mode".

**GAP 2 (Claude-tool-hooks) does NOT apply.** Headroom's MCP mode is plain on-demand MCP tools,
*not* Claude Code `PreToolUse`/`PostToolUse` hooks. There is no settings.json hook registration to
merge. The only path to *automatic* compression is the proxy (deferred). With MCP mode, compression
happens only when the agent chooses to call the tool — so the agent calls `headroom_compress`
directly when it judges an output too large (no skill is shipped; no hooks required).

## Recipe shape

**stdio MCP child.** No recipe Dockerfile, no service, no hooks. No skill — upstream ships none; a
user may add one later.

```
catalog/recipes/headroom/
  recipe.yaml
  PLAN.md
```

Why stdio (not the HTTP transport headroom also offers):

- **stdio is upstream's documented default for local Claude Code** (`headroom mcp install` →
  command-based, stdio). The harness agent and hatago share one pod network namespace, so from the
  agent's view the server is local — stdio via hatago is the natural fit (same shape as the `time`
  tracer bullet).
- **HTTP (`headroom mcp serve --transport http`) is documented for "agents running on a different
  machine"** — that maps to a `catalog/services/headroom/` sidecar. headroom is **stateless**
  (1-hour TTL cache, no shared state across instances), so a long-lived sidecar that outlives
  instances is the wrong lifecycle. stdio is lighter and matches the tool's nature.
- The HTTP sidecar is noted below as the **fallback** if the recipe→hatago baking gap (see Risks)
  proves too awkward to ship via a base-image edit.

### recipe.yaml

```yaml
name: headroom
description: >
  Context compression via the headroom MCP server — headroom_compress / headroom_retrieve /
  headroom_stats. On-demand JSON/code/structured compression (60–95% fewer tokens); originals
  retrievable via CCR. MCP-tools mode only (no proxy).

# stdio child: hatago spawns `headroom mcp serve` and wraps its stdio → the single HTTP endpoint
# the harness talks to. transport is explicit (RESEARCH Pitfall B). The `headroom` CLI must be
# available INSIDE the hatago image (see "Baking headroom into hatago" — recipes cannot yet put it
# there, so a base-image edit is required today).
mcp:
  servers:
    - name: headroom
      command: headroom
      args: [mcp, serve]
      transport: stdio

```

> No `expect:` block: the MCP server is probed automatically by the capability test (like `time`).

### Baking headroom into the hatago image (the one non-obvious step)

A stdio child runs **inside hatago's container**, so the `headroom` CLI must exist in the **hatago
image**, not the derived harness image. A recipe Dockerfile builds the harness image and **cannot
reach the hatago image** — there is no recipe→hatago baking mechanism today (confirmed:
`baked-servers.json` is emitted by `emit.write_baked_manifest` but never read by the build; the
hatago image is built statically from `catalog/base/Dockerfile.hatago`, where `mcp-server-time` is
hand-baked via `ARG` + `uv tool install`).

So headroom is baked **exactly the way `mcp-server-time` is** — an edit to the shared
`catalog/base/Dockerfile.hatago`:

```dockerfile
# In catalog/base/Dockerfile.hatago (the SHARED hatago image — NOT a recipe Dockerfile).
# headroom runs as a hatago stdio child, so the `headroom` CLI must live in THIS image.
# [mcp] extra only: mcp + httpx + core (tiktoken/pydantic/ast-grep-cli). Deliberately NOT [all]
# — see Risks. The py3-none-any wheel installs with no Rust toolchain. Pinned (no @latest).
ARG HEADROOM_VERSION=0.27.0
RUN uv tool install "headroom-ai[mcp]==${HEADROOM_VERSION}"
# Silence the once-daily PyPI update check (the netns-wide egress firewall blocks it anyway;
# --stateless/CI skips it, but be explicit for a long-lived hatago child).
ENV HEADROOM_UPDATE_CHECK=off
```

This is the same proven pattern as `MCP_SERVER_TIME_VERSION`/`uv tool install "mcp-server-time==…"`
already in that file. The recipe declares the server; the base-image edit bakes the binary.

## Test stack

```yaml
# catalog/stacks/claude_headroom/stack.yaml
name: claude_headroom
harness: claude
recipes: [headroom]
```

## Build / test lifecycle

```bash
# 1. bake headroom into the hatago image (one-time base-image edit, see above) — rebuild hatago:
harnessed build claude_headroom   # assemble → build base/hatago (picks up the edit) → derived image + scan
harnessed claude_headroom         # launch the pod; hatago spawns `headroom mcp serve` as a stdio child
harnessed test  claude_headroom   # capability report: ✓ headroom (mcp) connected
```

Manual verification (the capability test only confirms the MCP server connected — verify the
*behavior*):

- `headroom mcp serve` boots cleanly under hatago and lists `headroom_compress`/`_retrieve`/`_stats`
  (visible via `/mcp` in Claude Code).
- Calling `headroom_compress` on a large JSON blob returns `compressed` + `hash` + a non-zero
  `savings_percent`; `headroom_retrieve(hash)` returns the original within the 1-hour TTL.
- **Offline:** with the egress firewall active (default), `[mcp]` compression still works — it pulls
  no runtime assets (no ONNX/HF fetch). Confirm no egress to `pypi.org`/`cdn.pyke.io`/`huggingface.co`
  occurs during a compress call.

## Phasing

1. **recipe→hatago baking not yet built (today):** ship `recipe.yaml` + the hand-edit to
   `catalog/base/Dockerfile.hatago` (`uv tool install "headroom-ai[mcp]==0.27.0"`).
   This is exactly how `mcp-server-time` ships — proven, deterministic, firewall-safe.
2. **recipe→hatago baking built (future):** generalize the hatago build to consume the per-stack
   `baked-servers.json` manifest (already emitted by `emit.write_baked_manifest`) so a recipe's
   stdio server is baked automatically — no base-image edit. The recipe.yaml above needs no change;
   drop the manual `Dockerfile.hatago` edit. This unblocks every stdio MCP recipe beyond `time`.

> If the base-image edit is judged too cross-cutting for a single recipe, the **fallback shape** is
> an HTTP sidecar: `catalog/services/headroom/` (own Dockerfile running
> `headroom mcp serve --transport http --port 8080`, `service.yaml` with `port: 8080`) referenced
> `service: headroom, transport: http`. It sidesteps the hatago-baking gap (self-contained image)
> at the cost of a heavier, always-on container for a stateless tool. Prefer stdio per the
> reasoning above.

## Deferred: proxy mode

`headroom proxy` / `headroom wrap <tool>` is a **network intermediary** between the agent and the
LLM provider (the agent's base URL is pointed at the proxy, which compresses every request in
flight). Harnessed does not model this: the harness member talks **directly** to the LLM provider,
and there is no seam to inject a transparent compression proxy into that path. Supporting it would
require a network-intermediary model (route the harness's LLM egress through a local proxy, manage
its lifecycle, handle per-provider auth passthrough). Out of scope — tracked as the stress-test's
Tier-4 "headroom proxy mode". The MCP recipe above is the supported way to get headroom's
compression into a stack today.

## Risks / checks

- **recipe→hatago baking gap (the central risk).** A stdio child must be baked into the hatago
  image; recipes can't do that today, so a `catalog/base/Dockerfile.hatago` edit is required. This
  is the same constraint every stdio MCP recipe beyond `time` hits, and it is the thing to verify
  at `harnessed build` (if `headroom` isn't on hatago's PATH, the stdio child fails to spawn and the
  capability test reports headroom disconnected). The `baked-servers.json` manifest is already the
  artifact a future per-stack hatago build would consume.
- **`[mcp]` vs `[all]`.** Use `[mcp]` only. `[all]`/`[ml]` pull `torch`/`transformers`/
  `onnxruntime`/`huggingface-hub` (≈GBs) and trigger **runtime fetches** of the ONNX core
  (`cdn.pyke.io`) and the Kompress model (`huggingface.co`). The egress firewall is
  **netns-wide** (`egress-firewall.sh` comment: "unblocks the whole pod, including the hatago MCP
  proxy") and defaults OUTPUT to DROP — those hosts are not whitelisted, so `[all]` would fail at
  first compress unless pre-provisioned (`HF_HUB_OFFLINE=1` + a pre-downloaded model, or
  `ORT_STRATEGY=system` + `ORT_LIB_LOCATION`). `[mcp]` has none of this and compresses structured
  JSON/code offline. Trade-off recorded: `[mcp]` lacks the ML prose compressor (Kompress); prose
  compression is weaker. Acceptable for v1.
- **Maturity / churn.** 0.27.0, classifier "Development Status :: 4 - Beta", fast-moving
  (0.10 → 0.27 in ~2 months). Pin the exact version (`==0.27.0`); expect to bump it often. Verify
  the pinned version's `headroom mcp serve` stdio contract (tool names) is stable across bumps.
- **Update-check phoning home.** Set `HEADROOM_UPDATE_CHECK=off` in the hatago image (headroom's
  once-daily PyPI probe would otherwise be a blocked egress → startup warning).
- **No double-compression illusion.** Be clear in the stack docs: MCP mode compresses *only what
  the agent explicitly passes to the tool*. It is not the transparent, whole-traffic 60–95% the
  proxy headlines — that requires the deferred proxy mode.
