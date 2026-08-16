"""Prose lint for injected content — RULE.md, SKILL.md, and skill `description:` fields.

Rules and skills are the bytes a model reads every session, and the SAME bytes are adapted to every
harness (`Claude format is canonical`). Prose that is vague on Claude is vague on codex too, so the
fix belongs at authoring time, in the canonical source — not in a runtime transform that would
mangle a file after a human reviewed it.

The standard this enforces is ASD-STE100 Simplified Technical English, written up for authors in
`catalog/recipes/default/skills/harnessed-catalog/injected-content-style.md`. Keep the two in step:
the thresholds here are quoted in that file's table.

DELIBERATELY NOT a build gate. `validate_no_raw_npm` and the pin check raise on the first offence
because a raw `npx` is unambiguously wrong. Prose quality is a gradient, so this reports every
finding at once and is invoked on demand (`harnessed-tools lint-prose`), never from assemble().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --- What counts as prose -------------------------------------------------------------------------
# Everything below is measured on PROSE only. Code fences, tables, headings, list markers, and link
# targets are syntax: their word counts are meaningless and their "sentences" are not sentences.
# Measuring them was the first thing that made an early version of this lint useless — a field table
# in recipe-fields.md scored worse than any paragraph in the repo.
_CODE_MARKER = "CODE"
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
# A line that is structure rather than a sentence: heading, table row, blockquote, rule, list bullet.
_STRUCTURE_LINE_RE = re.compile(r"^\s*(#|\||>|-{3,}|={3,})")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")

# --- Checks ---------------------------------------------------------------------------------------
# Hedges. Each one turns an instruction into a suggestion, and a model treats it as optional. The
# list is closed and literal on purpose: a fuzzy "sounds tentative" check would fire on prose that
# is correctly describing a genuine choice.
_HEDGE_RE = re.compile(
    r"\b(?:should probably|might want to|may want to|try to|make sure to|make sure that"
    r"|be sure to|feel free to|if possible|where possible|as needed|when appropriate"
    r"|it is important to|it's important to|remember to|ideally)\b",
    re.IGNORECASE,
)
# First person. The reader is an agent being instructed; "we" invents a collaborator that is not in
# the room and makes ownership of the action ambiguous.
_FIRST_PERSON_RE = re.compile(r"\b(?:we|we're|we'll|our|ours|let's|let us)\b", re.IGNORECASE)
# Passive voice, approximated by `be`-verb + past participle. An approximation is correct here: this
# is a WARNING, so a false positive costs an author one glance, not a failed build.
_PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", re.IGNORECASE
)
_SOFT_MODAL_RE = re.compile(r"\b(?:can|could|may|might|should|would)\b", re.IGNORECASE)
_HARD_DIRECTIVE_RE = re.compile(r"\b(?:must|never|always|do not|don't|require[sd]?)\b", re.IGNORECASE)

# Thresholds. ASD-STE100 caps a procedural sentence at 20 words and a descriptive one at 25; the
# hard limit here is the descriptive one, since injected content mixes both. MAX_AVG is set from the
# measured repo baseline (rules averaged 10.3 words, skills 15.4) — tight enough to hold the rules
# where they already are, loose enough that one long-but-legitimate sentence does not trip it.
MAX_SENTENCE_WORDS = 25
MAX_AVG_SENTENCE_WORDS = 15.0
MAX_DESCRIPTION_WORDS = 40

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One style violation, anchored to a file and (where meaningful) a 1-indexed line."""

    path: Path
    severity: str
    check: str
    message: str
    line: int | None = None

    def format(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else str(self.path)
        return f"{where}: {self.severity}: [{self.check}] {self.message}"


@dataclass
class FileReport:
    """Per-file metrics plus every finding raised against it."""

    path: Path
    sentences: int = 0
    words: int = 0
    passive: int = 0
    soft_modals: int = 0
    hard_directives: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def avg_sentence_words(self) -> float:
        return self.words / self.sentences if self.sentences else 0.0

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == ERROR)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_body, rest). Frontmatter is absent → ("", text)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return "", text
    return match.group(1), text[match.end():]


def description_of(frontmatter: str) -> str:
    """The `description:` value from YAML frontmatter, with folded continuation lines joined.

    Hand-parsed rather than routed through ruamel because a SKILL.md description is routinely an
    unquoted multi-line scalar containing `:` — valid YAML, but the value is all this needs and a
    parse failure elsewhere in the block must not hide the check.
    """
    lines = frontmatter.splitlines()
    collected: list[str] = []
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        collected.append(line[len("description:"):].strip())
        for cont in lines[i + 1:]:
            # A continuation is indented and is not the next top-level key.
            if not cont.strip() or re.match(r"^\S+:", cont):
                break
            collected.append(cont.strip())
        break
    value = " ".join(collected).strip()
    # A block scalar writes the value on the following lines, leaving only the indicator on the
    # `description:` line. Left in, `>` or `|-` counts as a word and shows up in the excerpt.
    value = re.sub(r"^[>|][+-]?\d*\s*", "", value)
    # A quoted scalar's delimiters are syntax, not content.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def prose_text(body: str) -> str:
    """Strip every construct whose word count is syntax rather than prose."""
    body = _FENCE_RE.sub(" ", body)
    body = _INLINE_CODE_RE.sub(f" {_CODE_MARKER} ", body)
    body = _LINK_RE.sub(r"\1", body)
    kept: list[str] = []
    for line in body.splitlines():
        if _STRUCTURE_LINE_RE.match(line):
            continue
        if _LIST_MARKER_RE.match(line):
            # A bullet is its own unit even without terminal punctuation. Without this break,
            # sentences_of() runs consecutive bullets together and reports one 26-word "sentence"
            # made of four short ones — a false positive that survived until real content hit it.
            kept.append("")
            kept.append(_LIST_MARKER_RE.sub("", line))
            continue
        kept.append(line)
    return "\n".join(kept)


def sentences_of(text: str) -> list[str]:
    """Split prose into sentences, dropping fragments too short to carry an instruction.

    An abbreviation guard is deliberately omitted: `e.g.` and `i.e.` would over-split, but both
    produce SHORT fragments, which the 3-word floor discards. Adding a guard would trade a harmless
    dropped fragment for a genuinely wrong word count.
    """
    # Terminal punctuation is often followed by a CLOSING delimiter before the space — `*emphasis.*`,
    # a quotation, a parenthetical. Without allowing those, the split misses and two sentences are
    # reported as one over-long one.
    parts = re.split(r"(?<=[.!?])[*_\"')\]]*\s+|\n{2,}", text)
    return [p.strip() for p in parts if len(words_of(p)) > 2 and not _is_code_list(p)]


def words_of(text: str) -> list[str]:
    """Word tokens, excluding punctuation-only ones.

    Substituting an inline code span for ` CODE ` detaches the comma that followed it, so a naive
    `.split()` counted a thirteen-filename list as twenty-nine words — twelve of them bare commas.
    Every count in this module goes through here so the inflation cannot come back in one place.
    """
    return [w for w in text.split() if any(ch.isalnum() for ch in w)]


def _is_code_list(sentence: str) -> bool:
    """True when code spans are most of the words — an enumeration of files/flags, not prose.

    `- Read root config files: `package.json`, `Cargo.toml`, …` is fourteen filenames and four
    words. Counting it as an 18-word sentence and demanding it be split produces a finding no
    author can act on, so length is measured only where there is prose to measure.
    """
    words = words_of(sentence)
    if not words:
        return False
    return sum(1 for w in words if _CODE_MARKER in w) * 2 > len(words)


def lint_text(path: Path, text: str) -> FileReport:
    """Score one markdown document and raise every finding it earns."""
    frontmatter, body = split_frontmatter(text)
    report = FileReport(path=path)

    description = description_of(frontmatter)
    if description:
        count = len(words_of(description))
        if count > MAX_DESCRIPTION_WORDS:
            report.findings.append(Finding(
                path, ERROR, "description-length",
                f"description is {count} words (max {MAX_DESCRIPTION_WORDS}). "
                "It is resident every session — name the triggers, not the contents.",
                line=1,
            ))

    prose = prose_text(body)
    sentences = sentences_of(prose)
    report.sentences = len(sentences)
    report.words = sum(len(words_of(s)) for s in sentences)
    report.passive = len(_PASSIVE_RE.findall(prose))
    report.soft_modals = len(_SOFT_MODAL_RE.findall(prose))
    report.hard_directives = len(_HARD_DIRECTIVE_RE.findall(prose))

    # Line numbers are resolved against the ORIGINAL text so an author can jump straight to the
    # offending line; prose_text() has already discarded structure, so its own offsets are useless.
    for sentence in sentences:
        count = len(words_of(sentence))
        if count > MAX_SENTENCE_WORDS:
            report.findings.append(Finding(
                path, ERROR, "sentence-length",
                f"{count}-word sentence (max {MAX_SENTENCE_WORDS}): "
                f"{_excerpt(sentence)}",
                line=_line_of(text, sentence),
            ))

    for match in _HEDGE_RE.finditer(prose):
        report.findings.append(Finding(
            path, ERROR, "hedge",
            f"hedge {match.group(0)!r} — state the requirement as must/never/do not.",
            line=_line_of(text, match.group(0)),
        ))

    for match in _FIRST_PERSON_RE.finditer(prose):
        report.findings.append(Finding(
            path, ERROR, "first-person",
            f"first person {match.group(0)!r} — address the agent, or drop the subject.",
            line=_line_of(text, match.group(0)),
        ))

    if report.sentences and report.avg_sentence_words > MAX_AVG_SENTENCE_WORDS:
        report.findings.append(Finding(
            path, WARNING, "avg-sentence-length",
            f"average sentence is {report.avg_sentence_words:.1f} words "
            f"(target {MAX_AVG_SENTENCE_WORDS:.0f}). Split the long ones.",
        ))

    if report.passive:
        report.findings.append(Finding(
            path, WARNING, "passive-voice",
            f"{report.passive} passive construction(s) — name the actor.",
        ))

    if report.soft_modals > report.hard_directives:
        report.findings.append(Finding(
            path, WARNING, "soft-modals",
            f"{report.soft_modals} soft modal(s) vs {report.hard_directives} hard directive(s) — "
            "an instruction phrased as a possibility reads as optional.",
        ))

    return report


def _excerpt(sentence: str, limit: int = 60) -> str:
    flat = " ".join(sentence.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _line_of(text: str, needle: str) -> int | None:
    """1-indexed line of `needle`'s first token run in the original text; None if not locatable."""
    head = " ".join(needle.split()[:4])
    if not head:
        return None
    index = text.find(head)
    if index < 0:
        # prose_text() rewrote inline code to CODE, so the exact run may not survive; fall back to
        # the first distinctive word rather than reporting a wrong line.
        first = needle.split()[0]
        index = text.find(first)
        if index < 0:
            return None
    return text.count("\n", 0, index) + 1


# Only these two filenames are injected content. A README next to them documents the recipe for a
# human and is explicitly out of scope — linting it would flood the report with findings about
# writing nobody's model ever reads.
LINTED_NAMES = ("RULE.md", "SKILL.md")


def collect_paths(targets: list[Path]) -> list[Path]:
    """Expand each target: a file is taken as-is, a directory yields its RULE.md/SKILL.md."""
    out: list[Path] = []
    for target in targets:
        if target.is_dir():
            for name in LINTED_NAMES:
                out.extend(sorted(target.rglob(name)))
        elif target.is_file():
            out.append(target)
    # rglob over overlapping targets can repeat a path; keep first-seen order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in out:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def lint_paths(targets: list[Path]) -> list[FileReport]:
    """Lint every RULE.md/SKILL.md reachable from `targets`."""
    reports: list[FileReport] = []
    for path in collect_paths(targets):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        reports.append(lint_text(path, text))
    return reports
