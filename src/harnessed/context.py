"""What a stack makes the agent read every session, and what in it is duplicated or leaked.

`harnessed context` prints this. Read-only: nothing here writes.

Three sources, because the agent loads all three:
  - memory: the config dir's CLAUDE.md and rules/**.md, loaded whole into every session;
  - skills: each SKILL.md's description, listed in every session (bodies load on use);
  - leaks: CLAUDE.md files and .claude/rules above the project, which Claude Code loads by walking
    up from the working directory, whatever CLAUDE_CONFIG_DIR says.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .prose import description_of, split_frontmatter

_NAME_RE = re.compile(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.MULTILINE)

# The memory files Claude Code picks up in each ancestor directory.
_ANCESTOR_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")


@dataclass(frozen=True)
class Item:
    kind: str  # "memory" | "skill" | "leak"
    name: str
    path: Path
    tokens: int


def estimate_tokens(text: str) -> int:
    # shortcut: chars/4, not a tokenizer; good enough to rank, upgrade if budgets become exact.
    return len(text) // 4


def _md_files(root: Path, filename: str | None = None) -> list[Path]:
    """Every .md file (or every `filename`) under `root`, following symlinked dirs: host launches
    link plugin dirs into the config dir, and rglob does not descend into those."""
    out = []
    seen: set[str] = set()
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        # A link back to an ancestor would otherwise walk forever.
        real = os.path.realpath(dirpath)
        if real in seen:
            dirs.clear()
            continue
        seen.add(real)
        for f in files:
            if (f == filename) if filename else f.endswith(".md"):
                p = Path(dirpath) / f
                if p.is_file():
                    out.append(p)
    return sorted(out)


def _skill(path: Path) -> Item:
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, _body = split_frontmatter(text)
    named = _NAME_RE.search(frontmatter)
    name = named.group(1) if named else path.parent.name
    return Item("skill", name, path, estimate_tokens(description_of(frontmatter)))


def collect(config_dir: Path, project_dir: Path | None = None) -> list[Item]:
    """Everything always loaded for a session in `config_dir`, plus leaks above `project_dir`."""
    items = []
    memory = [config_dir / "CLAUDE.md", *_md_files(config_dir / "rules")]
    for p in memory:
        if p.is_file():
            items.append(Item("memory", p.name, p, estimate_tokens(p.read_text(errors="replace"))))
    items += [_skill(p) for p in _md_files(config_dir / "skills", "SKILL.md")]
    if project_dir is not None:
        for d in Path(project_dir).resolve().parents:
            leaked = [d / f for f in _ANCESTOR_FILES] + _md_files(d / ".claude" / "rules")
            for p in leaked:
                if p.is_file():  # a dangling symlink loads nothing, so it is not a leak
                    text = p.read_text(errors="replace")
                    items.append(Item("leak", p.name, p, estimate_tokens(text)))
    return items


def problems(items: list[Item]) -> list[str]:
    """What the build should not have produced: one skill name installed twice, one file's content
    loaded twice, and any leak at all."""
    out = []
    by_name: dict[str, list[Path]] = defaultdict(list)
    for it in items:
        if it.kind == "skill":
            by_name[it.name].append(it.path)
    for name, where in sorted(by_name.items()):
        if len(where) > 1:
            out.append(f"skill '{name}' is installed {len(where)} times: " + ", ".join(map(str, where)))
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for it in items:
        if it.kind in ("memory", "leak"):
            by_hash[hashlib.sha256(it.path.read_bytes()).hexdigest()].append(it.path)
    for where in by_hash.values():
        if len(where) > 1:
            out.append("same content loaded twice: " + ", ".join(map(str, where)))
    out += [f"loaded from outside the stack: {it.path}" for it in items if it.kind == "leak"]
    return out
