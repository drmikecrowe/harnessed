# Load-Bearing Comments

Comment the load-bearing weirdness. Nothing else.

Target: code a competent reader — human or agent — would call a bug, an inefficiency, or dead weight,
and would therefore delete.

- Workarounds for upstream defects.
- Empirically tuned constants.
- Ordering dependencies that look arbitrary.
- Defensive checks for edge cases no test covers.
- Deliberate deviations from the surrounding convention.

## A guardrail, not documentation

<!-- Why: an agent meets an unexplained null check, removes it, and reintroduces the bug someone
fixed years ago — clean diff, passing suite, full confidence. -->

The comment never informs. It makes the reader **stop**. That is also its bound: everything outside
that class stays out. A comment restating what a line plainly does ages into a lie.

## Form: terse marker plus a reference

```text
// Ordering matters here — see LW-4471
```

Never four sentences of inferred explanation. The marker says *stop*; the reference says *go read
why*.

**The reference is mandatory.** Never merge a rationale comment without a ticket, ADR, or commit SHA.
That turns an unverifiable assertion into a checkable one, and a model cannot invent a ticket number
that resolves.

Cannot cite why the weirdness exists → you are inferring. Say so in those words, or omit the comment.
A confident fabricated rationale is worse than none, because the next reader trusts it.

## The inverse obligation

Before deleting a check, constant, or ordering that carries a marker: read the reference. Never treat
"the suite passes without it" as evidence — see [[tests-are-authority]] §Green is not proof. The test
for that bug is often the one nobody wrote, which is why the comment had to exist.
