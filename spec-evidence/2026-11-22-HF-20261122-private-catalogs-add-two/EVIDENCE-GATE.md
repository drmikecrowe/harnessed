# Gate 2, evidence

verdict: ready
story: HF-20261122-private-catalogs-add-two
process: spec-evidence 1.7.2-local-2026-11-19
model: claude-sonnet-5-5
tokens: 320945/5151
record: work/evidence-record.json
graded: 2026-11-22T18:27:34.026Z

## Reasons

none

## Evidence hashes

- AC-1 proven d0afa8927e3328535e987260738c9858e5a24a5c796bcf334b4825960f005a74
- AC-2 proven 81ce1c0e50c1b0fd9460dbd7658f30cb07bd960e4024dbb7438f1708f887ece3
- AC-3 proven 6b4c5a4929711af14fea3e1a5258fe02a59e240dbe0dc08016efd80dc9349c48
- AC-4 proven d075dc1e525805a1efbdf994856d5359bfb84acb30a12bb5594165b2a838f981
- AC-5 proven 075909bc30e73d36957ab3df3e71586bd036682ac281911c2ddfdf62501d366b
- AC-6 proven fc7148bb7b5ec3ea67b922531c34272eb8e0f00a1c502cd48eeb81f4bd08e048
- AC-7 proven 6b2195555a860d89062e31cddd2b784a3c0681f358a984090f23d6348b57924f
- AC-8 proven e920c884e0bfe8d728f55aa9e797ae4067c76366a8d9873a9d74a2aaba8c418d
- AC-9 proven 426ee50eb433e55005d647e95ceb7151eb7e6399f52371af87d249453a3202e7
- AC-10 proven 404dc4f7d1f3194d0fb9f588a8ffc6fe6009fb8cace08e0739853c83e3964660
- AC-11 proven 58b5b3de7a6469944fc749aad237a449b84c048b7614b64594ff010f1c19925f
- AC-12 proven 2c943d889682bd535a631f1e1ebc4f82101e4e107944abf5b029b392b39b6176
- AC-13 proven 107c71686afad9b28b79c6be4706d209f430fe38900b1b5e38d5f3638094a1a6

## Record

```json
{"gaps":["No criterion names an @SC tag, so grading used the report's own Spec to Test mapping, where scenarios are S-ids (S1.1 to S13.3) and each AC has condition, boundary and negative rows.","The report records the tests layer as FAILED on 3 environment-only tests (also failing on origin/main), coverage as SUBSTITUTED, and live/live-docker as not yet run. I graded only whether each AC clause has a real test, not whether the tests pass.","AC-9 is proven through assemble.assemble and the storage-name functions, not through the `harnessed build` command. AC-8 is proven at credmounts._stack_from_overlay and _trusted_ssh_keys, plus a source-text check of container_run. No test drives a real container-run to its mounts.","S5.1 and S11.4 prove 'no network call' by replacing catalogsources._git with a function that raises. A network call made some other way would not be caught.","AC-13's next-launch warning is checked through `harnessed list --project`, not a launch verb."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1/S1.2 test_s1_1_flag_before_the_command and test_s1_2_flag_after_the_command; S1.3 test_s1_3_first_flag_wins (asserts the first folder's path wins); S1.4 test_s1_4_missing_dir_stops_before_any_build (asserts non-zero exit, error naming the dir, app never called, no profiles root). I read all four tests in tests/test_catalog_sources.py."},{"ac":"AC-2","status":"proven","evidence":"S2.1 test_s2_1_found_from_a_subfolder; S2.2 test_s2_2_nearest_wins (the parent catalog is not among the roots); S2.3 test_s2_3_stops_at_the_git_top_level; S2.4 no git top level; S2.5 test_s2_5_untrusted_is_ignored_with_one_warning (exactly one warning naming the path and 'harnessed catalog trust'); S2.6 and S2.8. I read them in tests/test_catalog_sources.py."},{"ac":"AC-3","status":"proven","evidence":"S3.1 test_s3_1_records_and_silences_the_warning; S3.3 test_s3_3_trust_belongs_to_the_path (a renamed folder is untrusted); S3.4 test_s3_4_nothing_to_trust (non-zero exit, error, record bytes unchanged). I read them in tests/test_catalog_trust.py."},{"ac":"AC-4","status":"proven","evidence":"S4.1 test_s4_1_clones_and_locks (clone under clones/harnessed-catalog, registry item with name, url, ref, sha equal to HEAD); S4.2 test_s4_2_no_ref_locks_the_default_branch (default branch 'trunk' and its SHA); S4.4 test_s4_4_a_failed_clone_leaves_nothing and test_s4_4_a_bad_ref_leaves_nothing (non-zero exit, no registry, no clone dir). I read them in tests/test_catalog_git.py."},{"ac":"AC-5","status":"proven","evidence":"S5.1 test_s5_1_resolves_from_the_clone_without_git (git replaced by a function that raises); S5.2 test_s5_2_a_moved_remote_changes_nothing (new remote commits, lock and clone unchanged); S5.3 test_s5_3_a_missing_clone_stops_a_build (stderr names the catalog and 'harnessed catalog update', non-zero exit, app not called). I read them in tests/test_catalog_git.py."},{"ac":"AC-6","status":"proven","evidence":"S6.1 test_s6_1_moves_the_lock (output holds old and new SHA, lock and clone move); S6.3 test_s6_3_a_full_sha_does_not_change ('did not change'); S6.5 test_s6_5_a_failed_fetch_changes_nothing (non-zero exit, registry bytes and clone HEAD unchanged). I read them in tests/test_catalog_git.py."},{"ac":"AC-7","status":"proven","evidence":"S7.1 test_s7_1_each_source_in_turn (removes each copy of `time` in order across flag, project, overlay, two git catalogs and shipped) and test_kinds_in_source_order; S7.2 test_s7_2_first_registered_git_catalog_wins; S7.3 test_s7_3_generated_never_wins (generated root is last). I read them in tests/test_catalog_sources.py."},{"ac":"AC-8","status":"proven","evidence":"S8.1 test_s8_1_new_sources_drop_ssh_keys (flag, project (trusted) and git; asserts the 'ignoring ssh_keys' note and an empty key list); S8.2 test_s8_2_the_overlay_keeps_them; S8.3 and S8.4 (a symlinked flag folder and a trusted project stack are not the overlay). I read them in tests/test_catalog_scope.py."},{"ac":"AC-9","status":"proven","evidence":"S9.1 test_s9_1_assemble_writes_a_scoped_profile (plain profile untouched); S9.2 test_s9_2_two_projects_get_separate_state (nine state names differ per project); S9.5 test_s9_5_another_project_reads_the_plain_profile. I read them in tests/test_catalog_scope.py."},{"ac":"AC-10","status":"proven","evidence":"S10.1 test_s10_1_one_warning_names_both_paths (one warning, both paths); S10.3 test_s10_3_no_warning_when_nothing_is_hidden; S10.5 test_s10_5_the_warning_never_stops_the_load; S10.2 covers stacks. I read them in tests/test_catalog_sources.py."},{"ac":"AC-11","status":"proven","evidence":"S11.1 test_s11_1_six_rows_in_source_order (kinds in order, git row has name, ref and SHA, project row says 'trusted'); S11.2 untrusted project row; S11.3 test_s11_3_the_baseline (overlay and shipped only); S11.4 test_s11_4_list_reads_only (git replaced by a function that raises, file snapshot unchanged). I read them in tests/test_catalog_git.py."},{"ac":"AC-12","status":"proven","evidence":"S12.1 test_s12_1_drops_one_and_keeps_the_order (entry and clone removed, others keep order and HEAD); S12.3 test_s12_3_an_unknown_name (non-zero exit, registry unchanged, clone still present). I read them in tests/test_catalog_git.py."},{"ac":"AC-13","status":"proven","evidence":"S13.1 test_s13_1_removes_one_path (the trust record holds only the other path, and `list` shows the trust warning again); S13.2 test_s13_2_others_stay_trusted; S13.3 test_s13_3_untrusting_an_untrusted_catalog_fails (non-zero exit, error, record bytes unchanged). I read them in tests/test_catalog_trust.py."}]}
```
