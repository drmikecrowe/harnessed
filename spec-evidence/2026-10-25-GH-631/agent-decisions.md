# Agent decisions: Host launches stop wiping a profile another launch or session uses

### A1. A reused profile does not get the host settings merge
- Other option: run `_merge_host_claude_settings` on every launch, as today, including when the profile is reused.
- Why: the merge rewrites `settings.json` inside a profile a live session uses, which is the class of write this change stops; the builder already merged it, and host settings changes then apply after every session closes, like stack changes.
- Command: hotfix
