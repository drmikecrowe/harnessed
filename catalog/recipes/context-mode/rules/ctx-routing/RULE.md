# Routing Large Output Through ctx_*

Every harness reaches context-mode's MCP tools directly. They need no hook, no bridge, and no
harness-native plugin, so this routing holds in every stack that ships the recipe.

## Searching: fire rg through ctx_batch_execute

**Before you run a shell search whose output you cannot bound, run it through `ctx_batch_execute`
instead.** It runs the command, indexes the output, and returns only the windows your `queries` match.
The raw match list never enters the conversation.

```text
ctx_batch_execute(
  commands: [{label: "callers", command: "rg -n load_recipe src tests"}],
  queries: ["load_recipe in schema", "load_recipe in tests"],
  cwd: "<repo root>"
)
```

This is the concrete form of "search before you read". It is also the step you will forget first. A
generic reminder that some reducer exists does not fire mid-task, when you are reaching for `rg`.

A bounded `rg -l` or `rg -c` stays fine, and cheaper, for a small answer. If you would page a long
match list, route it.

## The other tools

- **`ctx_search`** — interrogate what earlier calls already indexed, without re-running anything.
- **`ctx_fetch_and_index`** — a URL you will consult more than once.
- **`ctx_execute` / `ctx_execute_file`** — derive an answer in code, so raw bytes never enter the
  conversation. Only what you print comes back. Best for file-crunching.

**Always pass `cwd`.** Omit it and the sandbox starts in a missing directory. The failure surfaces as
`spawn bash ENOENT` or `spawn bun ENOENT`. That names the interpreter, so it reads like a broken
runtime install. The interpreter is fine. The working directory is not.

## The failure mode that costs more than it saves

`queries` decides what re-enters context, and it cuts BOTH ways.

Too **broad**: overlapping queries match every section and echo it **in full, once per query**. Two
loose queries over one command cost more than the plain command.

Too **narrow**: a command runs, indexes, and matches nothing. It never appears in the output, so you
re-run it separately. The batch succeeded and still cost you the round trip.

Write several precise queries. Between them they must cover every command you batched.

Use the labels as a checklist. Every command needs a `label` already. If you cannot name a query that
surfaces a given label, drop that command from the batch.

`query_scope` defaults to `batch`: this call's output only. Pass `global` only when you also want the
persistent index.

## Do not route everything

A single short command with no follow-up question does not need indexing. The round trip, the index
write, and the section headers all cost you before you read a line.

Bound the command first. The cheapest search is the one that never produced surplus output.
