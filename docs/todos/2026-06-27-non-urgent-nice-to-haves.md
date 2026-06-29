- [ ] Install ccstatusline@latest
- [ ] Ability to add to the system prompt
- [ ] `harnessed persist prune` — GC the per-project persist dirs at `XDG_DATA/harnessed/<stack>/<hash>/`.
      They survive `harnessed clean`/`rm` today (siblings of `profiles_root()`), so nothing reclaims them.
      Deferred from the /autoplan eng review of the persist slice (2026-06-29).
