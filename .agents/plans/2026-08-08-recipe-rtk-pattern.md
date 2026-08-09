# SPEC — converge every catalog **recipe and agent** on the rtk pattern

> **REVISION 1** (2026-08-08) — scope extended from recipes to **agents**, after the human observed
> that `harnessed update` does (or will) upgrade agents the same way. Not cosmetic: the agent surface
> is in **worse** condition than the recipe surface, including three genuinely unpinned downloads.
>
> **REVISION 2** (2026-08-08) — issue graph made queryable rather than prose. #261 narrowed to its
> reporting bug and parented; #330 filed for agents. See §5b.
>
> **REVISION 3** (2026-08-08) — D1, D2, D3 answered by the human and **resolved with evidence**.
> Two design changes fell out of the verification: the Family B field cannot auto-resolve 2 of its 4
> pins (S8), and the test runner is container-only, so AC-6 splits host/container (S9).
>
> **REVISION 4** (2026-08-08) — D1a resolved: the Family B mechanism is **`install.refs:`**, not a
> top-level `content:`. Refs move to the manifest; the fetch/copy logic stays in `install.sh`. S4
> answered by reading `emit.install_env`. See D1a.
>
> **REVISION 5** (2026-08-09) — five findings from CodeRabbit's review of PR #331, all valid, all
> addressed: markdown lint; the Family B inventory reconciled across **all seven** refs (which
> turned up a third resolvability class the review's binary framing had no slot for); AC-10 given
> an owning scenario (A7) it previously lacked; the `install.refs` contract specified as a 7-rule
> Phase 0 test plan; and the AC-8 / NC-9 conflict resolved with a fourth status, `UNPINNABLE`.
>
> **REVISION 6** (2026-08-09) — CodeRabbit third pass on PR #331, four findings, all valid:
> A7 must run BEFORE A2–A4 (the list order was executable in the wrong sequence); Dockerfile
> extraction cannot identify an upstream for 3 of 5 agents, so `build_args` gains a declared
> `spec:`; `UNPINNABLE` promoted to a first-class outcome with defined behaviour at every gate;
> Phase 0 and Phase A file lists split.
>
> **APPROVED** 2026-08-08. Later changes to this file are spec drift and must be visible as a
> commit — that is the property this committed copy exists to provide, and that the gitignored
> working copy cannot.

- **Tracker**: [#329](https://github.com/drmikecrowe/harnessed/issues/329) (epic).
  Children: [#261](https://github.com/drmikecrowe/harnessed/issues/261) (reporting),
  [#330](https://github.com/drmikecrowe/harnessed/issues/330) (agents).
- **Working artifacts**: `.old-coder/20260808-233611-recipe-rtk-pattern/` — **gitignored**
  (`.bare/info/exclude`), so it exists only in the author's `main/` checkout and in no worktree.
  THIS committed file is the authoritative copy of the spec; that directory holds the working
  copy plus `logs/` and the eventual `EVIDENCE.md`.
- **Status**: **APPROVED** 2026-08-08 — *"The spec is approved."* No implementation file has
  been touched at the time of this commit. Approval covers the setup plan in §4, including the
  worktree-per-phase isolation and signed checkpoint commits.
- **Tier**: 3 (public catalog surface + supply-chain pinning + a new schema field other people's recipes will depend on).

---

## 0. The correction this spec makes to the request

The request was _"all installs should likely be through mise and not from an install script."_
That is right for roughly half the catalog and **impossible for the other half**. The evidence is in
§1 Family B and D1.

The real invariant is not _"everything through mise"_:

> **Every catalog pin — recipe or agent — is declared once, in its manifest (`recipe.yaml` /
> `agent.yaml`), in a field `harnessed update` can read: auto-bumpable where a registry can answer,
> explicitly `hold:`-marked where it cannot.**

`tools:` is that field for anything that lands a binary on PATH — and it is **correct** there, rtk
included. Content fetches need a sibling field that does not exist yet. That gap is the root cause of
issue #261's Class 1/2, and it is Phase 0.

Agents obey the same invariant and are in worse shape (§1b): three of five are **unpinned outright**,
and the lint CLAUDE.md says rejects unpinned downloads never runs on them.

---

## 1. Measured current state — RECIPES

Inventory taken 2026-08-08 across all 22 recipes in `catalog/recipes/`.

### Family A — tool/binary recipes (mise CAN own the pin)

| Recipe                  | Pin today                                                                                  | Target                                                   | Notes                                                                                                                                                         |
| ----------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **rtk**                 | `tools: github:rtk-ai/rtk@0.44.1`                                                          | _(reference implementation — no change)_                 | one pin, wiring-only `install.sh`, `tests/rtk-runs.sh`                                                                                                        |
| agentmemory             | `tools: npm:@agentmemory/mcp@0.9.28`                                                       | compliant; add `tests/`                                  |                                                                                                                                                               |
| repowise                | `tools: pipx:repowise@0.37.0`                                                              | compliant; add `tests/`                                  |                                                                                                                                                               |
| pulumi                  | `tools: pulumi@3.255.0`                                                                    | compliant; add `tests/`                                  |                                                                                                                                                               |
| **ccstatusline**        | `tools:` **+** `CCSTATUSLINE_VERSION="2.2.27"`                                             | delete the literal                                       | literal is **unused** by the script (it resolves via `command -v`/`mise which`) — dead weight that already drifted, #323                                      |
| **context-mode**        | `tools:` **+** `CONTEXT_MODE_VERSION="1.0.169"`                                            | feed it from `tools:`                                    | literal **is load-bearing**: `omp plugin install context-mode@$VER`                                                                                           |
| **serena**              | `tools:` **+** `SERENA_VERSION="1.6.1"`                                                    | delete the literal                                       | literal is **unused** (`serena init -b LSP` only)                                                                                                             |
| **codebase-memory-mcp** | `CBM_VERSION="0.9.0"` + hand-rolled `mise use -g`/`mise install` in shell; **no `tools:`** | `tools: github:DeusData/codebase-memory-mcp@0.9.0`       | already uses the mise `github:` backend, just in shell. Host branch symlinks into `$UV_TOOL_BIN_DIR` — must confirm `tools:` reproduces that on a host launch |
| **tokensave**           | Dockerfile `ARG TOKENSAVE_VERSION=7.0.2` + curl + hard-coded per-arch sha256               | `tools: ubi:…` **(UNVERIFIED — S1)**                     | if `ubi:` resolves, the Dockerfile deletes and both sha256 literals go with it                                                                                |
| **solidspec**           | Dockerfile `ARG SOLIDSPEC_REF=v0.3.0` + `cargo install --git … --tag`                      | `tools: cargo:…` **(UNVERIFIED — S2)**                   | Dockerfile **cannot fully vanish**: it also `apt-get install`s `cmake pkg-config` as root. Target = system deps only, zero version literals                   |
| **gsd-core**            | `GSD_CORE_VERSION="1.6.1"` + `pnpm dlx @opengsd/gsd-core@$VER`                             | `tools: npm:…` then invoke the bin **(UNVERIFIED — S3)** | only if the package ships a `bin`                                                                                                                             |

### Family B — content recipes (mise CANNOT own the pin)

| Recipe                | Ref, and how many places it is written                                                                                                     | What it installs                          |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| caveman               | `CAVEMAN_REF="v1.9.0"` + `cache: v1.9.0` — **2 copies**                                                                                    | `skills/ commands/ agents/`               |
| superpowers           | `SUPERPOWERS_REF="v6.0.3"` + `cache: v6.0.3` — **2 copies**                                                                                | `skills/`                                 |
| hyperpowers           | `HYPERPOWERS_REF="7905547b…"` + `cache: 7905547b…` — **2 copies**                                                                          | `skills/ commands/ agents/`               |
| gstack                | `GSTACK_REF="11de390b…"` + `cache: 11de390b…` — **2 copies**                                                                               | `skills/gstack` + runs upstream `./setup` |
| mikes-universal-setup | `OAKOSS_SHA`, `BLADER_SHA`, `AMINBLG_SHA` + a **synthetic mashed** `cache: "oak0283bed3-hum1b485648-ste379728b5"` — **4 copies of 3 refs** | 7 third-party skills                      |

The `cache:` duplication is **mandated by the current schema**, whose own description reads
_"Keep it equal to the ref pinned inside the script."_ That instruction is #261's Class-3 defect
written into the contract.

#### Resolvability of all SEVEN Family B refs (measured 2026-08-09)

Raised in review of PR #331: the earlier text classified four refs and left mikes-universal-setup's
three unaccounted for, while AC-2 says *every* pin. Checking all seven turned up a **third class**
that neither the review nor the original spec anticipated.

| # | Ref | Repo | Releases | Tags | Pinned as | Class |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | caveman | JuliusBrussee/caveman | 17 | 17 | tag `v1.9.0` | **A** |
| 2 | superpowers | obra/superpowers | 11 | 33 | tag `v6.0.3` | **A** |
| 3 | hyperpowers | withzombies/hyperpowers | **0** | **0** | SHA | **B** |
| 4 | gstack | garrytan/gstack | **0** | **0** | SHA | **B** |
| 5 | `OAKOSS_SHA` | oakoss/agent-skills | **0** | **0** | SHA | **B** |
| 6 | `BLADER_SHA` | blader/humanizer | 2 | 2 | SHA | **C** |
| 7 | `AMINBLG_SHA` | AminBlg/SimpleEnglish | 1 | 1 | SHA | **C** |

- **Class A — tag-pinned, releases exist.** `_github_releases` resolves them. Auto-bumpable in
  mechanism; still `hold:` by the #240 policy, but the hold reason is *policy*, and it can be lifted
  by decision alone.
- **Class B — SHA-pinned, no releases and no tags.** There is nothing for any resolver to return.
  `hold:` is **structural**, not policy: lifting the policy would change nothing. Reason string must
  say so, or a future reader will "fix" a hold that is not fixable.
- **Class C — SHA-pinned, but releases exist.** *This is the class the review's binary
  auto-bumpable/held framing has no slot for.* The resolver CAN list candidate releases, but it
  **cannot order a raw SHA against a tag** — it cannot tell whether the pinned commit is before or
  after `v1.2.3`, so it cannot say whether an "upgrade" is an upgrade. Offering a bump here risks a
  silent DOWNGRADE.
  - **Decision required (part of S8, not deferrable past Phase 3)**: either (a) migrate the pin from
    a SHA to a tag, making it Class A and losing the exact-commit guarantee #240 chose deliberately,
    or (b) hold it with the reason *"SHA-pinned by design; releases exist but are not orderable
    against a commit."* **Recommend (b)** — #240 picked SHA pinning because the vercel CLI's
    tag/branch pinning was the exposure, and undoing that to gain a bump prompt trades a security
    property for convenience.

**So the honest S8 answer is 2 / 3 / 2, not 4-or-2.** Two auto-bumpable in mechanism, three
structurally unresolvable, two resolvable-but-not-orderable. Every one of the seven ends with an
explicit `hold:` and a reason naming which class it is — which is what AC-2 requires, and it is why
AC-2 is satisfiable even though five of seven can never be auto-bumped.

### Family C — no pin at all

`default`, `floating-recipe`, `greet`, `openbrain-example`, `ping`, `time` — local content only.
In scope only for the `tests/` requirement, and only where they install something.

---

## 1b. Measured current state — AGENTS (`catalog/agents/`) → #330

`update.py` contains **no agent awareness whatsoever** (`rg agent src/harnessed/update.py` returns
only unrelated matches). The pin surface it cannot see:

| Agent           | Where the pin lives                                                                                   | Verdict                                                                                                          |
| --------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **omp**         | `agent.yaml` `build_args: {OMP_VERSION: "17.2.11"}`; Dockerfile `ARG OMP_VERSION` **with no default** | **the reference implementation** — the agent-side rtk                                                            |
| opencode        | Dockerfile `ARG OPENCODE_VERSION=1.17.9` **with a default**; nothing in `agent.yaml`                  | pinned but **invisible** to `update.py` — #261 Class 2, agent edition                                            |
| **codex**       | `mise use -g npm:@openai/codex` — **no version at all**                                               | **UNPINNED**, resolves `@latest` at build. `schema.py:1354` names this exact defect for the recipe path          |
| **claude**      | `RUN curl -fsSL https://claude.ai/install.sh \| bash`                                                 | **UNPINNED**                                                                                                     |
| **antigravity** | `RUN curl -fsSL https://antigravity.google/cli/install.sh \| bash`                                    | **UNPINNED** (installer does verify sha512 against Google's signed manifest — integrity yes, reproducibility no) |

`agent.schema.json` already describes `build_args` as _"The single source of truth for pinned tool
versions … the agent Dockerfile's matching ARG carries no default."_ omp follows it; four do not.

### Why the lint did not catch three unpinned agents

`validate_pin` (`src/harnessed/schema.py:2182`) rejects `--branch main`, `:latest`, `@latest` and
moving clone/archive refs. Two independent gaps:

1. **Scope.** Called from `assemble()` for **recipe** Dockerfiles only — its error string is literally
   `f"recipe '{recipe_name}': …"`. `catalog/base/Dockerfile.harnessed-*` is never linted.
2. **Pattern.** Even in scope it would miss these. `npm:@openai/codex` contains no `@latest` token;
   `curl .../install.sh` contains no ref at all. **Absent** is not **floating**, and the regex only
   knows floating.

So CLAUDE.md's _"Pin every download … The build rejects them"_ is, on the agent surface, enforced by
nothing.

### Also found (uncommitted, in the working tree)

`catalog/agents/omp/agent.yaml` has an unstaged `OMP_VERSION: 16.4.6 → 17.2.11`; its `description:`
two lines below still reads _"omp (via mise, pinned v16)"_. A fourth instance of this epic's class,
created by hand, minutes before the audit.

### The third pin surface

`catalog/base/extra-tools.default.txt` — [#248](https://github.com/drmikecrowe/harnessed/issues/248)
reports it _pins nothing_, so `dua` resolves `@latest` and the base image build is broken. Same
class. See D5.

### Test coverage today

`tests/*.sh` exists for **2 of 22** recipes: `rtk` (`rtk-runs.sh`), `caveman` (`hook-fires.sh`).
Discovery is convention-based (`discover_recipe_tests`, `src/harnessed/capability.py:223` — any
`*.sh` under `catalog/recipes/<name>/tests/`, exit 0 == pass), copied into the live instance via
`podman cp` and exec'd (`run_recipe_tests`, same file).

---

## 2. Decisions

### D1 — RESOLVED. `tools:` is correct; it just cannot reach five recipes.

**Asked**: _"You are saying `tools: github:rtk-ai/rtk@0.44.1` isn't the right vehicle?"_

**No — it is exactly right, and it stays the vehicle** for everything that lands a binary on PATH:
rtk today, and codebase-memory-mcp / tokensave / solidspec / gsd-core as targets. §0's original
wording was imprecise. The claim is not "`tools:` is wrong", it is "`tools:` cannot reach Family B".
Now measured rather than argued:

The mise `github:`/`ubi:`/`aqua:` backends are **release-asset installers** — they resolve through
the GitHub _releases_ API (`_REPO_BACKENDS`, `_github_releases`; `src/harnessed/update.py:306,329`),
download an arch-matched asset, and put an **executable on PATH**. Queried 2026-08-08:

| Repo                    | Releases | Assets on latest    |
| ----------------------- | -------- | ------------------- |
| JuliusBrussee/caveman   | 17       | **none** (tag-only) |
| obra/superpowers        | 11       | **none** (tag-only) |
| withzombies/hyperpowers | **0**    | —                   |
| garrytan/gstack         | **0**    | —                   |

`tools: github:JuliusBrussee/caveman@v1.9.0` has **no asset to download**; hyperpowers and gstack
have no release at all, which is exactly why they pin raw commit SHAs. And even a successful asset
install would land a file on PATH — it would not copy `skills/ commands/ agents/` into
`$HARNESSED_CONFIG_DIR`, which is these recipes' entire job. Two independent reasons, either
sufficient.

**Design consequence found only by checking**: I had claimed the Family B field (now `install.refs:`,
see D1a) would resolve through the existing `_github_releases`. That works for caveman and
superpowers. It returns **nothing** for hyperpowers and gstack. Those two are `hold:`-with-a-reason
**by necessity, not by policy** — unless the resolver also learns tags/commits. This is **spike S8**,
and it is the difference between "4 pins auto-bumpable" and "2 of 4".

### D1a — RESOLVED. Refs move to the manifest; the FETCH stays in `install.sh`.

**Asked**: *"For Family B — can we put the ref(s) in the recipe so update has one place to check?"*

**Yes. That is the whole fix, and it is smaller than the `content:` field I originally specced.**

My first draft called the field `content:` and modelled `repo` + `ref` + destination. That name
implied harnessed would do the fetching and copying. **It should not**, and that distinction is the
design:

| Concern | Owner | Why |
|---|---|---|
| **Declaring the pin** | `recipe.yaml` | It is data. `update` needs one place to look. |
| **Performing the install** | `install.sh` | It is not uniform, and declaring it would mean inventing a DSL. |

The second row is load-bearing. The five Family B installs are genuinely different: caveman copies
**three** directories; superpowers copies **one**; gstack copies one, then runs upstream `./setup`,
then `./bin/gstack-config set redact_prepush_hook true -- /ship`; mikes-universal-setup fetches
**three separate repos** and cherry-picks **seven** named skills, one of which is a single file
rather than a directory. Expressing that in YAML is a mini-language with a parser, and it would be
the least-tested code in the change. `install.sh` already does it, correctly, today.

**So: declare the refs, keep the script.**

Multi-ref example, using the hardest real case — `mikes-universal-setup` declares **three**:

```yaml
install:
  script: install.sh
  refs:
    oakoss: # ref KEY: ^[a-z][a-z0-9_]*$ (see contract below)
      repo: oakoss/agent-skills # owner/repo — what `update` queries
      ref: 0283bed313563d5677a0838f4bf921b03296cf6c # tag or FULL SHA; floating rejected as for tools:
      hold: "structural: repo publishes no releases or tags" # class-naming reason, per AC-2
    blader:
      repo: blader/humanizer
      ref: 1b48564898e999219882660237fde01bf4843a0f
      hold: "not-orderable: SHA-pinned by design; releases exist but cannot be ordered against a commit"
    aminblg:
      repo: AminBlg/SimpleEnglish
      ref: 379728b51981b6d2ee1de0f201164483a9648972
      hold: "not-orderable: SHA-pinned by design; releases exist but cannot be ordered against a commit"
```

#### The `install.refs` contract — settled BEFORE Phase 0 writes code

Raised in review of PR #331: the first draft showed one ref and left the mechanics implied. Implied
mechanics become whatever the first implementation happened to do. Each rule below gets an executable
test in Phase 0; **this list is the Phase 0 test plan**, not commentary.

1. **Ref key syntax**: `^[a-z][a-z0-9_]*$`, unique within a recipe. Rejected at schema validation,
   not at env-emit time — a bad key must fail the build with a message naming the key, not produce a
   silently missing variable.
2. **Key → env mapping is deterministic and total**: key `oakoss` yields exactly
   `HARNESSED_REF_OAKOSS` and `HARNESSED_REPO_OAKOSS` (uppercase; the key charset admits no other
   transformation, which is why the charset is restricted rather than the mapping made clever).
   `HARNESSED_REPO_*` carries `owner/repo`, NOT a URL — the script composes the URL, so a recipe
   switching from `git clone` to a tarball fetch needs no manifest change.
3. **Collisions.** The first draft of this rule was **unreachable, and therefore untestable**
   (caught in review of PR #331, second pass): it declared a schema error when a ref key collides
   with `HARNESS` / `MODE` / `CONFIG_DIR` / …, but rule 2 prefixes every emitted name with
   `HARNESSED_REF_` or `HARNESSED_REPO_`, so no valid key can ever produce one of those. A test for
   it could only ever pass vacuously — the exact defect mutation testing exists to catch, written
   directly into a spec. **Deleted.** What replaces it is the collision that IS reachable:
   - **Key-to-key**: impossible under rule 1 (unique keys, restricted charset). One test asserts it
     rather than trusting it, since rule 1 is what makes rule 2's mapping total.
   - **Namespace reservation (the real risk, and it is forward-looking)**: `HARNESSED_REF_*` and
     `HARNESSED_REPO_*` become a namespace owned exclusively by `refs:`. A test asserts that
     `install_env`'s own fixed key set contains **no** key matching `^HARNESSED_(REF|REPO)_`. Today
     it trivially passes; its job is to fail the day someone adds a general-purpose
     `HARNESSED_REF_DIR`, which — because `install_env` keys are applied LAST and win — would
     silently shadow a recipe's ref and hand the script an empty variable. That is the failure mode
     the `install_env` docstring exists to prevent, and this is the version of the rule that can
     actually detect it.
4. **Ordering is irrelevant to behaviour and must be proven so.** YAML mappings carry no meaningful
   order; the emitted env is a dict. The one place order could leak is the derived cache key, which
   rule 6 pins.
5. **`hold:` scope is the single ref**, matching `tools:[].hold`. A recipe with three refs may hold
   one and auto-bump two. A hold never licenses a floating ref (`tools:` already establishes this).
6. **Cache identity is derived, deterministic, and order-independent.** Under-specifying this
   (as the first draft did — "hash `key=repo@ref` joined by `\n`", with no algorithm named) lets two
   implementations produce different keys for identical inputs, which surfaces as cache misses or,
   worse, a producer and a consumer disagreeing about which cache entry is which. Fully specified:
   - **Canonical input**: refs sorted by key (byte order; the rule-1 charset makes this unambiguous),
     each rendered `key=repo@ref`, joined with a single `\n`. **No trailing newline.**
   - **Encoding**: UTF-8. **Digest**: SHA-256. **Output**: lowercase hex, **truncated to the first 16
     characters** — short enough to read in a path, and 64 bits of collision resistance against an
     accidental collision (this is not a security boundary; the refs themselves carry the integrity).
   - **Golden test vector**, from the real `mikes-universal-setup` refs, asserted verbatim in Phase 0:

     ```text
     canonical input (no trailing newline):
     aminglg=AminBlg/SimpleEnglish@379728b51981b6d2ee1de0f201164483a9648972
     blader=blader/humanizer@1b48564898e999219882660237fde01bf4843a0f
     oakoss=oakoss/agent-skills@0283bed313563d5677a0838f4bf921b03296cf6c

     sha256   = efbbcb7c70f8e3912984eed2e7c50613848a93773a4c2e69a2040be1e73c8e88
     cache key = efbbcb7c70f8e391
     ```

   - Consequences that must be tested, because each has bitten this repo before: changing ANY ref
     changes the key (so a stale cache cannot be served); reordering the YAML does NOT (so a
     cosmetic edit does not force a refetch); and the key is a fixed-length digest, which is what
     stops the `oak0283bed3-hum1b485648-ste379728b5` hand-mashing pattern from returning as an
     auto-generated version of itself.
7. **`refs:` and a hand-written `cache:` together is a schema error**, not a precedence rule (NC-5).

Each of 1–7 gets a schema/update unit test. Rule 2 additionally needs a test asserting the generated
environment for a real multi-ref recipe, since that is the rule an implementer is most likely to
satisfy "close enough".

`install.sh` then consumes what it used to declare — the Family B equivalent of rtk's `rtk --version`
guard:

```bash
# was: CAVEMAN_REF="v1.9.0"; CAVEMAN_REPO="https://github.com/JuliusBrussee/caveman.git"
: "${HARNESSED_REF_CAVEMAN:?}"          # ref, from install.refs
: "${HARNESSED_REPO_CAVEMAN:?}"         # owner/repo, so the URL is not a second copy either
```

**This answers the naming question too**: `install.refs`, not a top-level `content:`. The block
already owns `script:` and `cache:`, which are exactly the two things refs relate to. Nothing new at
the top level.

**What it buys, per acceptance criterion:**

- **AC-2** — `update` has one place to check. `repo` resolves through the existing
  `_github_releases` where releases exist (S8); `hold:` marks the rest as *deliberate*, not
  *unresolved*.
- **AC-1** — the ref is written once. Today it is 2 copies for four recipes, and **4 copies of 3
  refs** for mikes-universal-setup.
- **`cache:` becomes derived**, not hand-written, from the declared refs. The schema instruction
  *"Keep it equal to the ref pinned inside the script"* is deleted — it is the #261 Class-3 defect
  written into the contract. mikes-universal-setup's hand-mashed
  `oak0283bed3-hum1b485648-ste379728b5` is computed instead of maintained.
  - **Backward compat (NC-5)**: `cache:` stays valid on its own. Where `refs:` is present, a
    hand-written `cache:` is **rejected as a conflict** rather than silently losing — two sources for
    one key is the defect being removed.
  - **One-time cost**: a derived key differs from today's hand-written one, so every Family B recipe
    takes one cache miss on first launch after the migration. It is a content cache; it repopulates.
    Say so in the PR rather than letting someone discover a slow first build.

**Plumbing verified, not assumed** — this was spike S4, now answered. `emit.install_env`
(`src/harnessed/emit.py:727`) is a flat `dict[str, str]`, applied **last** so it wins over both the
inherited environment and the recipe's own `env:` (`test_install_env_precedence` asserts this in both
modes). Adding derived `HARNESSED_REF_*` / `HARNESSED_REPO_*` keys fits without changing its shape.

> One invariant to respect: the docstring promises *"identical KEYS in host and container mode."*
> Per-recipe ref keys vary **by recipe**, never **by mode**, so the invariant holds — and it is
> **already pinned by an existing, ungated test**:
> `tests/test_live_verification_debt.py::TestHostHomeShim::test_the_install_env_exports_both_vars_in_both_modes`,
> parametrized over `["host", "container"]`, with no `HARNESSED_PODMAN` gate. So this is a regression
> guard that already runs — not a test to write. `install.refs` must not break it, and if adding
> per-recipe keys makes its key-set comparison fail, that is a real signal, not a test to relax
> (anti-gaming rule 1).
>
> *Found by `search_graph`, not by hand — see the note in §5 on tooling.*

**Rejected, with reasons**: declaring the copy/fetch semantics in YAML (a DSL, per the table above);
teaching `update.py` to parse shell/Dockerfiles (its own docstring refuses this, and the ref stays
duplicated); waiting for the vercel `skills` CLI (#240 proves it cannot pin to a SHA and does not
verify hashes); overloading `tools:` with a fake backend (breaks the "binary on PATH" meaning
`emit`/`capmatrix` rely on).

### D2 — RESOLVED: 5 PRs, approved.

Each phase is its own old-coder loop and its own PR. Phase 0 changes the schema (a public contract
with a JSON-schema URL users reference); bundling 20 recipe migrations into that PR would make the
schema change unreviewable. Per D6, **Phase A (agents) goes first** — it needs no schema change.

### D3 — RESOLVED. Yes: tests validate the install, post-assembly. The runner only does half of that.

**Answered**: _"tests should run after assembling the host/container. these validate the install,
right?"_ — Yes, that is the contract, and rtk's `tests/rtk-runs.sh` already meets it: binary resolves
on PATH, `rtk --version` identifies itself, `rtk gain` works, and the hook is present in the
**assembled** `settings.json`.

**But the runner is container-only.** Verified: every path in `run_recipe_tests` goes through
`podman cp` / `podman exec` (`_cp` at `src/harnessed/capability.py:315`, `_exec` at `:299`,
`_exec_script` at `:327`). There is **no host-launch test path at all**.

That matters more than the #250 gate, because **the host branch is where install logic is most
conditional and least verified**: rtk's `install.sh` carries a long comment on why the host branch
used to refuse to install and now does not; codebase-memory-mcp's host branch symlinks into
`$UV_TOOL_BIN_DIR` while its container branch does not; ccstatusline resolves its binary differently
in each. None of that divergence is testable today.

**Resolution — AC-6 splits in two:**

- **AC-6a (host)** — run each recipe's `tests/*.sh` against a **host** assembly. **Needs no podman**,
  so it can run in `tools/run-tests.sh` and CI _today_. Requires a host execution path in
  `capability.py` beside the podman one.
- **AC-6b (container)** — the existing podman path, still gated on #250.

This converts Phase 4 from _blocked_ to _partly shippable_, and gives the new tests a home that
actually executes. It also addresses #250's second direction (_"make the skip loud in aggregate"_):
a host layer that runs is a layer whose absence is visible.

**Spike S9 gates it**: can a host assembly complete in CI (mise present, network for `tools:`
installs, no podman)? If not, AC-6a is local-only and D3 reverts to "block Phase 4 on #250". Do not
write 20 test files on the assumption until S9 answers.

### D4 — spike results can invalidate targets

S1/S2/S3 are marked UNVERIFIED. If a spike fails, that recipe's target changes and this spec gets a
visible revision, not a silent one.

### D5 — is `catalog/base/extra-tools.default.txt` in scope?

**Recommended: no — track it as #248, and hold AC-2 to "every recipe and agent pin".** Same class,
but a base-image concern with its own open issue and its own failure mode (a broken build, not
silent drift). Folding it in triples Phase 0's blast radius.

### D6 — phase order: agents first?

**Recommended: yes — Phase A before Phase 0.** Three reasons: (1) three agents are genuinely
unpinned right now, which is live exposure rather than drift; (2) it needs **no new schema field** —
`build_args` exists and omp proves the shape; (3) it lands the **lint** (A6) that stops the class
regressing, before 20 recipe migrations start moving pins around.

Against: A2/A3/A4 change which CLI version users get — a behaviour change disguised as a pinning
change. **S7** exists to make that visible rather than accidental.

---

## 3. Executable acceptance criteria

### The pattern contract — RECIPES

- **AC-1 — one pin, one place.** Every upstream version/ref string appears exactly once across
  `recipe.yaml`, `install.sh`, `Dockerfile`.
  _Test_: lint scanning each recipe dir for `*_VERSION=`/`*_REF=`/`ARG *_VERSION` literals; fails if
  the value also appears in `recipe.yaml`, or appears nowhere in it.
- **AC-2 — every pin is reachable.** `harnessed update --check` classifies every catalog pin as
  _resolvable_ or _held with a stated reason_. The **unresolved** list is empty.
  - "Every pin" means **all seven** Family B refs (see §1 Family B), not one per recipe —
    mikes-universal-setup declares three. A per-recipe count would pass while two refs went
    unclassified.
  - A `hold:` reason must name its class (policy / structural / not-orderable). "held" alone is not
    a stated reason, and a structural hold mislabelled as policy invites a future reader to lift
    something that cannot be lifted.
- **AC-3 — `install.cache` is never reported as an upstream pin.** **Delegated to child #261.**
- **AC-4 — `install.sh` performs no version-bearing download** whose version it declares itself.
- **AC-5 — first line of defence is a guard.** Every recipe whose `tools:` delivers an executable has
  `<tool> --version` in `install.sh` before any wiring (rtk's pattern).
- **AC-6 — every installing recipe has a behavioural test, run POST-ASSEMBLY against the real
  install.** It must (a) invoke the thing installed, (b) assert it identifies itself where a name
  collision is possible, and (c) assert the **assembled** wiring is present (`settings.json` entry,
  skill file on disk, MCP server connected) — not merely that a file exists.
  - **AC-6a (host)** — the same scripts run against a host assembly, no podman. Gated on S9.
  - **AC-6b (container)** — the existing podman path. Gated on #250.
  - A recipe whose install differs between modes must be asserted in **both**. A single-mode pass for
    a two-mode recipe is `SUBSTITUTED`, not `PASSED`.

### The three pin outcomes — one vocabulary, all gates

Raised in review of PR #331 (third pass): AC-9 rejected every unversioned installer, AC-10 admitted
only *resolved* or *held*, NC-9 said "hold it", and AC-8 said `hold:` does not apply. Four gates,
four different answers for one agent. An implementer could not tell whether Phase A passes.

**There are exactly three outcomes.** Every gate below uses these words and no others.

| Outcome | Means | Declared as |
| --- | --- | --- |
| **RESOLVED** | pinned, and a registry can answer "is there a newer one" | `{value, spec}` |
| **HELD** | pinned; bumping is deliberately manual | `{value, spec?, hold: "<reason>"}` |
| **UNPINNABLE** | **not pinned**, because no version selector exists that preserves integrity (NC-9) | `{unpinnable: "<reason naming the integrity mechanism>"}` |

`UNPINNABLE` is **not** a flavour of HELD. HELD is pinned and chosen; UNPINNABLE is unpinned and
conceded. Collapsing them would let an unpinned installer inherit HELD's "this is fine" reading —
the fabricated pass AC-8 exists to prevent.

Per gate:

- **Lint (AC-9)** — rejects an unversioned acquisition **unless** that agent's manifest declares
  `unpinnable:` with a non-empty reason. The escape hatch is explicit and reviewable in the diff,
  never inferred from the Dockerfile's shape. A bare `curl … | bash` with no declaration still fails.
- **Update report (AC-10)** — three sections, not two. UNPINNABLE entries appear under their own
  heading with the reason verbatim, never inside *unresolved* (which means "should have resolved and
  did not" — an actionable defect) and never inside *held* (which means "resolvable, deliberately
  frozen").
- **Phase gate (Phase A)** — Phase A **passes** with UNPINNABLE agents present, provided each is
  declared with a reason. It **fails** on any undeclared unpinned agent. Blocking the phase on the
  worst agent would leave codex — trivially pinnable, unambiguously broken — unpinned for longer.
- **EVIDENCE** — an UNPINNABLE agent is reported as a known limit, in the same register as the
  podman blind spot. Reproducibility and integrity are different properties; a report that averages
  them into one green tick is lying by aggregation.

### The pattern contract — AGENTS (#330)

- **AC-7 — the pin lives in `agent.yaml`, never in the Dockerfile.** Every agent declares its CLI
  version in `build_args:`; the matching Dockerfile `ARG` carries **no default**.
- **AC-8 — no unpinned download in any agent image.** codex, claude, antigravity each acquire their
  CLI at a version named in `agent.yaml`.
  - **Conflict with NC-9, resolved here** (raised in review of PR #331). AC-8 demands a version;
    NC-9 forbids buying one by bypassing a verifying installer. If S5/S6 finds an installer that
    cannot take a version without losing its signature check, those are not both satisfiable, and
    **`hold:` does not rescue it**: a held unversioned installer is still unpinned, and recording it
    as AC-8-compliant would be a fabricated pass (anti-gaming rule 6 — never label a property you
    did not verify).
  - The required outcome, in strict order:
    1. **Find a versioned, integrity-preserving source.** A pinned release asset with a published
       checksum, or the installer's own version flag if it has one. This satisfies both.
    2. **If none exists, the agent FAILS AC-8** and is recorded with a fourth status —
       `UNPINNABLE (<installer>, verifies <mechanism>, offers no version selector)`. It is not
       `PASSED`, not `held`, and not quietly excluded. It appears in the update report as a known
       unpinnable surface with its integrity mechanism named.
    3. **Phase A ships anyway.** Blocking all five agents on the worst one would leave codex —
       which is trivially pinnable and unambiguously broken — unpinned for longer. Partial
       convergence with an honest gap beats a stalled phase.
  - Reproducibility and integrity are different properties. An `UNPINNABLE` agent has integrity and
    lacks reproducibility, and the report must say exactly that rather than averaging them into one
    green tick.
- **AC-9 — the lint reaches agents, and can see ABSENT as well as FLOATING.** Runs over
  `catalog/base/Dockerfile.harnessed-*`; rejects the existing floating patterns **and** unversioned
  acquisition (bare `mise use -g <backend>:<pkg>` with no `@`; piped installer with no version arg)
  — **unless** that agent declares `unpinnable:` with a reason (see the three-outcome table above).
  A test asserts the declaration is what suppresses the error, so an undeclared unpinned agent still
  fails.
  _Test_: unit tests feeding it each of the three real pre-migration bodies — each must raise. A lint
  that passes on today's `catalog/base/` is not fixed.
- **AC-10 — `harnessed update` resolves agent pins**, or they are `hold:`-marked with a reason.
  **Owned by Phase A scenario A7** (added in review of PR #331 — AC-10 previously had no scenario
  implementing it, so it would have passed review as a criterion nobody built). Concretely:
  Note A7 opens with a **schema prerequisite**: `build_args` has no slot for a `hold:` reason today.
  `update.py` gains an agent-manifest source beside its recipe sources — read `catalog/agents/*/agent.yaml`,
  take each `build_args` entry whose Dockerfile `ARG` it feeds, resolve it through the SAME backend
  machinery as `tools:` (the mise spec in `Dockerfile.harnessed-omp` is `github:can1357/oh-my-pi@…`,
  so `_github_releases` already applies), and honour a `hold:` reason. Tests: one resolved agent pin
  offered for bump, one held agent pin listed informationally and never offered, and one
  `UNPINNABLE` agent (per AC-8) reported as such rather than as unresolved.
- **AC-11 — no free-text copy of a pin.** No `description:` or comment restates a version
  `build_args` owns. (The live omp `"pinned v16"` vs `17.2.11` drift is the motivating case.)

### Negative constraints (must NOT change)

- **NC-1** — `catalog/` stays free of anything host-local; no absolute paths in the schema change.
- **NC-2** — no pin becomes floating. `@latest`, `main`, `master`, `HEAD` stay rejected, including in
  `install.refs:`.
- **NC-3** — recipes stay harness-independent: no `harnesses:` field (context-mode's `${HARNESS}`
  branch survives verbatim).
- **NC-4** — credentials referenced, never replicated.
- **NC-5** — `recipe.schema.json` stays backward compatible: a recipe with no `install.refs:`
  validates unchanged, and `install.cache:` alone stays valid. No new required field. Where `refs:`
  IS present, a hand-written `cache:` is rejected as a conflict — two sources for one key is the
  defect being removed, not a fallback to preserve.
- **NC-6** — baseline test count must not drop. Re-measure before starting (per #250 the suite
  currently reports `2120 passed, 22 skipped`).
- **NC-7** — tokensave's supply-chain posture must not regress. It verifies a **sha256 per arch**
  today. `ubi:` must offer equal or better integrity or the migration is refused and the Dockerfile
  stays.
- **NC-8** — **rtk** and **omp** are the reference implementations and do not change mechanically.
  (omp's stale `description:` prose is in scope; its `build_args`/`ARG` arrangement is not.)
- **NC-9** — antigravity's sha512 manifest verification, and claude's official installer integrity,
  must not regress. If pinning means bypassing a verifying installer, **refuse the pin and hold it**
  — reproducibility must not be bought with integrity.
- **NC-10** — `agent.schema.json` stays backward compatible (`build_args` already exists).

### Scenarios

**Phase A — agents (#330; runs FIRST per D6).**

**Intra-phase order is NOT the list order** (raised in review of PR #331, third pass). A7 changes
`agent.schema.json` and the update path, and A2–A4 need the `{value, hold}` form and the `spec:`
field it adds. Executing top-to-bottom would write pins into a schema that cannot hold them. The
dependency is:

```text
A7  (schema + update.py: hold:, spec:, UNPINNABLE)   <- FIRST, blocks A2-A4
A6  (lint)                                            <- independent, any time
A1  (opencode relocation)                             <- independent of A7 (scalar form suffices)
A5  (omp prose + land/revert the pending bump)        <- independent
     |
     +-- then A2 (codex), A3 (claude), A4 (antigravity)
```

A1 is listed first below because it is the simplest illustration of the target shape, not because it
runs first. Only A2–A4 are blocked, and they are blocked on A7 alone.


- A1. `opencode`: move `OPENCODE_VERSION=1.17.9` into `agent.yaml build_args`; Dockerfile `ARG` loses
  its default. _Pure relocation — no RED test; use the byte-identity + mutation substitute._
- A2. `codex`: `npm:@openai/codex` → `@<pinned>` from `build_args`. **Not a relocation** — the image
  is currently whatever `@latest` was at its last build. Record which version and why (S7).
- A3. `claude`: pin `claude.ai/install.sh` (S5), under NC-9.
- A4. `antigravity`: same (S6), under NC-9.
- A5. `omp`: delete `"pinned v16"` prose (AC-11); land or revert the pending 17.2.11 bump — do not
  leave the tree split.
- A6. Extend the lint (AC-9). This is the guard that stops A1–A4 regressing.
- A7. **Teach `harnessed update` to see agents** (AC-10). Without A7, A1–A5 move pins into
  `agent.yaml` where `update` still cannot read them — the migration would be cosmetic and AC-10
  would be met on paper only.

  **Blocking prerequisite found while specifying this** (review of PR #331, second pass):
  **`agent.yaml` has nowhere to put a `hold:` reason.** `agent.schema.json` types `build_args` as
  `additionalProperties: {type: [string, number]}` — a bare scalar, `OMP_VERSION: "17.2.11"`. There
  is no slot for a hold, and AC-10 plus the AC-8 `UNPINNABLE` status both require one (claude and
  antigravity are the likely holders, per NC-9). So A7 begins with a schema change, and A7 must
  therefore land BEFORE A2–A4, not after them.

  **How does `OPENCODE_VERSION` tell the resolver what to query?** (Raised in review of PR #331,
  third pass — the first draft said "take each `build_args` entry that feeds a Dockerfile `ARG`",
  which does not identify an upstream.) Measured across all five agent Dockerfiles:

  | Agent | What the Dockerfile exposes | Resolvable by extraction? |
  | --- | --- | --- |
  | omp | `mise use -g "github:can1357/oh-my-pi@${OMP_VERSION}"` | yes — a mise spec |
  | codex | `mise use -g npm:@openai/codex` | yes, after A2 adds the version |
  | opencode | `curl -fsSL https://opencode.ai/install \| bash -s -- --version "${OPENCODE_VERSION}"` | **no** — the URL does not name `sst/opencode` |
  | claude | `curl -fsSL https://claude.ai/install.sh \| bash` | **no** — no upstream identifier at all |
  | antigravity | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` | **no** |

  **So extraction is rejected: it works for 2 of 5 and cannot work for the rest.** A "precise, tested
  Dockerfile extraction rule" would be a shell parser that is correct for the two easy cases and
  silently blind for the three that matter — and `update.py`'s module docstring already refuses
  exactly this (*"install.sh bodies, Dockerfiles, and install.cache are not that. They are shell and
  text"*). Writing a Dockerfile parser to satisfy this epic would contradict the principle the epic
  is built on.

  **Declare instead.** The `build_args` mapping form carries an optional `spec:` — a mise spec in the
  same vocabulary `tools:` already uses. The resolver never reads a Dockerfile; it reads the manifest,
  exactly as it does for recipes:

  ```yaml
  build_args:
    OMP_VERSION: { value: "17.2.11", spec: "github:can1357/oh-my-pi" }
    OPENCODE_VERSION: { value: "1.17.9", spec: "github:sst/opencode" }
    CODEX_VERSION: { value: "0.0.0", spec: "npm:@openai/codex" }
    CLAUDE_VERSION: { unpinnable: "official installer verifies its own download; offers no version selector" }
  ```

  Per-source-type coverage for A1–A5:

  | Scenario | Agent | `spec:` | Outcome |
  | --- | --- | --- | --- |
  | A1 | opencode | `github:sst/opencode` | **RESOLVED** — installer takes `--version`, so value and spec agree |
  | A2 | codex | `npm:@openai/codex` | **RESOLVED** — npm registry; value chosen by S7 |
  | A3 | claude | *(none)* | **UNPINNABLE** unless S5 finds a version selector |
  | A4 | antigravity | *(none)* | **UNPINNABLE** unless S6 finds one, under NC-9 |
  | A5 | omp | `github:can1357/oh-my-pi` | **RESOLVED** — already the reference shape |

  A `spec:` is a *resolver hint*, never a second installer. It names where the version comes from; the
  Dockerfile still performs the install. That separation is the same one `install.refs` makes for
  Family B (declare the pin, keep the fetch), and it is why neither needs a DSL.

  1. **`agent.schema.json`** — a `build_args` value becomes `oneOf`: the existing scalar, **or** a
     mapping `{value, spec?, hold?, unpinnable?}`, mirroring what `tools:` already does with
     `{spec, hold}`. `unpinnable` is mutually exclusive with `value`/`spec` — an agent is either
     pinned or it is not, and a manifest that claims both is a schema error.
     Reusing that shape rather than inventing a second one is the point: one hold concept, one
     reader, one set of semantics. Backward compatible per NC-10 — every existing scalar still
     validates, and no field becomes required.
  2. **`src/harnessed/schema.py`** — parse and validate the new form; a `hold` must be a non-empty
     reason string, and (as with `tools:`) a hold does **not** license an unpinned value.
  3. **`src/harnessed/update.py`** — an agent-manifest pin source beside the recipe sources: walk
     `catalog/agents/*/agent.yaml`, take each `build_args` entry that feeds a Dockerfile `ARG`,
     and resolve it through the SAME backend machinery as `tools:`. `Dockerfile.harnessed-omp`
     already carries a mise spec (`github:can1357/oh-my-pi@${OMP_VERSION}`), so `_github_releases`
     applies unchanged — the work is discovery and reporting, not a new resolver.
  4. **`src/harnessed/emit.py` / launcher** — confirm the `--build-arg` path reads `.value` from
     the mapping form. **This is the regression risk of the whole scenario**: a reader that gets a
     dict where it expected a string either crashes the build or, worse, stringifies the dict into
     the `ARG`. A test must pin the mapping form end-to-end to `--build-arg`, not just through the
     schema.

  **Tests** (each named because "add tests" is how a criterion goes unbuilt):
  - a scalar `build_args` pin resolves and is offered for bump;
  - a `{value, hold}` pin is listed informationally and **never** offered;
  - a `hold` with an empty/missing reason is a schema error;
  - an `UNPINNABLE` agent (AC-8) reports under that status, not as unresolved;
  - the mapping form reaches `podman build` as `--build-arg NAME=<value>`, with no dict leakage;
  - every existing scalar-only `agent.yaml` in `catalog/agents/` still validates (NC-10).

**Phase 1 — literal deletions** (no behaviour change): ccstatusline (closes #323), serena,
context-mode (fed from `tools:`).

**Phase 2 — Family A onto `tools:`**: codebase-memory-mcp; tokensave (after S1, under NC-7);
solidspec (after S2 — Dockerfile keeps only its `apt-get` layer); gsd-core (after S3).

**Phase 3 — Family B onto `install.refs:`**: caveman, superpowers, hyperpowers, gstack,
mikes-universal-setup. Acceptance is per **ref**, not per recipe: all **seven** declared refs end
with a resolver outcome or an explicit `hold:` naming its class, and mikes-universal-setup's three
are asserted individually. The Class C decision (S8) is made in this phase, in writing, not left to
the implementer. For each: same files land in `$HARNESSED_CONFIG_DIR`, the derived
`install.cache` key still hits on a second launch, and `harnessed update` lists the pin as resolvable
or held (S8 decides which).

**Phase 4 — tests for all** (AC-6a now, AC-6b gated on #250).

### Spikes (do these first; they change §3)

- **S1** — can mise resolve `ubi:aovestdipaperino/tokensave@7.0.2` for x86_64 _and_ aarch64, and what
  integrity does it give (NC-7)?
- **S2** — does mise's `cargo:` backend accept a git URL + tag? If not, solidspec has no `tools:`
  target.
- **S3** — does `@opengsd/gsd-core@1.6.1` ship a `bin`, and does invoking it behave like `pnpm dlx`?
- ~~**S4**~~ — **ANSWERED 2026-08-08** (D1a). `emit.install_env` (`src/harnessed/emit.py:727`) is a
  flat `dict[str, str]` applied last, winning over the inherited env and the recipe's own `env:`
  (`test_install_env_precedence`, both modes). Derived `HARNESSED_REF_*`/`HARNESSED_REPO_*` keys fit
  without changing its shape. Its "identical KEYS in host and container mode" docstring invariant
  still holds (ref keys vary by recipe, never by mode) and is **already covered** by an ungated,
  mode-parametrized test — `test_live_verification_debt.py::TestHostHomeShim::test_the_install_env_exports_both_vars_in_both_modes`.
- **S5** — does `claude.ai/install.sh` accept a version argument (opencode's does:
  `bash -s -- --version "$VER"`)? If not, is there a pinnable alternative preserving integrity (NC-9)?
- **S6** — same for `antigravity.google/cli/install.sh`, whose sha512 verification must survive.
- **S7** — what is the _currently resolved_ version of `npm:@openai/codex` in the built image
  (`mise ls` inside it), so A2 pins what already ships rather than silently upgrading users?
- **S8** _(from D1; partially ANSWERED 2026-08-09, see §1 Family B)_ — resolvability is measured for
  all seven refs: **2 Class A** (tag-pinned, resolvable), **3 Class B** (no releases or tags —
  structurally unresolvable), **2 Class C** (releases exist but the pin is a SHA, so candidates
  cannot be ordered against it). What REMAINS open in S8 is the Class C decision: migrate those two
  pins to tags, or hold them with the not-orderable reason. Recommend holding — see §1 Family B. Determines whether Phase 3 delivers 4 auto-bumpable pins or 2.
- **S9** _(from D3, gates Phase 4)_ — can a **host** assembly complete in CI (mise present, network,
  no podman)?

---

## 4. Setup plan

- **Isolation**: `worktree` per `.old-coder.toml` and CLAUDE.md. One worktree per phase. **This spec
  phase wrote only into the gitignored artifact dir in `main/`; no tracked file was touched.**
- **Commits**: `commit = "allow"`, signed (`git commit -S`) per `.claude/rules/signed-commits`.
- **New dependencies**: **none proposed.** If a spike shows otherwise, it returns here for approval.
- **Files touched — Phase A/A7** (agents; lands before Phase 0 per D6):
  - `schemas/agent.schema.json` _(`build_args` value gains `{value, spec?, hold?, unpinnable?}`)_
  - `src/harnessed/schema.py` _(parse/validate the mapping form)_
  - `src/harnessed/update.py` _(agent-manifest pin source; three-outcome reporting)_
  - `src/harnessed/emit.py` _(`--build-arg` must read `.value`, not the mapping)_
  - `catalog/base/Dockerfile.harnessed-*` _(A1–A4: `ARG`s lose their defaults)_
  - `catalog/agents/*/agent.yaml` _(A1–A5: pins move here)_
  - `tests/test_agent_pins.py` _(new — the six A7 tests)_
- **Files touched — Phase 0** (recipes; later phases add `tests/*.sh` under existing recipe dirs):
  - `schemas/recipe.schema.json` _(new `install.refs:`; `cache:` becomes derived)_
  - `src/harnessed/schema.py`
  - `src/harnessed/update.py`
  - `src/harnessed/emit.py`
  - `src/harnessed/capability.py` _(host test path, AC-6a)_
  - `tests/test_recipe_pin_hygiene.py` _(new — AC-1, AC-4)_
- **Tracker**: `tracker = "allow"`; roll-up to #329.

---

## 5. Gauntlet tooling audit (read from the manifests, not PATH)

| Layer                       | Declared?                                                                                             | Command                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Full test suite             | yes — `.old-coder.toml [commands].test`                                                               | `tools/run-tests.sh`                                         |
| Lint / format               | yes — `ruff`, `pyproject.toml [tool.ruff]`                                                            | `mise exec -- uv run --extra dev ruff check src tests tools` |
| Static types                | yes — `pyright` pinned in `mise.toml` (`npm:pyright = "1.1.411"`)                                     | `mise exec -- pyright`                                       |
| Coverage (changed lines)    | **verify at Phase 0** (`pytest-cov`?)                                                                 | TBD                                                          |
| Mutation testing            | **verify at Phase 0**. `tools/mutants_capmatrix.py` is a project-specific harness, not a general tool | TBD                                                          |
| Property-based tests        | **verify** (`hypothesis`?)                                                                            | TBD                                                          |
| Real execution              | **partially UNAVAILABLE by construction** — see blind spot                                            | `harnessed test`, `HARNESSED_PODMAN=1`                       |
| Suite health (random order) | **verify** (`pytest-randomly`?)                                                                       | TBD                                                          |
| Supply chain                | relevant: NC-7, NC-9; `install.refs:` changes where the fetch ref is declared                          | `pip-audit` if declared; manual capability diff otherwise    |
| Adversarial review          | required — Tier 3, **and** this touches code I did not write                                          | fresh subagent, security lens on the fetch/pin surface       |

**Baselines to re-measure before any edit** (`.old-coder.toml`'s values are stale by its own
admission): ruff 196, pyright 89 on clean `main` at `292ecee`. The bar is **zero NEW** findings,
never `exit 0`.

**Structural blind spot**: this project's suite runs **no `podman build` and no
`harnessed container-run`** (CLAUDE.md says so; #250 documents the 22 skipped tests). Every claim
about _what happens inside a built image_ — most of this epic — is verifiable only by a manual
`HARNESSED_PODMAN=1` run. That is the largest limit on the evidence this loop can produce, and it is
why AC-6a matters: it moves part of that surface into a layer that runs.

---

## 5b. Issue graph

The critique that prompted this: AC-3 is a **reporting** change in `update.py`, not a recipe change,
so finishing every recipe migration would still leave #261's second criterion unmet. And
`Related: #261` in prose is a mention, not a queryable relationship — `trackedIssues`/
`trackedInIssues` were both 0 and #261 had no parent.

**Chosen: option 2 — scope #261 down to its Class 3 reporting bug and make it a sub-issue of #329.**

- **Option 1** (fold it into #329, close #261 as superseded) makes a ~20-line `update.py` change with
  a pure unit test wait behind 22 recipe conversions and three spikes.
- **Option 3** (leave both open, just set `--parent`) leaves #261 claiming Classes 1 and 2, which
  #329 now owns — two issues asserting the same work.
- **Option 2** gives each piece one owner: the epic owns pin _migration_, the child owns pin
  _reporting_, and containment is queryable.

Consequences:

- **AC-3 is delegated to #261.** It remains an epic AC — an epic AC satisfied by a sub-issue is still
  satisfied.
- **Order matters**: #261 suppresses `install.cache` from the _report_ now; Phase 3's derived-cache
  change removes the hand-written _key_ later. Doing #261 first means Phase 3 carries no reporting
  fix as collateral.
- **#330 filed** for the agent work: #329's Ask was recipe-only, and three unpinned agents are a
  different failure mode (reproducibility / supply chain) from recipe drift. Phase A ships without
  the `install.refs:` schema change.

```text
#329  epic: converge recipes AND agents on the rtk pattern
 ├─ #261  (narrowed)  update.py: stop reporting install.cache keys as unresolved pins   → AC-3
 ├─ #330              agents: 3 unpinned CLIs + the lint that never runs on them        → AC-7..AC-11, Phase A
 └─ (recipe phases 0-4 tracked in the epic itself)
```

`#323` stays a peer, not a child: it is closed _as a side effect_ of Phase 1 scenario 1, and
re-parenting someone else's bug report to claim it is a worse signal than closing it with a commit
reference.

---

## 6. Issues this epic touches

**Children**: #261 (reporting, owns AC-3, ship first) · #330 (agents, owns AC-7..AC-11 / Phase A).

**Closed by the epic directly**: #323 (paired-literal drift; Phase 1).

**Blockers / decided alongside:**

- #250 — live-verification layer runs nowhere → gates AC-6b (D3, S9)
- #255 — first container build of any `install.cache` recipe fails → Phase 3 touches that code path

**Materially affected; re-read before the relevant phase:**

- #240 — skill-fetch bridge; supplies the `hold:` policy and rules out the vercel CLI (D1a)
- #235 — recipe-capability × backend matrix; `install.refs:` is a new capability row
- #252 — derived-image layer order; deleting the tokensave/solidspec Dockerfiles changes composition
- #243 — `mise.lock` advisory artifact; more `tools:` entries makes it more valuable
- #248 — base-image `extra-tools.default.txt` pins nothing (D5)
- #291 — `harnessed update` cannot resolve markdownlint-cli2
- #288 — `pin-check.yml` uses floating action tags
- #254 — the `:latest` URL-path exemption test asserts nothing; NC-2 depends on which is true
- #283 — shipped wrangler skill says `npm install -D wrangler@latest`
- #319 — `Recipe.root` defaults to `.`; the AC-1 lint walks `Recipe.root`

---

## 7. What this spec deliberately does NOT cover

- Rewriting `harnessed update` to parse shell or Dockerfiles (rejected, D1a).
- Migrating off the hand-rolled tarball fetch to the vercel `skills` CLI (#240; blocked upstream).
- Fixing #250 itself — this spec depends on it and routes around it (AC-6a), it does not solve it.
- Any mechanical change to `rtk` or `omp` (NC-8).
- `catalog/base/extra-tools.default.txt` (D5 — tracked as #248).
- The `catalog-local/` user overlay, unless a spike shows the schema change breaks it.
