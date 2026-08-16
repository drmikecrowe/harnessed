# Load-Bearing Comments

Comment the load-bearing weirdness. Nothing else.

The target is narrow and specific: code a competent reader — human or agent — would reasonably
conclude is a bug, an inefficiency, or dead weight, and would therefore delete.

- Workarounds for upstream defects.
- Empirically tuned constants.
- Ordering dependencies that look arbitrary.
- Defensive checks for edge cases that appear in no test.
- Deliberate deviations from the surrounding convention.

## This is a guardrail, not documentation

An agent that meets an unexplained null check removes it — confidently, with a clean diff and a
passing suite — and reintroduces the bug someone fixed years ago. The comment is not there to
inform. It is there to make the reader **stop**.

That justification is also the bound: everything outside that class stays out. The code is the
documentation and always was, and a comment restating what a line plainly does is noise that ages
into a lie.

## Form: terse marker plus a reference

```
// Ordering matters here — see LW-4471
```

Not four sentences of inferred explanation. The marker says *stop*; the reference says *go read why*.
A tenth the context of a paragraph, and auditable.

**The reference is mandatory.** A rationale comment carrying no ticket, ADR, or commit SHA does not
merge. That is structural rather than stylistic: it converts an unverifiable assertion into a
checkable one, and a model cannot invent a ticket number that resolves. If you cannot cite why the
weirdness exists, you are inferring it — say so in those words, or leave the comment out. A confident
fabricated rationale is worse than no comment, because the next reader will trust it.

## The inverse obligation

Before you delete a check, a constant, or an ordering that carries a marker and a reference: read the
reference. "The suite passes without it" is not evidence. The test for that bug may be exactly the
thing that was never written, which is why the comment had to exist at all.
