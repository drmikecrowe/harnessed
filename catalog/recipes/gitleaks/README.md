# gitleaks recipe

Secret-scanning gate for harnessed agent sessions.

## What it does

Downloads the [gitleaks](https://github.com/gitleaks/gitleaks) v8.30.1 binary and wires a
`PreToolUse` hook (`gitleaks-guard`) that blocks the agent's `git commit` and `git push` Bash
calls when secrets are detected in the staged tree or outgoing commits.

The hook is the only gate an agent **cannot bypass**: `--no-verify` skips git's hooks, not the
harness's — the Bash tool call itself is refused before it reaches the executor.

## What it does NOT do

It does not protect your own terminal `git commit` calls. For those, wire gitleaks per-repo via
[pre-commit](https://pre-commit.com/): `gitleaks git --staged` is the scan command. Never use a
global `core.hooksPath` — it silently overrides every repo's `.git/hooks` and breaks pre-commit.

## How it works in both modes

`install.sh` runs as a `RUN bash install.sh` layer during `podman build` **and** as a host
provisioner step on `launch --host`. One script, two executors, one outcome.

- Downloads `gitleaks_8.30.1_linux_{x64,arm64}.tar.gz` from the GitHub release.
- Extracts the `gitleaks` binary to `$HARNESSED_BIN_DIR` (on PATH first).
- Copies `gitleaks-guard` to `$HARNESSED_BIN_DIR`.
- Uses `$HARNESSED_INSTALL_CACHE` so the host re-downloads once, not every launch.

## gitleaks CLI notes (v8.30.1)

The `protect` and `detect` subcommands are **gone**. The commands are `git`, `dir`, `stdin`.
- Pre-commit scan: `gitleaks git --staged`
- Scan commits not yet pushed: `gitleaks git --log-opts="$upstream..HEAD"`
