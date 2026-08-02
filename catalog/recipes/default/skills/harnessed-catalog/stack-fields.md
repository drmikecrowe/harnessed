# `stack.yaml` fields

Stack manifests are **strict**: any key outside this set is rejected with a did-you-mean suggestion
(`KNOWN_STACK_FIELDS` in `src/harnessed/schema.py`, the authority):

```text
name extends recipes services harnesses permissions instructions
forward_git_credentials ssh_keys forward_aws_sso state hatago
```

Strictness is deliberate. Parsing used to be tolerant, and an `extends:` written before the feature
existed inherited nothing for months while looking accepted.

`hatago:` is in that set but is **not** a usable field: it is kept only so a manifest still carrying
the removed override is rejected with a message naming its replacement
(`_reject_removed_hatago_override`) instead of dying in the generic unknown-field path. Never author
it, and it is not inheritable.

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/drmikecrowe/harnessed/main/schemas/stack.schema.json
name: my-stack              # required; must equal the directory name; may NOT be a harness name
recipes: [a, b, c]          # composed in order
services: []                # shared sidecars auto-started at launch
harnesses: [claude]         # build-time convenience only — see below
permissions: auto           # prompt | auto | yolo | acceptEdits | bypassPermissions | default |
                            #   dontAsk | plan
instructions: |             # identity text → .claude/CLAUDE.md (omp: APPEND_SYSTEM.md; codex: AGENTS.md)
  You are a review agent.
state:
  persist: true             # default; `--fresh` overrides at runtime
  session_state: host       # host (default) | volume
forward_git_credentials: false   # opt-in: gh token + opted-in private SSH keys
ssh_keys: []                     # private key basenames under ~/.ssh — overlay stacks only
forward_aws_sso: false           # opt-in: AWS creds via the aws-sso ECS server
extends: base-stack
```

There is no `harness:` field — it is rejected with a pointer to `harnesses:`. The harness is a
run-time argument (`harnessed build <stack> <harness>`, `harnessed container-run <harness> --stack
<name>`). `harnesses:` only tells a bare `harnessed build <stack>` which pairs to build, and lets a
bare `harnessed build` include them in its staleness sweep.

## Fields worth a second look

**`session_state: volume` isolates history and is usually wrong.** harnessed containerizes
*configuration*, not *storage* — conversations, usage, and stats persist to the host so switching
stacks on one project never fragments your history. `host` (the default) is what delivers that.
`volume` is a real escape hatch for a deliberately throwaway stack, and easy to copy in by accident.

**`instructions:` is stack identity**, a single block emitted at assemble time. It is not
concatenated with recipe `rules:`, which fan into `.claude/rules/` separately.

**`ssh_keys:` is honored only from the user overlay.** A repo-catalog stack (or a repo base a child
extends) may list key names, but the launcher drops them — the key owner, not a third-party stack
author, must consent to mounting a private key. Declare it in the overlay stack you actually launch.

## `extends:` — the answer for several stacks that share a base

```yaml
# base
name: house
recipes: [ccstatusline, mikes-universal-setup]
permissions: auto
forward_git_credentials: true

# child
name: house-review
extends: house
recipes: [repowise]        # → ccstatusline, mikes-universal-setup, repowise
permissions: yolo          # → yolo (child wins)
```

| Field | Rule |
| --- | --- |
| `recipes`, `services`, `harnesses`, `ssh_keys` | **union**: base's entries in base order, then the child's, de-duped |
| `permissions`, `instructions`, `state` | child wins **whole**, when set; otherwise inherited. `state` replaces — no per-key merge. |
| `forward_git_credentials`, `forward_aws_sso` | inherited; a child may set either back to `false` |
| `name` | never inherited; must match the directory name |

- `extends:` takes a **single** name — no multiple inheritance, no diamonds. Chains are allowed and
  merged base-first; cycles are a hard error naming the chain.
- The parent resolves in the child's **own catalog root first**, then the normal search (overlay,
  then repo). That is what lets an overlay stack extend a base the repo ships.
- **There is no way to remove** a recipe or service the base declares. If you need base-minus-one,
  the base is wrong — split it.
- Editing a base marks every child stale: a child's staleness inputs include every `stack.yaml` in
  its chain plus every recipe dir in the merged list.

## Composing three stacks that differ

Put everything shared in one base and let each child state only its difference. A child whose entire
manifest is `name`, `extends`, and one `recipes:` line is the goal — that is the shape that does not
rot when you change the house recipe list.

Before writing three manifests, check whether you need any: `harnessed container-run <harness>
--recipe a --recipe b` mints a content-named stack under the generated catalog root, so the same
recipe set in five repos is one stack, one image, one pair of volumes. Author a stack when you want
a stable name, `instructions:`, credential forwarding, or `ssh_keys:` — a generated stack cannot use
`ssh_keys:` at all (it is shared across repos, so it cannot express "the key for *this* repo").

## Lifecycle

```bash
harnessed-tools assemble <stack> <harness> --build-dir "$(mktemp -d)"   # fast gate, no podman
harnessed build <stack> <harness>                                        # real build
harnessed test  <stack> <harness>                                        # capability oracle
harnessed list                                                           # authored stacks + instances
harnessed stop|rm <stack>                                                # across all projects
harnessed install <stack>                                                # ~/.local/bin/<stack> shim
```

`harnessed new <name> --recipes a,b` scaffolds a manifest — into the **repo** catalog, refusing to
overwrite and refusing a harness name. Overlay stacks are written by hand.
