# Load-Bearing Comments

Comment the load-bearing weirdness. Nothing else.

The target is narrow. Comment code that a competent reader — human or agent — would call a bug, an
inefficiency, or dead weight, and would therefore delete.

- Workarounds for upstream defects.
- Empirically tuned constants.
- Ordering dependencies that look arbitrary.
- Defensive checks for edge cases that appear in no test.
- Deliberate deviations from the surrounding convention.

## This is a guardrail, not documentation

An agent meets an unexplained null check and removes it. Clean diff, passing suite, full confidence.
It has just reintroduced the bug someone fixed years ago.

The comment never exists to inform. It exists to make the reader **stop**.

That justification is also the bound. Everything outside that class stays out. The code is the
documentation and always was. A comment restating what a line plainly does always ages into a lie.

## Form: terse marker plus a reference

```text
// Ordering matters here — see LW-4471
```

Not four sentences of inferred explanation. The marker says *stop*; the reference says *go read why*.
A tenth the context of a paragraph, and auditable.

**The reference is mandatory.** Never merge a rationale comment carrying no ticket, ADR, or commit
SHA. That is structural, not stylistic: it turns an unverifiable assertion into a checkable one, and
a model cannot invent a ticket number that resolves.

If you cannot cite why the weirdness exists, you are inferring it. Say so in those words, or leave
the comment out. A confident fabricated rationale is worse than no comment, because the next reader
trusts it.

## The inverse obligation

Before you delete a check, a constant, or an ordering that carries a marker: read the reference.
Never treat "the suite passes without it" as evidence. The test for that bug is often the thing
nobody wrote, which is why the comment had to exist.
