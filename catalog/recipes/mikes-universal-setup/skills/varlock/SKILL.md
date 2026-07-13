---
name: varlock
description: >
  Create, edit, and maintain `.env.schema` files using the varlock/@env-spec DSL. Use when:
  working with `.env.schema` files; adding or updating environment variable definitions;
  migrating from `.env.example` to `.env.schema`; running varlock CLI commands (init, load,
  run, encrypt, audit, reveal, lock); setting up varlock in a new project; debugging missing
  or invalid env vars; integrating secrets from 1Password or other secret managers.
---

# Varlock

Varlock uses the `@env-spec` DSL — decorator-style comments on top of standard `.env` syntax — to declare schemas for environment variables with types, validation, secrets integration, and defaults.

Full decorator/type reference: [references/env-spec.md](references/env-spec.md)

## File Structure

```env-spec
# This env file uses @env-spec - see https://varlock.dev/env-spec for more info
# @plugin(@varlock/1password-plugin@0.3.2)   ← root decorator (before ---)
# @initOp(allowAppAuth=true)
# ---                                         ← divider separates root from items

# --- Section Name ---                        ← organize items with dividers

# Human-readable description of what this var does
# @required @sensitive @example="sk-ant-api12345...."
ANTHROPIC_API_KEY=op(op://Private/ANTHROPIC_API_KEY/credential)
```

**Key rules:**
- Root decorators (`@plugin`, `@initOp`, `@defaultRequired`, etc.) go before `# ---`
- Item decorators (`@required`, `@sensitive`, `@type`, `@example`) go immediately above the key
- `ALL_CAPS` keys only; no `-` or `.`; no spaces around `=`
- Use `# ---` dividers to group related items

## Common Patterns

### 1Password secrets (used in all projects)

```env-spec
# @plugin(@varlock/1password-plugin@0.3.2)
# @initOp(allowAppAuth=true)
# ---

# @required @sensitive
SECRET=op(op://VaultName/ItemName/credential)
```

### API keys with examples

```env-spec
# @required @sensitive @example="sk-ant-api12345...."
ANTHROPIC_API_KEY=op(op://Private/ANTHROPIC_API_KEY/credential)

# @required @sensitive @example="AIxxxxxxx"
GEMINI_API_KEY=op(op://Private/GEMINI_API_KEY/credential)
```

### Derived/constructed values

```env-spec
# Individual components
# @required
DB_HOST=localhost
# @required
DB_PORT=5432
# @required
DB_USER=myapp

# @required @sensitive
DB_PASSWORD=op(op://Private/DB_PASSWORD/credential)

# Constructed DSN — override if using a managed instance
# @required @sensitive
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/myapp
```

### Tool path discovery

```env-spec
OP_LOCATION=exec('which op')
```

### Typed items

```env-spec
# @required @type=port
PORT=3000

# @required @type=url(prependHttps=true)
API_BASE_URL=https://api.example.com

# @required @type=enum(development, staging, production)
NODE_ENV=development

# @required @type=boolean
FEATURE_FLAG=false
```

## CLI Commands

| Command | Purpose |
|---------|---------|
| `varlock init` | Bootstrap `.env.schema` from existing `.env` files |
| `varlock load` | Debug/validate — shows resolved values and errors |
| `varlock run -- <cmd>` | Run a command with validated env vars injected |
| `varlock encrypt --file .env.local` | Encrypt sensitive values in a file |
| `varlock reveal` | Decrypt and show sensitive values |
| `varlock lock` | Re-encrypt all decryptable values |
| `varlock audit` | Report unused or undeclared vars |

**Invoke via package manager (JS/TS projects):**
```bash
pnpm exec -- varlock load
npx varlock load
bunx varlock load
```

**Standalone binary:**
```bash
varlock load
varlock run -- python main.py
```

## Installation

**JS/TS project:**
```bash
pnpm dlx varlock init   # installs + generates .env.schema from existing .env
```

**Standalone binary:** Download from https://varlock.dev/getting-started/installation

## Decorator Quick Reference

See [references/env-spec.md](references/env-spec.md) for the full reference. Most common:

| Decorator | Usage |
|-----------|-------|
| `@required` | Fail if value is empty/undefined |
| `@optional` | Opposite of required |
| `@sensitive` | Mask in logs/output |
| `@example="val"` | Show example without setting a placeholder |
| `@type=string` | Set type (string, number, boolean, url, enum, port, email, ip) |
| `@docs(url)` | Link to documentation |
