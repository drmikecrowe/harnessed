# House style for injected content

Applies to every `RULE.md` and `SKILL.md` under a recipe, and to the `description:` field of each
skill. These files are read by a model, not by a person, and the same bytes must work on Claude,
opencode, codex, and antigravity. Write them as procedures, not as prose.

Check your work with `harnessed-tools lint-prose <path>...`. The thresholds below are the ones it
enforces.

## The standard

This is [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) applied to agent
instructions. STE was written so a maintenance procedure survives a reader who is tired, rushed, or
not a native speaker. That is the same failure mode a model has, and it is the reason this standard
is harness-agnostic: it constrains the writing, not the tokenizer. A trick tuned to one model's
attention is not portable. A short imperative sentence is.

| Rule | Do | Not |
| --- | --- | --- |
| **Imperative** | `Run the script.` | `You should run the script.` |
| **One clause per instruction** | `Commit signed. Then push.` | `Commit signed and then push, making sure that…` |
| **Condition before command** | `If the build fails, revert.` | `Revert if the build fails.` |
| **Active voice** | The lint rejects `npx`. | `npx` is rejected by the lint. |
| **Hard modals** | `must`, `never`, `always`, `do not` | `should probably`, `consider`, `try to`, `make sure to`, `ideally` |
| **Second person or none** | Author under `catalog/`. | We author under `catalog/`. |
| **One word, one meaning** | pick `recipe` and keep it | `recipe` / `bundle` / `package` for one thing |

Limits, per sentence:

| Kind | Max words |
| --- | --- |
| Instruction or procedure step | 20 |
| Explanation or `description:` | 25 |

## Show the pair, do not explain the rule

A wrong/right pair is shorter than the paragraph that describes it, and it is unambiguous. Prefer it.

```bash
# Wrong
npx some-tool

# Right
pnpm dlx some-tool
```

## Budget by where the bytes land

The three surfaces do not cost the same. Spend accordingly.

| Surface | Loaded | Budget |
| --- | --- | --- |
| Skill `description:` | **always**, every session | 1–2 sentences. Name the triggers. |
| `RULE.md` body | **always**, every session | Keep it under ~400 tokens. |
| `SKILL.md` body | only when the skill fires | Room to work, still imperative. |
| Reference file next to `SKILL.md` | only when the body links to it | Put the long tables and field lists here. |

A skill body that grows past a screen belongs in a reference file with a one-line pointer. That is
what `recipe-fields.md`, `stack-fields.md`, and `services.md` are for. Length in a reference file is
free. Length in a `description:` is paid every session, by every stack that ships the recipe.

## Write `description:` as a trigger, not a summary

The `description:` is routing. The model reads it to decide whether to open the skill, so it must
name the situations that should open it — and nothing else.

```yaml
# Wrong — a summary of the skill's contents, in one 60-word sentence
description: A comprehensive skill for working with the Cloudflare Workers CLI which can be used
  for deploying, developing and managing Workers, KV, R2, D1, Vectorize, Hyperdrive, Workers AI,
  Containers, Queues, Workflows, Pipelines and Secrets Store, and which should be loaded before
  running any wrangler commands to ensure correct syntax and best practices.

# Right — what it covers, then when to open it
description: Cloudflare Workers CLI — deploy and manage Workers, KV, R2, D1, Queues, and Secrets.
  Use before running any `wrangler` command.
```

## What the lint checks

`harnessed-tools lint-prose` reports two severities. Errors fail the command; warnings do not.

| Check | Severity |
| --- | --- |
| Sentence over 25 words | error |
| Hedge phrase (`consider`, `try to`, `make sure`, `feel free`, `ideally`, …) | error |
| First person (`we`, `our`, `let's`) | error |
| `description:` over 40 words | error |
| Average sentence over 15 words | warning |
| Passive voice | warning |
| More soft modals (`can`, `might`, `should`) than hard directives | warning |

Code fences, tables, headings, and list markers are excluded from every count. Prose is measured;
syntax is not.

Run it on what you wrote before you open the PR:

```bash
harnessed-tools lint-prose catalog/recipes/<name>
```
