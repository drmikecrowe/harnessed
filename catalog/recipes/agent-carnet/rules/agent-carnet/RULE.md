## Persistent memory — use agent-carnet, not auto-memory

The **agent-carnet** skill is the single source of truth for all cross-session
memory: decisions, handoffs, in-progress state, hard-won fixes, rejected
alternatives, and anything a future session would otherwise re-derive.

- **Write only to carnet.** When you would normally save an auto-memory, save a
  carnet note instead. Follow the skill's own conventions for category/slug.
- **Do not write to the auto-memory system.** Never create or edit `MEMORY.md`
  or files under the `memory/` directory, and never add to its index. Treat that
  system as read-only legacy.
- **Injected auto-memories are read-only.** The harness may still surface recalled
  `MEMORY.md`/`memory/*.md` entries in `<system-reminder>` blocks — you may read
  them for context, but do not update them in place. If one is still relevant,
  migrate it into carnet and rely on the carnet copy thereafter.
- **When in doubt, prefer a brief carnet note** over losing context — unused
  carnet notes expire on their own.
