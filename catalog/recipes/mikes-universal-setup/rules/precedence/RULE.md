# Precedence

When two instructions disagree, resolve in this order. Higher wins; lower still applies wherever it
does not conflict.

1. **User instruction in this conversation** — including a correction that reverses earlier guidance.
2. **Harness tool policy** — the tool inventory and routing rules the harness injects. It knows which
   tools exist and which shell commands are blocked. These rules do not.
3. **Project docs** — AGENTS.md, CLAUDE.md, README, and whatever the repo declares about itself.
4. **These always-on rules.**
5. **Skills** — and only when the task actually matches the skill's stated trigger.
6. **Memory and learned lessons** — heuristics and process context, never proof of current state.

## Tool disagreements

A rule that names a specific binary is naming an *example*, not a mandate. When a rule and the
harness disagree about which tool to reach for, the harness wins on the mechanism and the rule still
governs the intent. "Search before reading whole files" survives intact even where the binary the
rule happens to name is absent, blocked, or superseded by a built-in tool.

So: obey the harness on *which* tool, obey the rule on *why*. Neither one gets to cancel the other.

## Stale-by-design sources

An index, graph, or cache is a derived view — fast, ranked, and possibly behind the working tree.
Prefer an authoritative resolver for single-symbol truth, use the derived view for breadth, ranking,
and multi-hop questions, and re-derive after substantial edits. Memory has the same shape: it earns
confidence only after repository verification.

## When precedence does not settle it

If two sources of equal rank genuinely conflict, say so and ask. Silently picking one and proceeding
hides the conflict from the only person who can fix it.
