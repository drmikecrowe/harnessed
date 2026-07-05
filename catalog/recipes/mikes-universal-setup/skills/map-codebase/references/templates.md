# Document Templates

Use these templates as starting structure when writing codebase analysis documents.
Expand, modify, or omit sections based on what you actually find in the codebase.

---

## STACK.md

```markdown
# Technology Stack

**Analysis Date:** YYYY-MM-DD

## Languages

**Primary:**
- [Language] [Version] — [Where used]

**Secondary:**
- [Language] [Version] — [Where used]

## Runtime

- [Runtime] [Version]
- Package manager: [Manager] [Version]
- Lockfile: [present/missing]

## Frameworks

**Core:**
- [Framework] [Version] — [Purpose]

**Testing:**
- [Framework] [Version] — [Purpose]

**Build/Dev:**
- [Tool] [Version] — [Purpose]

## Key Dependencies

**Critical** (core functionality depends on these):
- [Package] [Version] — [Why it matters]

**Infrastructure:**
- [Package] [Version] — [Purpose]

## Configuration

- How environment config is managed
- Key config files and their roles
- Secrets management approach
```

---

## INTEGRATIONS.md

```markdown
# External Integrations

**Analysis Date:** YYYY-MM-DD

## Databases
- [Database] — [How connected, which ORM/driver]
- Connection config: `path/to/config`

## External APIs
- [Service] — [Purpose, how authenticated]
- Client code: `path/to/client`

## Auth Providers
- [Provider] — [Flow type, where configured]

## Message Queues / Event Systems
- [System] — [Purpose, topics/queues used]

## Other Services
- [Service] — [Purpose]
```

---

## ARCHITECTURE.md

```markdown
# Architecture

**Analysis Date:** YYYY-MM-DD

## Pattern
[e.g., Layered MVC, Hexagonal, Microservices, Monolith]

## Layers
[Describe each layer and its responsibility]

## Entry Points
- [Entry point] — `path/to/file` — [What it handles]

## Data Flow
[Describe how a typical request flows through the system]

## Key Abstractions
- [Abstraction] — [Purpose, where defined]

## State Management
[How state is managed — database, cache, in-memory, etc.]
```

---

## STRUCTURE.md

````markdown
# Codebase Structure

**Analysis Date:** YYYY-MM-DD

## Directory Layout

```
project-root/
├── src/           # [description]
│   ├── ...
├── tests/         # [description]
├── ...
```

## Key Locations

- **Entry point:** `path/to/main`
- **Routes/handlers:** `path/to/routes/`
- **Business logic:** `path/to/services/`
- **Data layer:** `path/to/models/`
- **Configuration:** `path/to/config/`
- **Tests:** `path/to/tests/`

## Naming Conventions

- Files: [convention, e.g., kebab-case.ts]
- Directories: [convention]
- Components/Classes: [convention]

## Where to Add New Code

- New API endpoint: [where and how]
- New service/module: [where and how]
- New test: [where and how]
````

---

## CONVENTIONS.md

````markdown
# Coding Conventions

**Analysis Date:** YYYY-MM-DD

## Code Style

- Formatter: [tool and config file]
- Linter: [tool and config file]
- Style guide: [if any]

## Naming Patterns

- Functions: [convention with example]
- Variables: [convention with example]
- Constants: [convention with example]
- Types/Interfaces: [convention with example]

## Common Patterns

### [Pattern Name]
```[language]
// Example from codebase: `path/to/file`
[actual code example]
```

### Error Handling
[How errors are handled — show actual patterns from the code]

### Logging
[Logging approach — library, format, levels]

## Import Organization
[How imports are organized — order, grouping]
````

---

## TESTING.md

````markdown
# Testing

**Analysis Date:** YYYY-MM-DD

## Framework
- [Framework] [Version]
- Config: `path/to/config`

## Test Structure
- Unit tests: `path/to/unit/`
- Integration tests: `path/to/integration/`
- E2E tests: `path/to/e2e/`

## Running Tests
```bash
[command to run all tests]
[command to run specific test]
[command to run with coverage]
```

## Mocking Approach
[How mocks/stubs are created — library, patterns]

## Fixtures / Test Data
[How test data is managed]

## Coverage
- Current coverage: [if discoverable]
- Coverage config: `path/to/config`

## Patterns

### Writing a New Test
```[language]
// Example pattern from: `path/to/test`
[actual test example]
```
````

---

## CONCERNS.md

```markdown
# Concerns & Technical Debt

**Analysis Date:** YYYY-MM-DD

## High Priority

### [Issue Title]
- **Location:** `path/to/file:line`
- **Impact:** [What could go wrong]
- **Fix approach:** [How to address it]

## Medium Priority

### [Issue Title]
- **Location:** `path/to/file`
- **Impact:** [What could go wrong]
- **Fix approach:** [How to address it]

## Low Priority / Improvement Opportunities

### [Issue Title]
- **Location:** `path/to/file`
- **Note:** [Why it matters]

## TODOs and FIXMEs Found
- `path/to/file:line` — [content of TODO/FIXME]

## Missing or Weak Areas
- [Area with insufficient coverage, documentation, or testing]
```
