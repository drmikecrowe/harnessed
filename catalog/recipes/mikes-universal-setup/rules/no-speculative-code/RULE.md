# No Speculative Code

[[coding-principles]] §2 says simplicity first. This is the named blocklist, because a principle does
not fire at the moment you are typing the interface.

Each section bans code you would ADD. None licenses removing what exists — that is
[[coding-principles]] §3 and [[load-bearing-comments]].

## Abstractions

Abstract only to remove complexity you can point at. Never write:

- an interface, `Protocol`, or ABC with one implementation
- a factory or builder returning one type
- a wrapper that only delegates
- a parameter, flag, or config key with one caller and one value
- a generic helper whose only caller is the code you just wrote

Three similar lines beat a premature abstraction. Wait for the third real caller, then extract what
they actually share.

## Error handling

- Do not handle what cannot happen. Trust internal contracts.
- Validate at system boundaries ONLY: user input, API and subprocess responses, file/env/network
  reads, deserialization.
- Never add a `try`/`except` that only logs, swallows, or re-raises unchanged. Let it propagate.
- Never substitute a default for a real failure. Fail loudly at the boundary.

## Dependencies

- A few lines of code beat a new dependency.
- An existing dependency covering the case beats a new one. Read the manifest first.
- A new dependency needs a stated reason and a pin. Raise it; never bury it in a diff.
