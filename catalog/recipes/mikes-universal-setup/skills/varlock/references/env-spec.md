# varlock / @env-spec Reference

Full docs: https://varlock.dev/llms-small.txt

## Item Decorators

### `@required` / `@optional`
Validation fails if value resolves to `undefined` or empty string.
```env-spec
# @required
ITEM=

# @optional
ITEM=some-default

# @required=forEnv(prod)        ← required only in production
# @required=eq($OTHER, foo)     ← required if OTHER equals "foo"
```

### `@sensitive`
Masks value in logs, `varlock load` output, and generated type comments.
```env-spec
# @required @sensitive
API_KEY=op(op://Vault/Item/credential)
```

### `@example`
Shows a sample value without using it as a default or placeholder.
```env-spec
# @required @sensitive @example="sk-ant-api12345...."
ANTHROPIC_API_KEY=
```

### `@type`
Sets type for validation and coercion. See types below.
```env-spec
# @type=string(minLength=5, maxLength=50)
# @type=number(min=0, max=100)
# @type=boolean
# @type=url(prependHttps=true, noTrailingSlash=true)
# @type=enum(development, staging, production)
# @type=port(min=1024)
# @type=email(normalize=true)
# @type=ip(version=4)
```

### `@docs()` / `@docsUrl` (deprecated)
Links to documentation. Can be called multiple times.
```env-spec
# @docs(https://docs.stripe.com/keys)
# @docs("Auth guide", https://example.com/auth)
STRIPE_KEY=
```

### `@icon`
Attaches an iconify icon identifier (for UI surfaces and generated docs).
```env-spec
# @icon=mdi:key
API_KEY=
```

### `@auditIgnore`
Suppress "unused in schema" warning from `varlock audit` for items consumed externally.

## Root Decorators (before `# ---`)

### `@defaultRequired`
```env-spec
# @defaultRequired=true     ← all items required unless @optional
# @defaultRequired=false    ← all items optional unless @required
# @defaultRequired=infer    ← required if has a value, optional if empty
```

### `@defaultSensitive`
```env-spec
# @defaultSensitive=true
# @defaultSensitive=false
# @defaultSensitive=inferFromPrefix(PUBLIC_)   ← PUBLIC_ keys are not sensitive
```

### `@plugin()`
Load a plugin (registers new decorators/resolvers/types).
```env-spec
# @plugin(@varlock/1password-plugin@0.3.2)
# @plugin(@varlock/aws-secrets-plugin)
```

### `@currentEnv`
Declare which variable holds the current environment name.
```env-spec
# @currentEnv=$NODE_ENV
```

### `@generateTypes`
Generate TypeScript types from the schema.
```env-spec
# @generateTypes(outputPath=./src/env.d.ts)
```

## Data Types Reference

| Type | Options |
|------|---------|
| `string` | `minLength`, `maxLength`, `toUpperCase`, `toLowerCase`, `startsWith`, `endsWith` |
| `number` | `min`, `max`, `precision`, `isInt`, `isDivisibleBy`, `coerceToMinMaxRange` |
| `boolean` | — (accepts t/true/yes/on/1 and f/false/no/off/0) |
| `url` | `prependHttps`, `allowedDomains`, `noTrailingSlash`, `matches` |
| `enum` | Comma-separated values: `enum(a, b, c)` (required to have args) |
| `email` | `normalize` |
| `port` | `min` (default 0), `max` (default 65535) |
| `ip` | `version` (4 or 6), `normalize` |

## Resolver Functions

### Static / computed values
```env-spec
ITEM=some-value
ITEM=exec('which op')              # run shell command
ITEM=${OTHER_VAR}/suffix           # variable interpolation
ITEM=ref($OTHER_VAR)               # reference another item
ITEM=remap($VAR, "a", 1, "b", 2)  # map values
ITEM=forEnv(prod=foo, dev=bar)     # env-specific value
```

### 1Password plugin (`@varlock/1password-plugin`)
```env-spec
# @plugin(@varlock/1password-plugin@0.3.2)
# @initOp(allowAppAuth=true)   ← use 1Password app auth (no service token needed)
# ---

# @type=opServiceAccountToken  ← use service account token instead of app auth
OP_TOKEN=

ITEM=op(op://VaultName/ItemName/field)
ITEM=op(instanceId, op://VaultName/ItemName/field)  # multi-instance

# Bulk load all fields from a 1Password environment
# @setValuesBulk(opLoadEnvironment(op://Vault/Item), format=json)
```

**`@initOp` options:**
- `allowAppAuth=true` — use the 1Password desktop app (no token needed)
- `serviceAccountToken=$OP_TOKEN` — use a service account token

### Local encryption
```env-spec
ITEM=varlock(encrypted)    # value encrypted with local key
ITEM=varlock(prompt)       # prompt for value on first load
```

## Conditional Logic

```env-spec
# @required=eq($OTHER, foo)           # required if OTHER == "foo"
# @required=forEnv(prod, staging)     # required in prod and staging
ITEM=remap($ENV, "main", production, /.*/, preview, undefined, development)
```

## Best Practices

- Use `# --- Section ---` dividers to group related items
- Always add descriptions above sensitive items
- Prefer `@example` over placeholder values (placeholders get accidentally used)
- Use `op()` for all secrets; commit `.env.schema`, never `.env`
- Use `exec('which op')` to discover tool paths at load time
- Prefer `@docs()` over `@docsUrl` (deprecated)
- Use `# @defaultRequired=true` at the top to enforce completeness
