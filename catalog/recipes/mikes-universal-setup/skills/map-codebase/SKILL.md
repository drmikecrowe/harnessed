---
name: map-codebase
description: >
  Analyze an existing codebase by running parallel analysis agents across four domains:
  technology stack, architecture, coding conventions, and technical concerns.
  Produces 7 structured markdown documents. Use when the user asks to "map codebase",
  "analyze codebase", "document existing code", "understand this project",
  "codebase analysis", "what does this codebase look like", or when onboarding
  to a brownfield project. Also use when the user says "map my code",
  "analyze my project structure", or "generate codebase documentation".
license: MIT
compatibility: >
  Best with Claude Code (parallel agent spawning via Task tool).
  Works sequentially with any agent that has filesystem access.
  Requires: ability to read files, run glob/grep, and write markdown files.
metadata:
  author: TÂCHES
  version: "1.0"
  category: development
  tags: codebase-analysis, documentation, onboarding, brownfield
  upstream: https://github.com/gsd-build/get-shit-done
---

# Map Codebase

Analyze an existing codebase and produce structured documentation across four domains.
Each domain writes its documents directly — no round-tripping content through the orchestrator.

## Output

All documents are written to `docs/codebase/` in the project root:

| Domain | Documents |
|--------|-----------|
| Tech stack | `STACK.md`, `INTEGRATIONS.md` |
| Architecture | `ARCHITECTURE.md`, `STRUCTURE.md` |
| Conventions | `CONVENTIONS.md`, `TESTING.md` |
| Concerns | `CONCERNS.md` |

## Step 1 — Check for existing map

Check if `docs/codebase/` already exists.

If it exists, show the user what documents are present and ask:
1. **Refresh** — Delete existing docs and remap the entire codebase
2. **Skip** — Keep existing map as-is

If the user chooses Skip, stop. If Refresh, delete `docs/codebase/` and continue.

If `docs/codebase/` does not exist, continue.

## Step 2 — Create output directory

```bash
mkdir -p docs/codebase
```

## Step 3 — Run analysis

There are two execution modes depending on your agent's capabilities.

### Mode A: Parallel (Claude Code with Task tool)

Spawn 4 background agents simultaneously using `Task(run_in_background=true)`.
Each agent gets one of the four focus prompts below.
Wait for all to complete, then go to Step 4.

### Mode B: Sequential (any agent)

Run each of the four focus areas one at a time, in order: tech → arch → quality → concerns.
For each focus area, follow the exploration and writing process described below, then move to the next.

---

### Focus: tech

Analyze the technology stack and external integrations.

**Explore:**
- Read root config files: `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `Gemfile`, `pom.xml`, `build.gradle`, `Makefile`, `Dockerfile`, `docker-compose.yml`, `.tool-versions`, `.node-version`, `.python-version`
- Use Glob to find config files you missed
- Use Grep to find import statements, framework usage patterns, database drivers, HTTP clients, auth libraries

**Write to `docs/codebase/`:**
- `STACK.md` — Languages, runtime, frameworks, package manager, key dependencies, configuration approach
- `INTEGRATIONS.md` — External APIs, databases, auth providers, message queues, webhooks, third-party services

Use the templates in [references/templates.md](references/templates.md).

---

### Focus: arch

Analyze the architecture and directory structure.

**Explore:**
- Map the top-level directory layout
- Trace entry points (main files, route handlers, CLI entrypoints)
- Identify architectural pattern (MVC, hexagonal, microservices, monolith, etc.)
- Follow data flow through a typical request/operation
- Find key abstractions and interfaces

**Write to `docs/codebase/`:**
- `ARCHITECTURE.md` — Pattern, layers, data flow, entry points, key abstractions, state management
- `STRUCTURE.md` — Directory layout, key locations, naming conventions, where to add new code

Use the templates in [references/templates.md](references/templates.md).

---

### Focus: quality

Analyze coding conventions and testing patterns.

**Explore:**
- Check for formatter/linter configs (`.prettierrc`, `.eslintrc`, `rustfmt.toml`, `ruff.toml`, `.editorconfig`, etc.)
- Read actual source files to identify naming patterns, error handling, logging, import organization
- Find test directories and read example tests
- Check for test config, coverage config, CI test commands

**Write to `docs/codebase/`:**
- `CONVENTIONS.md` — Code style, naming patterns, error handling, logging, common patterns with real code examples
- `TESTING.md` — Test framework, structure, mocking approach, how to write and run tests

Use the templates in [references/templates.md](references/templates.md).

---

### Focus: concerns

Analyze the codebase for technical debt and issues.

**Explore:**
- Grep for `TODO`, `FIXME`, `HACK`, `XXX`, `WORKAROUND`, `@deprecated`
- Look for suppressed warnings, unchecked errors, empty catch blocks
- Check for missing tests, outdated dependencies, security issues
- Identify fragile areas, inconsistencies, and missing documentation

**Write to `docs/codebase/`:**
- `CONCERNS.md` — Technical debt prioritized by severity (high/medium/low), TODOs/FIXMEs found, missing or weak areas

Use the templates in [references/templates.md](references/templates.md).

---

## Writing rules (all focus areas)

- **Always use the Write tool** to create files — never use `cat << 'EOF'` or heredocs
- **Always include actual file paths** formatted with backticks: `src/services/user.ts`
- **Document quality over brevity** — a 200-line CONVENTIONS.md with real code patterns beats a 50-line summary
- **Show patterns, not just lists** — include HOW things are done with code examples from the actual codebase
- **Be prescriptive** — "Use camelCase for functions" helps an agent write correct code; "Some functions use camelCase" doesn't

## Step 4 — Summary

After all four domains are complete, list the documents that were created:

```
## Codebase Map Complete

Documents written to docs/codebase/:
- STACK.md — Technology stack and dependencies
- INTEGRATIONS.md — External services and APIs
- ARCHITECTURE.md — Architecture patterns and data flow
- STRUCTURE.md — Directory layout and conventions
- CONVENTIONS.md — Code style and patterns
- TESTING.md — Test framework and practices
- CONCERNS.md — Technical debt and issues
```
