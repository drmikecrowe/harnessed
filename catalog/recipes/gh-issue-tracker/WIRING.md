# AGENTS.md stanza

Paste this into the repo's `AGENTS.md` (or `CLAUDE.md`). This is the only
always-on piece — keep it this short. Everything else loads on demand.

```markdown
## Work tracking

This repo tracks durable work in GitHub Issues, not in a local tracker.
Run `.gh-issue-tracker/prime.sh` at the start of a session for the working rules
and the current ready queue. Use TodoWrite for within-session steps only.
```

That's it. Four lines. Compare to `beans prime`, which injects its full
instruction block plus the entire GraphQL schema every session.

---

## Wiring it per harness

Pick the layers that apply. They compose — the AGENTS.md stanza is the floor
that works everywhere, and the rest are optimizations.

### Claude Code — SessionStart hook

`.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": ".gh-issue-tracker/prime.sh" }] }
    ]
  }
}
```

`prime.sh` exits silently when gh is missing, unauthenticated, or the repo
isn't resolvable, so this is safe to leave wired in repos that don't use it.

### Claude Code — the skill (preferred)

Install `gh-issue-tracker/` as a skill instead and you get progressive disclosure:
only the ~500-character description sits in context, and the body loads when
the model recognizes a backlog task. That's the token-efficient path, and it's
the one advantage skills have over prime-style injection.

Use both if you want: the skill for depth, the hook for live state. They
don't conflict — the hook reports what's ready now, which a skill can't.

### OpenCode / omp / anything else

AGENTS.md stanza only. Optionally run `prime.sh` manually at session start,
or wire it into whatever session-open mechanism the harness offers.

### harnessed recipes

Bake `prime.sh` into the image and run it host-side at pod launch, writing the
output into the pod as a file. The agent then reads local state and never needs
`api.github.com` in the allowlist. Same mediation pattern as the secrets agent.

---

## Why it's built this way

**The rule lives in a file you own.** `beans prime` embeds its template with
`go:embed`; the PR making it configurable has been open since January. Here the
template is a bash heredoc you edit directly.

**No instruction-override language.** `beans prime` tells the agent to "ignore
all previous instructions" about TodoWrite. That phrasing is injection-shaped,
and the underlying rule is wrong anyway — TodoWrite is good at within-session
steps. Scope the two tools instead of having one override the other.

**It carries live state.** A static template can't tell you that 12 issues are
ready and 2 are assigned to you. That's the part worth spending tokens on; the
CLI surface is already covered by the skill and `gh --help`.

**It fails silent.** Any missing precondition exits 0 with no output. A prime
hook that errors at session start is worse than no prime hook.
