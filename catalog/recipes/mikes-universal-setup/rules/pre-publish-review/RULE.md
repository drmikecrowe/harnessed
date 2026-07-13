# Pre-Publish Review

Before ANY push, PR, or publish: read every file in the diff you did not author yourself.
Vendored deps, third-party skills, WIP handed to you, files you copied or cloned. No exceptions
for "it's just markdown" or "user said it's fine" — publishing is irreversible, review is cheap.

A secret scanner catches key-shaped strings only. It cannot see the leaks below. That pass is yours.

## Check for

- **Live credentials** — keys, tokens, private keys, connection strings with real passwords.
- **Real names of private things** — vault/item names, internal hostnames, private URLs, S3 buckets,
  client/employer names, ticket IDs. Placeholders (`op://Private/FOO`, `sk-ant-api12345....`) fine.
- **Personal paths** — `/home/<user>/...`, machine names, local ports that reveal a private setup.
- **Unreleased/confidential content** — plans, prices, roadmaps, anything not already public.

## Vendored third-party content

- Never commit a clone. A nested `.git` makes git treat the dir as a foreign repo and silently skip
  its files. Copy the files you want; leave the clone behind.
- Record provenance where it will be read: upstream URL + **pinned** commit SHA or tag + license.
- Ship the upstream LICENSE next to the content.
- Prefer a pinned build-time fetch over a vendored copy when upstream has real release tags and
  ships more than a file or two. Vendor when it is small and untagged.

## Report

State provenance and what you checked, in the PR and to the user. If you did not read a file, say
so — do not imply coverage you do not have.

Pairs with [stop-and-ask] (no outward-facing action without an explicit yes) — that gates WHETHER
you publish; this gates WHAT you publish.
