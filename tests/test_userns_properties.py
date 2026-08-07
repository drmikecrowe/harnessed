"""Property-based cover for the two pure functions bd harnessed-rv2.1 introduced.

Both are small, both are load-bearing, and both are the kind of thing example-based tests cover in
the shapes their author happened to imagine. The example tests live in `test_userns_mapping.py` and
`test_persist_allowlist.py`; these assert the invariants over inputs nobody enumerated.

Worth fuzzing specifically because each has a failure mode that is silent rather than loud:

  * `_without_userns` dropping too much would strip a bind mount, and the container would come up
    missing a directory rather than erroring;
  * `pod_host_uid` returning the wrong number makes `guard_ownership` either wave through an
    unwritable dir (the CI failure) or refuse a perfectly good one.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given, strategies as st

from harnessed import launcher, paths

# Argv fragments as they really appear: flags, `-v host:ctr` pairs, paths, and userns in every
# spelling the tree has ever emitted.
_USERNS = st.sampled_from([
    "--userns=keep-id",
    "--userns=keep-id:uid=1000,gid=1000",
    "--userns=keep-id:uid=1001,gid=1001",
    "--userns=auto",
    "--userns=host",
])
_OTHER = st.sampled_from(["-v", "a:b", "--rm", "run", "--entrypoint", "sh", "-c", "true", "--user"])
_ARG = st.one_of(_USERNS, _OTHER)


class TestWithoutUserns:
    @given(st.lists(_ARG, max_size=25))
    def test_it_removes_every_userns_and_nothing_else(self, args):
        kept = launcher._without_userns(args)
        assert not any(a.startswith("--userns") for a in kept)
        assert kept == [a for a in args if not a.startswith("--userns")]

    @given(st.lists(_OTHER, max_size=25))
    def test_it_is_the_identity_when_there_is_no_userns(self, args):
        """A host launch's args must survive untouched — this is the "drops too much" guard."""
        assert launcher._without_userns(args) == args

    @given(st.lists(_ARG, max_size=25))
    def test_it_is_idempotent(self, args):
        once = launcher._without_userns(args)
        assert launcher._without_userns(once) == once


class TestPodHostUid:
    """`monkeypatch` is used as a CONTEXT MANAGER, not as a fixture. hypothesis rejects the fixture
    form outright: a function-scoped fixture is not reset between generated inputs, so the patch
    would leak from one example into the next and the property would be testing whatever the last
    example left behind. Suppressing that health check would have been the wrong fix."""

    @given(st.integers(min_value=0, max_value=65535))
    def test_only_a_mapping_onto_the_image_uid_makes_the_pod_the_caller(self, mapped):
        """The single invariant the guard rests on: the pod writes as the CALLER exactly when the
        mapping names the image's uid, and as the IMAGE's uid in every other case — including the
        bare `keep-id` that caused the CI failure."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(paths, "USERNS_ARG", f"--userns=keep-id:uid={mapped},gid={mapped}")
            expected = os.getuid() if mapped == paths.CONTAINER_UID else paths.CONTAINER_UID
            assert paths.pod_host_uid() == expected

    @given(st.text(max_size=40).filter(lambda s: "uid=" not in s))
    def test_a_mapping_that_names_no_uid_falls_back_to_the_image_uid(self, tail):
        """Fail SAFE: an unrecognized mapping must resolve to the image uid, which makes
        `guard_ownership` fire, not to the caller, which would make it wave the launch through."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(paths, "USERNS_ARG", f"--userns=keep-id{tail}")
            assert paths.pod_host_uid() == paths.CONTAINER_UID
