"""Copy `~/.claude/CLAUDE.md` @-imports into a stack's rules, because ACP sessions drop them (GH-600).

A headless ACP session (claude-agent-acp 0.85.1 and 0.89.1) loads CLAUDE.md files but expands none of
their `@`-imports, and it loads no symlinked rule. It does load a regular file anywhere under the
config dir's `rules/`. So, when the user agrees, harnessed keeps a real copy of each imported file in
`rules/harnessed-imports/`, a directory it owns outright, and rewrites it on every launch: a one-time
copy would go stale after `gortex instructions switch`.

Only `~/.claude/CLAUDE.md` is read. Parent and project CLAUDE.md imports differ per project, and one
`host-acp` agent serves many projects from one stack home, so converting them would leak one
project's instructions into the others.

The answer is stored per stack: `y` copies; `n` copies nothing and `host-acp` keeps warning; `i`
copies nothing and silences the warning.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import typer
from rich.markup import escape

from . import paths
from .console import _can_prompt, _err, in_acp_mode

PROMPT = (
    "Your ~/.claude/CLAUDE.md uses @import syntax that ACP sessions do not expand. "
    "Copy the imported files into this stack's rules? [y/n/i]"
)
ANSWERS = ("y", "n", "i")
OWNED_DIR = "harnessed-imports"


def _warn(text: str) -> None:
    _err.print(f"[yellow]warning:[/yellow] {escape(text)}", soft_wrap=True)


def import_file() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def find_imports(text: str) -> list[Path]:
    """The import targets in `text`, in order, each once.

    An import is a line whose stripped text is `@<path>` with no whitespace in the path (GH-600
    Decide 2): an `@` inside prose, such as an e-mail address, is never one. `~/` is the home dir and
    a relative path is relative to `~/.claude/`, the directory the file sits in.
    """
    found: dict[Path, None] = {}
    for line in text.splitlines():
        s = line.strip()
        ref = s[1:]
        if not s.startswith("@") or not ref or any(c.isspace() for c in ref):
            continue
        if ref.startswith("~/"):
            target = Path.home() / ref[2:]
        elif ref.startswith("/"):
            target = Path(ref)
        else:
            target = Path.home() / ".claude" / ref
        found.setdefault(target, None)
    return list(found)


def _current_imports() -> list[Path]:
    try:
        return find_imports(import_file().read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def read_answer(stack: str) -> str | None:
    """The stored answer, or None for none — an unreadable or unknown value counts as none."""
    try:
        value = paths.claude_imports_answer_file(stack).read_text(encoding="utf-8")
    except OSError:
        return None
    return value if value in ANSWERS else None


def write_answer(stack: str, answer: str) -> None:
    f = paths.claude_imports_answer_file(stack)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(answer, encoding="utf-8")


def ask(stack: str, *, reask: bool = False) -> None:
    """Ask the question once per stack, where someone can answer it.

    `build`, `install`, `host-run` and `container-run` call this. Nobody is at an ACP or `-exec`
    launch, so there it asks nothing; `--reask-imports` with no terminal still clears the answer.
    """
    if reask:
        paths.claude_imports_answer_file(stack).unlink(missing_ok=True)
    if not _current_imports() or read_answer(stack) is not None:
        return
    if in_acp_mode() or not _can_prompt():
        if reask:
            _warn(
                f"--reask-imports needs a terminal; the stored answer for {stack} is cleared. "
                f"Run: harnessed build {stack} claude --reask-imports"
            )
        return
    answer = ""
    while answer not in ANSWERS:
        answer = typer.prompt(PROMPT, prompt_suffix=" ").strip().lower()
    write_answer(stack, answer)


def acp_warning(stack: str) -> None:
    """`host-acp`: say on stderr that the imports will not load, unless the user said `y` or `i`."""
    if _current_imports() and read_answer(stack) in (None, "n"):
        _warn(
            "~/.claude/CLAUDE.md has @-imports this ACP session will not load. "
            f"Run: harnessed build {stack} claude --reask-imports"
        )


def copy_name(target: Path) -> str:
    """`<stem>-<8 hex of sha256 of the path>.md`: stable per target, distinct for two `notes.md`."""
    return f"{target.stem}-{hashlib.sha256(str(target).encode()).hexdigest()[:8]}.md"


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def _write_failed(stack: str, exc: OSError) -> None:
    _warn(f"could not update the @-import copies for {stack}: {exc}")


def refresh(stack: str) -> Path | None:
    """Rewrite the stack's copies dir from the import targets; None when the answer is not `y`.

    The directory itself is kept and only its contents change, so a running container's bind mount
    of it sees the new files. Without a `y` no target is even read. A missing or unreadable target,
    or a copies dir that cannot be written, is a warning, never a failure: a launch must not break
    over an import.
    """
    try:
        return _refresh(stack)
    except OSError as exc:
        _write_failed(stack, exc)
        return None


def _refresh(stack: str) -> Path | None:
    d = paths.claude_imports_dir(stack)
    if read_answer(stack) != "y":
        if d.is_dir():
            for f in d.iterdir():
                _remove(f)
        return None
    want: dict[str, bytes] = {}
    for target in _current_imports():
        if not target.is_file():
            _warn(f"@-import target not found, skipped: {target}")
            continue
        try:
            want[copy_name(target)] = target.read_bytes()
        except OSError as exc:
            _warn(f"@-import target unreadable, skipped: {target} ({exc.strerror})")
    d.mkdir(parents=True, exist_ok=True)
    for f in d.iterdir():
        if f.name not in want:
            _remove(f)
    for name, data in want.items():
        (d / name).write_bytes(data)
    return d


def sync_owned_dir(stack: str, rules_dir: Path) -> None:
    """Host: make `rules_dir/harnessed-imports/` hold exactly the stack's current copies.

    Only that directory is touched; every other file under `rules_dir` is the stack's or the user's.
    """
    src = refresh(stack)
    owned = rules_dir / OWNED_DIR
    try:
        if owned.exists() or owned.is_symlink():
            _remove(owned)
        if src is None:
            return
        owned.mkdir(parents=True)
        for f in sorted(src.iterdir()):
            shutil.copyfile(f, owned / f.name)
    except OSError as exc:
        _write_failed(stack, exc)


def mount_args(stack: str, container_dir: str) -> list[str]:
    """Container: the ro bind mount of the refreshed copies dir at `container_dir`, or none."""
    src = refresh(stack)
    return [] if src is None else ["-v", f"{src}:{container_dir}:ro"]
