"""Tests for the injected-content prose lint (`harnessed-tools lint-prose`).

Each false-positive test below corresponds to a bug the lint actually had when it was first run
against the real catalog. They are the regression surface: the checks themselves are simple, but
what counts as "a sentence" in markdown is not, and every one of these shapes broke it.
"""
from pathlib import Path

import pytest

from harnessed import prose
from harnessed.cli import main


def _lint(body: str, frontmatter: str = "") -> prose.FileReport:
    text = f"---\n{frontmatter}\n---\n{body}" if frontmatter else body
    return prose.lint_text(Path("RULE.md"), text)


def _checks(report: prose.FileReport, severity: str | None = None) -> list[str]:
    return [f.check for f in report.findings if severity is None or f.severity == severity]


# --- sentence length ------------------------------------------------------------------------------

def test_long_sentence_is_an_error():
    body = "Alpha " * 30 + "end."
    assert "sentence-length" in _checks(_lint(body), prose.ERROR)


def test_short_sentences_are_clean():
    assert _lint("Run the script. Commit the result. Push the branch.").findings == []


def test_sentence_ending_inside_emphasis_is_split():
    """`*use rg, never find.*` ends a sentence — the `*` sits between the period and the space."""
    body = ("If a subagent prompt will search a tree, say so explicitly: *use rg, never find.* "
            "Left unsaid, subagents are the single largest source of denied calls here.")
    assert "sentence-length" not in _checks(_lint(body))


def test_consecutive_bullets_are_separate_sentences():
    """Four short bullets must not be measured as one long sentence."""
    body = (
        "Same shape, same problem:\n\n"
        "- as I said earlier\n"
        "- note that my change was correct\n"
        "- that file was already like that\n"
        "- any re-listing of evidence that you did your part right\n"
    )
    assert "sentence-length" not in _checks(_lint(body))


def test_wrapped_paragraph_is_one_sentence():
    """A hard-wrapped paragraph must NOT be split at its single newlines."""
    report = _lint("Alpha beta gamma delta epsilon zeta\neta theta iota kappa lambda mu nu.")
    assert report.sentences == 1


# --- code is syntax, not prose --------------------------------------------------------------------

def test_code_fence_is_not_measured():
    fence = "```bash\n" + "some very long shell command line here\n" * 10 + "```"
    assert _lint(f"Run it.\n\n{fence}\n").findings == []


def test_code_dominated_enumeration_is_skipped():
    """A list of filenames is data, not a sentence to split."""
    body = "- Read root config files: " + ", ".join(f"`file{i}.toml`" for i in range(14))
    assert "sentence-length" not in _checks(_lint(body))


def test_detached_punctuation_does_not_inflate_the_word_count():
    """Inline code becomes ` CODE `, which detaches the following comma into its own token."""
    assert prose.words_of(prose.prose_text("`a`, `b`, `c`")) == ["CODE", "CODE", "CODE"]


def test_table_rows_are_not_measured():
    body = "| a very long table cell with many words in it | another one entirely |\n" * 5
    assert _lint(body).sentences == 0


# --- hedges, first person -------------------------------------------------------------------------

@pytest.mark.parametrize("hedge", ["try to", "make sure to", "feel free to", "ideally", "if possible"])
def test_hedges_are_errors(hedge):
    assert "hedge" in _checks(_lint(f"You should {hedge} run the tests now."), prose.ERROR)


def test_first_person_is_an_error():
    assert "first-person" in _checks(_lint("We author under the catalog."), prose.ERROR)


def test_imperative_prose_raises_nothing():
    assert _lint("Author under the catalog. Never commit to main.").findings == []


# --- description --------------------------------------------------------------------------------

def test_over_long_description_is_an_error():
    fm = "name: x\ndescription: " + "word " * 50
    assert "description-length" in _checks(_lint("Body.", fm), prose.ERROR)


def test_short_description_is_clean():
    fm = "name: x\ndescription: Deploy Workers. Use before any wrangler command."
    assert _lint("Body.", fm).findings == []


def test_folded_scalar_indicator_is_not_counted_as_content():
    assert prose.description_of("description: >\n  Deploy Workers now.") == "Deploy Workers now."


def test_quoted_description_loses_its_delimiters():
    assert prose.description_of('description: "Deploy Workers now."') == "Deploy Workers now."


def test_multiline_description_stops_at_the_next_key():
    fm = "name: x\ndescription: >\n  Deploy Workers.\n  Use it early.\nlicense: MIT"
    assert prose.description_of(fm) == "Deploy Workers. Use it early."


# --- warnings are not errors ----------------------------------------------------------------------

def test_passive_voice_warns_but_does_not_error():
    report = _lint("The lint is invoked by the build. The result is printed by the console.")
    assert "passive-voice" in _checks(report, prose.WARNING)
    assert report.errors == 0


def test_soft_modals_warn_when_they_outnumber_hard_directives():
    report = _lint("You can do this. You might do that. You could also do the other.")
    assert "soft-modals" in _checks(report, prose.WARNING)
    assert report.errors == 0


# --- collection -----------------------------------------------------------------------------------

def test_collect_paths_finds_only_rule_and_skill_files(tmp_path):
    (tmp_path / "rules" / "r").mkdir(parents=True)
    (tmp_path / "rules" / "r" / "RULE.md").write_text("Run it.")
    (tmp_path / "skills" / "s").mkdir(parents=True)
    (tmp_path / "skills" / "s" / "SKILL.md").write_text("Run it.")
    (tmp_path / "README.md").write_text("A readme nobody's model reads.")
    names = {p.name for p in prose.collect_paths([tmp_path])}
    assert names == {"RULE.md", "SKILL.md"}


def test_explicit_file_target_is_linted_even_if_not_a_rule_or_skill(tmp_path):
    path = tmp_path / "NOTES.md"
    path.write_text("Run it.")
    assert prose.collect_paths([path]) == [path]


def test_overlapping_targets_do_not_duplicate(tmp_path):
    (tmp_path / "rules" / "r").mkdir(parents=True)
    rule = tmp_path / "rules" / "r" / "RULE.md"
    rule.write_text("Run it.")
    assert prose.collect_paths([tmp_path, tmp_path / "rules"]) == [rule]


# --- the shipped catalog holds the standard -------------------------------------------------------

def test_shipped_catalog_has_no_prose_errors():
    """The catalog IS the reference implementation of the house style. Keep it at zero."""
    catalog = Path(__file__).resolve().parents[1] / "catalog" / "recipes"
    reports = prose.lint_paths([catalog])
    assert reports, "no injected content found — the lint would pass vacuously"
    offenders = [f.format() for r in reports for f in r.findings if f.severity == prose.ERROR]
    assert not offenders, "\n".join(offenders)


# --- CLI ------------------------------------------------------------------------------------------

def test_cli_exits_nonzero_on_an_error(tmp_path):
    (tmp_path / "RULE.md").write_text("Alpha " * 30 + "end.")
    assert main(["lint-prose", str(tmp_path / "RULE.md")]) == 1


def test_cli_warn_only_exits_zero_on_an_error(tmp_path):
    (tmp_path / "RULE.md").write_text("Alpha " * 30 + "end.")
    assert main(["lint-prose", str(tmp_path / "RULE.md"), "--warn-only"]) == 0


def test_cli_exits_zero_on_clean_content(tmp_path):
    (tmp_path / "RULE.md").write_text("Run the script. Commit the result.")
    assert main(["lint-prose", str(tmp_path / "RULE.md")]) == 0


def test_cli_summary_renders(tmp_path, capsys):
    (tmp_path / "RULE.md").write_text("Run the script. Commit the result.")
    assert main(["lint-prose", str(tmp_path / "RULE.md"), "--summary"]) == 0
    assert "prose metrics" in capsys.readouterr().out


def test_cli_reports_a_miss_rather_than_passing_vacuously(tmp_path):
    """An empty target must not read as 'clean' — that would hide a wrong path in CI."""
    assert main(["lint-prose", str(tmp_path)]) == 1
