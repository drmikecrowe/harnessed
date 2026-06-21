---
name: greet-helper
description: Greet the user by name with a friendly, time-aware hello. A recipe-breadth tracer skill (no dependencies, no MCP).
---

# Greet Helper

A minimal standalone skill that ships no dependencies and consumes no MCP server — it exists to
prove a second recipe composes into a stack alongside `time` (plan 04-03, success criterion 2).

When the user asks to be greeted, respond with a short, friendly greeting that includes their name
(if known) and a coarse time-of-day salutation (good morning / afternoon / evening). Keep it brief
and natural; this is a tracer, not a feature.
