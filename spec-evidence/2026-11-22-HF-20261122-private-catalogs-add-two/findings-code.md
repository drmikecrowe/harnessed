{
  "clean_claims": [
    "src/harnessed/catalogsources.py: read whole. The project discovery slice, the URL and ref option guard, the atomic writes and the clone-into-temp-sibling flow hold up. Only the findings and hunches below apply.",
    "Merge-gate match: lint.yml runs `ruff check src tests tools` and `pyright --pythonpath <uv python>`, test.yml runs `uv run --extra dev pytest`. All three equal the gauntlet-layers.json argument lists. The layer set is not narrower than the gate.",
    "src/harnessed/assemble.py, volumes.py, setupenv.py, plugin.py, layout.py, schema.py (_resolve_parent_stack_dir hunk), credmounts.py and catalogseed.py (_writable_roots): changed lines read, no defect found.",
    "tests/catalog_env.py: hermetic. Every root is under tmp_path and the git helper sets its own env."
  ],
  "finding": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 5805,
      "severity": "advisory",
      "rule": "none",
      "defect": "`stop` and `rm` match instances with `-<stack>-<8hex>$` on the plain stack name, but instance_name now embeds storage_name(stack), which appends `-<8hex>` for a scoped stack. The aoe.forget_stack call at line 5833 also receives the plain name.",
      "trigger": "`harnessed --catalog ./dir container-run claude --stack foo` where foo loads something from ./dir. The container is named harnessed-claude-foo-ab12cd34-<hash>. Then run `harnessed stop foo` or `harnessed rm foo`.",
      "consequence": "The regex does not match, so the output is 'No running instances' and the scoped container is neither stopped nor removed. SPEC line 194 says a `--catalog` folder still reaches these verbs, but neither verb calls storage_name, so the claim does not hold for them. The stale aoe rows are not forgotten either."
    },
    {
      "file": "tests/test_catalog_sources.py",
      "line": 80,
      "severity": "advisory",
      "rule": "none",
      "defect": "No test drives `_check_git_clones` (S5.3: a missing clone refuses to start, and `catalog` and help are exempt) or the output rows of `catalog list`. A grep of tests/test_catalog_*.py for both names found nothing.",
      "trigger": "A change that drops the exemption for `catalog`, or makes `_check_git_clones` hit `--help`, or reorders the rows in `catalog_list`.",
      "consequence": "A user with a missing clone could be unable to run `harnessed catalog update`, and the suite stays green."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 391,
      "rule": "none",
      "defect": "`remove` writes the registry first, then runs rmtree with ignore_errors=True.",
      "consequence": "If the clone cannot be deleted, the failure is invisible. The registry no longer lists it, `remove` says 'not registered', and `add` refuses with 'already exists and is not registered; remove it first'. The CLI offers no way out of that loop."
    },
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 412,
      "rule": "none",
      "defect": "`_inside` resolves each closure directory, so a recipe or service entry that is a symlink out of the folder source counts as outside the folder. The stack is then left unscoped.",
      "consequence": "Two projects whose `--catalog` folders symlink same-named recipes to different targets would share one profile, image and volume. This is the cross-project mixing AC-9 exists to prevent."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 1413,
      "rule": "none",
      "defect": "`_check_git_clones` exempts only the `catalog` verb. Every other verb is blocked when any registered clone is missing, including verbs that never read the catalog, such as `harnessed update`/`upgrade` and `volume-gc`.",
      "consequence": "A missing clone blocks unrelated maintenance commands until the user runs `harnessed catalog update`."
    }
  ],
  "coverage": {
    "calls_used": "14/66",
    "hunts_not_reached": [
      "9 (flags and config keys the diff names; not checked against the pinned versions)",
      "10 (Documentation section; the AGENTS.md, ARCHITECTURE.md and SKILL.md hunks were not read)",
      "8 (no EVIDENCE report in the diff)"
    ],
    "sites_not_opened": [
      "tests/test_catalog_trust.py (diff lines 2796 onward)",
      "tests/test_catalog_git.py",
      "tests/test_catalog_scope.py (only test names grepped, bodies not read)",
      "src/harnessed/launcher.py:3228 (the `path` type passed to `_launch_host`)",
      "src/harnessed/aoe.py forget_stack",
      "the hostname length cap against the suffixed instance_name",
      "the .github/workflows/live.yml trigger table against the changed paths.py and launcher.py"
    ],
    "files_reviewed": [
      "src/harnessed/assemble.py",
      "src/harnessed/catalogseed.py",
      "src/harnessed/catalogsources.py",
      "src/harnessed/credmounts.py",
      "src/harnessed/launcher.py",
      "src/harnessed/layout.py",
      "src/harnessed/paths.py",
      "src/harnessed/plugin.py",
      "src/harnessed/schema.py",
      "src/harnessed/setupenv.py",
      "src/harnessed/volumes.py",
      "tests/catalog_env.py",
      "tests/test_catalog_sources.py"
    ],
    "files_not_reviewed": [
      "AGENTS.md",
      "ARCHITECTURE.md",
      "catalog/recipes/default/skills/harnessed-catalog/SKILL.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/SPEC.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/STORY.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/agent-decisions.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/context-pack.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/decisions.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/label",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/spec-gate.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/spec-intent.md",
      "spec-evidence/2026-11-22-HF-20261122-private-catalogs-add-two/story-gate.md",
      "tests/test_catalog_git.py",
      "tests/test_catalog_scope.py",
      "tests/test_catalog_trust.py"
    ]
  }
}
