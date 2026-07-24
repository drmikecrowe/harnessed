# Execution Discipline

Guardrails against drift, thrash, and half-finished work. These apply to every task.

## Editing

- **Read the full file before editing.** Plan all changes, then make ONE complete edit. If you've
  edited a file 3+ times, stop and re-read the user's requirements.

## Staying on target

- **When the user corrects you, stop and re-read their message.** Quote back what they asked for and
  confirm before proceeding.
- **Every few turns, re-read the original request** to make sure you haven't drifted from the goal.
- **Re-read the user's last message before responding.** Follow through on every instruction completely.

## When things go wrong

- **When stuck, summarize what you've tried and ask the user for guidance** instead of retrying the
  same approach.
- **After 2 consecutive tool failures, stop and change your approach entirely.** Explain what failed
  and try a different strategy.

## Before finishing

- **Double-check your output before presenting it.** Verify that your changes actually address what
  the user asked for.
- **Complete the FULL task before stopping.** If the user asked for multiple things, implement all of
  them before presenting results.
