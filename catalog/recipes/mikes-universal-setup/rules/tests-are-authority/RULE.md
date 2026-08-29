# Tests Are Authority

An existing test encodes a decision already made. Your change does not outrank it.

## Default

- Test fails after your change → **your change is wrong**. Fix the code.
- Never widen an assertion, loosen a tolerance, add skip/xfail, or delete a case to reach green.
- Change a test only when the task intentionally changes the behaviour it covers. Name that
  behaviour in the commit body, and say why the old assertion no longer describes it.
- Never delete a test you do not understand. Same reflex [[load-bearing-comments]] exists to stop.

## If the test is genuinely wrong

- Reproduce it alone, then reproduce the passing case. Name the ONE variable that differs.
- State the diagnosis before editing the file. Evidence, never convenience.
- Fix the SETUP, not the ASSERTION. Failure from ambient state — an exported env var, the real
  `$HOME`, machine-local config — is a broken fixture, never a wrong expectation.

<!-- Instance: harnessed #432 — five tests failed on any machine with the harness OAuth token
exported. Code correct, expectation correct, fixture missing one monkeypatch.delenv. -->

## Green is not proof

- "It passes without it" never justifies deleting a check — see [[load-bearing-comments]]
  §The inverse obligation.
- Local red where CI is green is a FINDING: an ambient variable, a machine-dependent fixture, or a
  test CI skips. Diagnose it. Never report it as "pre-existing failures" — that sentence tells the
  reader the mainline is broken.

Writing new tests is [[coding-principles]] §Verification. This rule governs existing tests only.
