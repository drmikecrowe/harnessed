{
  "clean_claims": [
    "src/harnessed/credmounts.py _stack_from_overlay region: reads the source kind, not the resolved path; I found no defect in it",
    "src/harnessed/catalogsources.py discover_project_catalog and git_top_level: the parents-slice arithmetic is correct for start == top and start below top",
    "src/harnessed/paths.py catalog_sources dedupe: with no new source it returns the old three roots unchanged"
  ],
  "finding": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 4004,
      "severity": "blocking",
      "rule": "none",
      "defect": "host_run, use, container_run, build, list and test call _set_catalog_project, but host_acp calls paths.is_built(stack, harness) at line 4004 with no project directory set. project_dir() is still None there, so no project source is seen and storage_name is unscoped. The set at _launch_host:3228 comes after the check.",
      "trigger": "Build a stack whose closure comes from a trusted project .harnessed/catalog (so its profile is stored under stack-<hash>), then run `harnessed host-acp claude --stack <that stack>` from the project.",
      "consequence": "is_built looks for the unscoped profile and exits with 'has no assembled profile (run: harnessed build ...)' even though the build succeeded. The stack may also fail to resolve, because the project catalog is invisible when the project dir is unset. A flag-scoped stack is unaffected because it reads HARNESSED_CATALOG from the env."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 6456,
      "severity": "advisory",
      "rule": "none",
      "defect": "scan, rescan, stop, rm, context and project-setup never call _set_catalog_project. They use find_in_catalog and _derived_image, which now use storage_name.",
      "trigger": "Run `harnessed scan <project-scoped stack> claude` after building it from a trusted project catalog.",
      "consequence": "The project catalog is not seen. scan reports 'no such stack', or looks up the image under the unscoped name, and the scan targets the wrong image or none. The user must know to cd and pass a flag that these commands lack."
    },
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 774,
      "severity": "advisory",
      "rule": "none",
      "defect": "trusted_paths does an unguarded json.loads(...).get(...). load_registry has the same fault: it indexes the four keys directly and uses ruamel's parser with no handling.",
      "trigger": "Write truncated JSON, or a list instead of an object, to trusted-catalogs.json. Or write a catalogs.yaml entry that lacks `sha`.",
      "consequence": "JSONDecodeError, AttributeError or KeyError propagates as a raw traceback. Because _check_git_clones calls load_registry for every verb except `catalog`, a bad catalogs.yaml breaks every harnessed command, and the repair verb `catalog remove` also reads the registry. A bad trust file breaks every launch from any project that has a .harnessed/catalog."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 953,
      "rule": "none",
      "defect": "`git clone --quiet --no-checkout url tmp` has no `--` before url, and `git rev-parse` in _resolve_ref has none before the ref. A url or ref that starts with '-' is read as a git option, and `ext::` URLs are accepted.",
      "consequence": "`harnessed catalog add -- --upload-pack=<cmd>` runs a command. This needs the user to type it, so it is low severity, but a script that forwards a url from a manifest would be exposed."
    },
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 1040,
      "rule": "none",
      "defect": "_closure collects only the stack's own services and recipes, plus extends parents. A service named by a recipe, or an agent, from a flag or project catalog does not mark the stack scoped.",
      "consequence": "Two projects whose recipes pull different same-named services from their private catalogs share one profile, image and volume. This is the AC-9 collision the scoping exists to prevent."
    },
    {
      "file": "src/harnessed/catalogsources.py",
      "line": 836,
      "rule": "none",
      "defect": "Trust is recorded by path only. It is not tied to content, a commit, or the repository identity.",
      "consequence": "After `catalog trust`, a later `git pull`, or a different repository cloned to the same path, runs new catalog code on the host with no prompt."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 7156,
      "rule": "none",
      "defect": "_extract_catalog_flags strips `--catalog` from any argv segment before `--`, including values meant for a harness CLI after `--cli`, for example `--cli auth login`.",
      "consequence": "A harness argument literally named --catalog is swallowed, and the launch fails with 'no such directory'."
    }
  ],
  "coverage": {
    "calls_used": "8/66",
    "hunts_not_reached": [
      "1 (merge-gate argument comparison; I did not open the workflow files or tools/gauntlet-layers.json)",
      "8",
      "10",
      "12 (the tests were not read, only the src diff)"
    ],
    "sites_not_opened": [
      "tests/catalog_env.py:1",
      "tests/test_catalog_git.py:1",
      "tests/test_catalog_scope.py:1",
      "tests/test_catalog_sources.py:1",
      "tests/test_catalog_trust.py:1",
      "src/harnessed/launcher.py:5611 (context command)",
      "src/harnessed/launcher.py:5792 (stop command)"
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
      "src/harnessed/volumes.py"
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
      "tests/catalog_env.py",
      "tests/test_catalog_git.py",
      "tests/test_catalog_scope.py",
      "tests/test_catalog_sources.py",
      "tests/test_catalog_trust.py"
    ]
  }
}
