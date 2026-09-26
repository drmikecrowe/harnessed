---
name: diagnosis-discipline
description: Find the real cause of a failure before naming one. Use when a test passes alone and fails in the suite, when local and CI disagree, when a bug reproduces on one machine only, and before writing "the cause is".
---

# Diagnosis discipline

A wrong cause published with confidence costs more than no cause. Every step below exists because
skipping it once produced a wrong public diagnosis. The output of this skill is a cause with
evidence in both directions, or the statement that the cause is not yet known.

## The disagreement is the finding

Local red and CI green is a result, not noise. So is "passes on my machine". Never file either as
"pre-existing" or "flaky"; those words end the investigation without a cause. One of three things is
true: an ambient environment variable, a machine-dependent fixture, or a test one side skips. Find
which.

## Procedure

1. **Run the failing thing alone.** If it passes alone, the cause is pollution from something that
   ran before it, and reading the failing test will not find it.
2. **Bisect by pairing, not by reading.** Run the failing file with one other file at a time until a
   pair reproduces. Then pair tests inside those files. Two files out of ninety is a normal result.
   Code reading starts after the pair is known, never before.
3. **Vary the environment one axis at a time.** Unset one variable; swap in an empty home directory;
   change the working directory. The single axis that flips the result names the cause. Two axes
   changed at once name nothing.
4. **Read the wall clock.** The same tests taking four times longer in one environment means hidden
   work: real subprocesses, real network, real credentials. Compare durations across runs, not only
   pass and fail.
5. **Separate test leakage from production writes.** A test fixture that sets and restores is not the
   leak. Production code called from a test can write the process environment permanently, and no
   fixture restores that. Search for raw writes, not for fixtures.
6. **Prove it at the scale where it failed.** A negative experiment on one file does not carry to the
   suite. Before naming the cause, re-run the full failing scenario with the one axis changed, and
   re-run it once more with the axis restored. Both results go in the report.

## The report

In this order, each one line where one line suffices:

- Symptom, as the exact command and the exact output.
- The reproduction: the smallest command that shows it.
- The one axis, and the two results: with it changed, with it restored.
- The cause, stated once.
- The fix, and the check that shows the symptom gone.

A report missing the two-direction evidence is a hypothesis. Label it as one.

## What not to infer from

- Summary counts across environments ("45 skipped here, 53 there"). A worktree, a missing binary,
  and an ambient variable all move that number, and the deltas add.
- The most recent change. Recency is a place to start bisecting, never a cause.
- One negative experiment. Removing X and seeing green proves X is sufficient to hide the symptom.
  It does not prove X is the cause.
