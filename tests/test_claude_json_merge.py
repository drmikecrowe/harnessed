"""GH-594 S1: `merge_claude_json` builds a stack's `.claude.json` from its LIVE file.

Both launch paths used to overwrite the file on every launch, so folder trust, external-import
approval, the API key answer and MCP approvals never persisted. The merge keeps the live file as the
base and lays only the keys harnessed owns over it.
"""

import copy

from hypothesis import given, settings, strategies as st

from harnessed.jsonmerge import merge_claude_json

P = "/work/proj"
NOW = "2026-10-12T00:00:00.000Z"
PROJECT_KEYS = (
    "hasTrustDialogAccepted",
    "hasClaudeMdExternalIncludesApproved",
    "hasClaudeMdExternalIncludesWarningShown",
)
OWNED_TOP = ("hasCompletedOnboarding", "firstStartTime", "numStartups", "oauthAccount", "userID")
HOST_ID = {"oauthAccount": {"emailAddress": "me@example.com"}, "userID": "host-id"}


def _merge(live, host, project: str | None = P, *, isolated_auth=False):
    return merge_claude_json(live, host, project, isolated_auth=isolated_auth, now=NOW)


def test_s1_1_empty_inputs_give_exactly_the_owned_shape():
    assert _merge({}, {}) == {
        "hasCompletedOnboarding": True,
        "firstStartTime": NOW,
        "numStartups": 1,
        "oauthAccount": {},
        "userID": "",
        "projects": {P: {k: True for k in PROJECT_KEYS}},
    }


def test_s1_2_live_answers_survive_and_the_project_gains_its_keys():
    live = {
        "customApiKeyResponses": {"approved": ["abc"], "rejected": ["def"]},
        "projects": {
            P: {"enabledMcpjsonServers": ["srv"]},
            "/other": {"hasTrustDialogAccepted": False},
        },
    }
    out = _merge(copy.deepcopy(live), {})
    assert out["customApiKeyResponses"] == {"approved": ["abc"], "rejected": ["def"]}
    assert out["projects"]["/other"] == {"hasTrustDialogAccepted": False}
    assert out["projects"][P] == {"enabledMcpjsonServers": ["srv"], **{k: True for k in PROJECT_KEYS}}


def test_s1_3_onboarding_is_forced_true():
    assert _merge({"hasCompletedOnboarding": False}, {})["hasCompletedOnboarding"] is True


def test_s1_4_start_counters_keep_live_values():
    out = _merge({"firstStartTime": "2026-01-01T00:00:00.000Z", "numStartups": 7}, {})
    assert out["firstStartTime"] == "2026-01-01T00:00:00.000Z"
    assert out["numStartups"] == 7


def test_s1_5_host_contributes_nothing_but_identity():
    host = {
        "projects": {"/secret": {}},
        "mcpServers": {"leak": {}},
        "customApiKeyResponses": {"approved": ["zzz"]},
        "tipsHistory": {},
    }
    out = _merge({}, host)
    for key in ("mcpServers", "customApiKeyResponses", "tipsHistory"):
        assert key not in out
    assert "/secret" not in out["projects"]


def test_s1_6_shared_identity_comes_from_the_host():
    live = {"oauthAccount": {"emailAddress": "old@example.com"}, "userID": "old-id"}
    out = _merge(live, dict(HOST_ID))
    assert out["oauthAccount"] == {"emailAddress": "me@example.com"}
    assert out["userID"] == "host-id"


def test_s1_7_isolated_with_no_live_identity_gets_empty_placeholders():
    out = _merge({}, dict(HOST_ID), isolated_auth=True)
    assert out["oauthAccount"] == {}
    assert out["userID"] == ""


def test_s1_8_isolated_keeps_the_clients_own_login():
    live = {"oauthAccount": {"emailAddress": "client@example.com"}, "userID": "client-id"}
    out = _merge(copy.deepcopy(live), dict(HOST_ID), isolated_auth=True)
    assert out["oauthAccount"] == {"emailAddress": "client@example.com"}
    assert out["userID"] == "client-id"


def test_s1_9_isolated_scrubs_host_identity_left_by_a_shared_launch():
    out = _merge(copy.deepcopy(HOST_ID), dict(HOST_ID), isolated_auth=True)
    assert out["oauthAccount"] == {}
    assert out["userID"] == ""


def test_s1_10_no_project_leaves_projects_alone():
    assert "projects" not in _merge({}, {}, project=None)
    live = {"projects": {"/other": {"x": 1}}}
    assert _merge(copy.deepcopy(live), {}, project=None)["projects"] == {"/other": {"x": 1}}


def test_s1_11_non_dict_inputs_count_as_empty():
    assert _merge([1, 2], None) == _merge({}, {})
    assert _merge(None, ["x"]) == _merge({}, {})
    # A non-dict `projects`, or a non-dict entry for P, is replaced rather than crashed on.
    assert _merge({"projects": ["bad"]}, {})["projects"] == {P: {k: True for k in PROJECT_KEYS}}
    assert _merge({"projects": {P: "bad"}}, {})["projects"][P] == {k: True for k in PROJECT_KEYS}


_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner, max_size=3),
    max_leaves=10,
)


@settings(max_examples=200)
@given(
    live=st.dictionaries(st.text(max_size=12), _json, max_size=6),
    others=st.dictionaries(st.text(min_size=1, max_size=12).filter(lambda s: s != P), _json, max_size=4),
    host=st.dictionaries(st.text(max_size=12), _json, max_size=6),
    isolated=st.booleans(),
)
def test_s1_12_property_live_keys_survive_and_host_adds_only_identity(live, others, host, isolated):
    live = {**live, "projects": others}
    before = copy.deepcopy(live)
    out = _merge(live, host, isolated_auth=isolated)
    for key, val in before.items():
        if key not in OWNED_TOP and key != "projects":
            assert out[key] == val
    for path, entry in others.items():
        assert out["projects"][path] == entry
    for key in out:
        if key not in before and key not in OWNED_TOP and key != "projects":
            raise AssertionError(f"host leaked {key!r}")
    assert live == before, "the merge must not mutate its input"
