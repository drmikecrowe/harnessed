# Gortex: Linked Worktrees

Recovery steps the Gortex instructions do not give. They apply to v0.64.x. Upstream tracks each gap: zzet/gortex#931 to #937.

## Stale session binding

- When `edit_file` fails with `checkout mutation view is stale`, ask the user to start a new session. Do not retry it.
- When a covered worktree returns `repository not tracked`, ask the user to start a new session.
- Do not call `reconcile_checkouts` to clear either error. It reports `reconciled` and the refusal stays.
- When the hook blocks native Read and Gortex refuses writes, stop. Report that no edit path is left.

## Trust explain_view

- When orientation says "awaiting automatic discovery", call `explain_view` on the cwd.
- When `explain_view` shows `automatic`, an active route, and `ready: true`, proceed with Gortex tools.
- Before you diagnose a worktree, compare `primary_graph_id` with the trunk worktree's graph.
- When the primary is a feature-branch corpus, report it. Give the user the `set-primary` preview command.

## Writes

- After a write, the route rebuilds. Expect a `view_building ... not fully routed yet` refusal then.
- Retry a `view_building` refusal with the same `mutation_id`. Never resend it as a new edit.

## Admin commands

- When a CLI call fails with `exceeded its ... deadline and was abandoned`, check the state before you run it again.
- Check state with `gortex repos explain-view <path>` and `gortex repos families`.
- Treat `not a ready dedicated checkout` on `untrack` as success. The checkout is already automatic.
- From an untracked cwd, pass `--index <trunk worktree>` to every `gortex repos` command.

## Hook false positives

- When the hook blocks `rg` on a file that is not indexed source, process the file with `ctx_execute`.

## New-worktree scripts

When you write a script or task that creates a worktree, follow this pattern. `$dest` is the new worktree and `$trunk` is the trunk worktree.

1. Create the worktree where the repository's conventions put worktrees.
2. Run `gortex repos reconcile "$dest" --index "$trunk" || true`, guarded by `command -v gortex`.
3. Print `gortex repos explain-view "$dest" --index "$trunk"`, so the user sees the mode and the route.
4. Tell the user to start a new agent session in the new worktree.

- Never put `gortex track` in a worktree script. It creates a duplicate dedicated corpus.
- Never put `untrack`, `set-primary`, `forget`, `--confirm`, or a daemon restart in a script.
