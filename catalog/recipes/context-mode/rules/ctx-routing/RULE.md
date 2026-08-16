# Routing Large Output Through ctx_*

context-mode's MCP tools are reachable directly in every harness. They need no hook, no bridge, and
no harness-native plugin, so this routing holds wherever the recipe is installed.

## Searching: fire rg through ctx_batch_execute

**Before you run a search in the shell whose output you cannot bound, run it through
`ctx_batch_execute` instead.** It executes the command, indexes the output, and returns only the
windows matching your `queries`, so the raw match list never enters the conversation.

```text
ctx_batch_execute(
  commands: [{label: "callers", command: "rg -n load_recipe src tests"}],
  queries: ["load_recipe in schema", "load_recipe in tests"],
  cwd: "<repo root>"
)
```

This is the concrete form of "search before you read", and it is the step most easily forgotten: a
generic reminder that some reducer exists will not fire when you are mid-task and reaching for `rg`.
A bounded `rg -l` or `rg -c` in the shell is still fine and cheaper for a small answer. The moment you
would page a long match list, route it.

## The other tools

- **`ctx_search`** — interrogate what earlier calls already indexed, without re-running anything.
- **`ctx_fetch_and_index`** — a URL you will consult more than once.
- **`ctx_execute` / `ctx_execute_file`** — derive an answer in code so raw bytes never enter the
  conversation; only what you print comes back. Best for file-crunching.

**Always pass `cwd`.** Omit it and the sandbox starts in a directory that may not exist, which
surfaces as `spawn bash ENOENT` or `spawn bun ENOENT`. That names the interpreter, so it reads like a
broken runtime install and sends you hunting the wrong bug. The interpreter is fine; the working
directory is not.

## The failure mode that costs more than it saves

`queries` decides what re-enters context, and it cuts BOTH ways.

Too **broad**: overlapping queries match every section and echo them **in full, once per query**, so
two loose queries over one command can cost more than running it plainly.

Too **narrow**: a command runs and is indexed but matches nothing, so it never appears in the output
at all and you re-run it separately. The batch succeeded and still cost you the round trip.

Aim for several precise queries that between them cover every command you batched. `label` is
required on each command, so use the labels as your checklist: if you cannot name a query that would
surface a given label, that command had no reason to be in the batch.

`query_scope` defaults to `batch`, meaning this call's output only. Reach for `global` deliberately,
when you want the persistent index searched as well.

## Do not route everything

A single short command with no follow-up question does not need indexing. The round trip, the index
write, and the returned section headers are overhead paid before you read a line. Bound the command
first: the cheapest search is the one that never produced surplus output.
