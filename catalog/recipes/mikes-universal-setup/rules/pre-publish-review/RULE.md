# Pre-Publish Review

Before ANY push, PR, or publish: read every file in the diff you did not author. Vendored deps,
third-party skills, WIP handed to you, anything you copied or cloned. No exception for "it is just
markdown" or "the user said it is fine" — publishing is irreversible, review is cheap.

This is **required review**, not routine re-validation. Guidance against reflexive `git` calls
targets re-checking your own work; it never exempts the read before an irreversible action.

A secret scanner catches key-shaped strings only. It cannot see the rest. That pass is yours.

## Check for

- **Live credentials** — keys, tokens, private keys, connection strings with real passwords.
- **Real names of private things** — vault or item names, internal hostnames, private URLs, buckets,
  client or employer names, ticket IDs. Placeholders (`op://Private/FOO`, `sk-ant-api12345....`) fine.
- **Personal paths** — `/home/<user>/…`, machine names, local ports revealing a private setup.
- **Unreleased or confidential content** — plans, prices, roadmaps, anything not already public.

## Vendored third-party content

- Never commit a clone. A nested `.git` makes git treat the dir as a foreign repo and silently skip
  its files. Copy the files you want; leave the clone behind.
- Record provenance where it will be read: upstream URL + **pinned** SHA or tag + license.
- Ship the upstream LICENSE next to the content.
- Prefer a pinned build-time fetch when upstream has real release tags and ships more than a file or
  two. Vendor only when it is small and untagged.

## Report

State provenance and what you checked, in the PR and to the user. Did not read a file → say so.
Never imply coverage you do not have.

Pairs with [[stop-and-ask]]: that gates WHETHER you publish, this gates WHAT.
