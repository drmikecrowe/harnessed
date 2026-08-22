"""Parser-only contract tests for two external binaries whose output cannot be captured in CI.

# PARSER-ONLY COVERAGE: these tests assert that parsers in credmounts.py and capability.py
# correctly parse the output formats emitted by `lsusb` and `claude -p --output-format json`.
# They do NOT verify that those binaries are present, authenticated, or still emit these formats
# at runtime. They run in the standard hermetic suite — no HARNESSED_PODMAN gate.

B1 — _yubikey_device_args() (credmounts.py): tests run against a committed fixture for the
     lsusb output format. The fixture is SYNTHETIC (see provenance header in the file) because
     real YubiKey hardware is not available in CI. Tests remain useful for parser regression
     coverage; fixture must be replaced with a real capture when hardware is available.

B2 — _names_from_llm_json() (capability.py): tests for the JSON envelope format emitted by
     `claude -p --output-format json`. The fixture file (tests/fixtures/claude_mcp_list_output.json)
     must be captured by Mike on a machine with an authenticated claude binary and hatago hub.
     Fixture-dependent test skips with a LOUD reason when the file is absent.
     Parser-only scenarios (bare JSON array, prose wrapping, etc.) run unconditionally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from harnessed import credmounts
from harnessed.credmounts import _yubikey_device_args
from harnessed.capability import _names_from_llm_json

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_LSUSB_FIXTURE = _FIXTURES_DIR / "lsusb_with_yubikey.txt"
_CLAUDE_FIXTURE = _FIXTURES_DIR / "claude_mcp_list_output.json"


# ---------------------------------------------------------------------------
# B1 — lsusb YubiKey line parsing (credmounts._yubikey_device_args)
# PARSER-ONLY COVERAGE: tests assert that _yubikey_device_args() parses the lsusb output
# format correctly against a committed fixture. They do NOT verify that the lsusb binary still
# produces this format, or that a CI runner with a YubiKey attached would be detected.
# ---------------------------------------------------------------------------

class TestYubikeyDeviceArgs:
    """B1: Parser correctness for lsusb output → --device argument construction.

    Uses monkeypatch to inject the fixture content as subprocess output and to stub Path.exists.
    No subprocess or filesystem side effect escapes the test.
    """

    def _fixture_content(self) -> str:
        """Load the lsusb fixture, stripping provenance comment lines.

        Real lsusb never emits comment lines; the fixture file uses '#' headers for provenance
        metadata only. The mock must inject what lsusb actually produces, not the full file.
        Stripping here also prevents the parser matching '#  YubiKey model: Yubico.com ...'
        — a line that contains 'yubico' and would be parsed as a device line with wrong parts.
        """
        if not _LSUSB_FIXTURE.is_file():
            pytest.skip(
                f"lsusb fixture missing: {_LSUSB_FIXTURE} — "
                "capture real `lsusb` output with a YubiKey attached (preferred) or "
                "verify the SYNTHETIC fixture was committed."
            )
        return "\n".join(
            line for line in _LSUSB_FIXTURE.read_text().splitlines()
            if not line.strip().startswith("#")
        )

    def _make_completed(self, stdout: str, returncode: int = 0):
        proc = MagicMock()
        proc.stdout = stdout
        proc.returncode = returncode
        return proc

    def test_yubikey_line_is_parsed_to_device_argument(self, monkeypatch):
        """Real lsusb fixture line → ['--device', '/dev/bus/usb/003/004'].

        The fixture line:
          Bus 003 Device 004: ID 1050:0407 Yubico.com YubiKey OTP+U2F
        Parser extracts bus=003, dev=004 (stripped of trailing ':'), builds the device path,
        and returns it when Path.exists reports the path present.
        """
        content = self._fixture_content()
        monkeypatch.setattr(credmounts, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            credmounts.subprocess, "run",
            lambda *a, **kw: self._make_completed(content),
        )
        monkeypatch.setattr(credmounts.Path, "exists", lambda self: True)
        result = _yubikey_device_args()
        assert result == ["--device", "/dev/bus/usb/003/004"], (
            f"Expected ['--device', '/dev/bus/usb/003/004']; got {result!r}. "
            "Parser must extract bus=003 and device=004 from the YubiKey lsusb line."
        )

    def test_no_yubikey_line_yields_empty_list(self, monkeypatch):
        """lsusb output with no Yubico or 'id 1050:' lines → []."""
        non_yubikey = (
            "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
            "Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub\n"
        )
        monkeypatch.setattr(credmounts, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            credmounts.subprocess, "run",
            lambda *a, **kw: self._make_completed(non_yubikey),
        )
        result = _yubikey_device_args()
        assert result == [], f"Expected []; got {result!r}"

    def test_hostile_input_too_few_parts_yields_empty_list(self, monkeypatch):
        """A line matching 'id 1050:' but with only 3 whitespace-split parts → [].

        The guard `if len(parts) >= 4` prevents an IndexError when the line is malformed.
        Input: 'ID 1050: short' → parts=['ID', '1050:', 'short'] (len=3 < 4) → guard fires.
        """
        hostile = "ID 1050: short\n"
        monkeypatch.setattr(credmounts, "_host_os", lambda: "linux")
        monkeypatch.setattr(
            credmounts.subprocess, "run",
            lambda *a, **kw: self._make_completed(hostile),
        )
        result = _yubikey_device_args()
        assert result == [], (
            f"Expected [] for hostile input with < 4 parts; got {result!r}. "
            "The len(parts) >= 4 guard must prevent the IndexError."
        )

    def test_non_linux_host_returns_empty_without_subprocess(self, monkeypatch):
        """Non-Linux host → [] and subprocess.run is never called.

        YubiKey passthrough is Linux-only; macOS uses the gpg-agent socket relay instead.
        """
        called = []

        def _fail_if_called(*a, **kw):
            called.append(a)
            raise AssertionError("subprocess.run must not be called on non-Linux host")

        monkeypatch.setattr(credmounts, "_host_os", lambda: "macos")
        monkeypatch.setattr(credmounts.subprocess, "run", _fail_if_called)
        result = _yubikey_device_args()
        assert result == [], f"Expected [] on non-Linux; got {result!r}"
        assert not called, "subprocess.run was called on non-Linux host"


# ---------------------------------------------------------------------------
# B2 — claude --strict-mcp-config JSON envelope parsing (capability._names_from_llm_json)
# PARSER-ONLY COVERAGE: these tests assert that _names_from_llm_json() correctly parses the
# JSON envelope format emitted by `claude -p --output-format json`. They do NOT verify that
# the claude binary is present, authenticated, or still emits this format at runtime.
# ---------------------------------------------------------------------------

class TestNamesFromLlmJson:
    """B2: Parser correctness for `claude -p --output-format json` envelope → server name set.

    The fixture-dependent test (real captured output) skips LOUDLY when the file is absent.
    All other scenarios run unconditionally — they exercise the parser with synthetic inputs.
    """

    # The capture script pins --mcp-config to exactly one stdio server, so the correct answer is
    # knowable in advance and is written HERE rather than read out of the fixture. Deriving it from
    # the fixture (or from the parser's own output) would make the assertion tautological: a parser
    # that selected the wrong non-empty array would still "match". Keep in sync with _SERVER_NAME
    # in tools/capture-claude-mcp-fixture.sh.
    _EXPECTED_SERVERS: ClassVar[set[str]] = {"time"}

    def test_real_fixture_is_parsed_correctly(self):
        """Real captured fixture → exactly {'time'}.

        Capture with `tools/capture-claude-mcp-fixture.sh` on a machine with an authenticated
        `claude` binary. That script refuses to write a fixture the production parser cannot read
        back as _EXPECTED_SERVERS, so a fixture that exists is one that carries real evidence.

        THIS TEST NEVER CALLS `claude`. It reads a committed file. The billed `claude -p` call
        happens once, by hand, when the fixture is captured — never in CI and never per-run. Do not
        "improve" this by shelling out to claude to refresh the fixture.
        """
        if not _CLAUDE_FIXTURE.is_file():
            pytest.skip(
                f"fixture missing: {_CLAUDE_FIXTURE} — capture it with "
                "`tools/capture-claude-mcp-fixture.sh` (needs an authenticated `claude`; an "
                "unauthenticated one returns 'Not logged in' and the script refuses to write)"
            )
        raw = _CLAUDE_FIXTURE.read_text()
        fixture = json.loads(raw)
        assert "_provenance" in fixture, (
            "fixture must have a top-level '_provenance' key per the SPEC provenance requirement"
        )
        provenance = fixture["_provenance"]
        assert "captured" in provenance, "provenance must record the capture date"
        assert "coverage_type" in provenance, "provenance must state coverage_type"

        result = _names_from_llm_json(raw)
        assert isinstance(result, set), f"_names_from_llm_json must return a set; got {type(result)}"
        assert result == self._EXPECTED_SERVERS, (
            f"parser returned {result!r}, expected {self._EXPECTED_SERVERS!r}. Either the "
            "`claude -p --output-format json` envelope changed shape, or the fixture was captured "
            "without --strict-mcp-config and picked up the host's own MCP servers. Re-capture with "
            "tools/capture-claude-mcp-fixture.sh."
        )
        # Every item in the result must be a string (the function's documented contract)
        for item in result:
            assert isinstance(item, str), f"result contains non-string: {item!r}"

    def test_bare_json_array_is_parsed(self):
        """'[\"time\", \"filesystem\"]' → {'time', 'filesystem'}."""
        result = _names_from_llm_json('["time", "filesystem"]')
        assert result == {"time", "filesystem"}, f"got {result!r}"

    def test_prose_wrapping_a_json_array_is_handled(self):
        """'Connected servers: [\"time\"]' → {'time'}."""
        result = _names_from_llm_json('Connected servers: ["time"]')
        assert result == {"time"}, f"got {result!r}"

    def test_empty_string_yields_empty_set(self):
        """Empty string → empty set (no IndexError, no exception)."""
        result = _names_from_llm_json("")
        assert result == set(), f"got {result!r}"

    def test_no_array_in_response_yields_empty_set(self):
        """'I cannot list them' → empty set (no array found)."""
        result = _names_from_llm_json("I cannot list them")
        assert result == set(), f"got {result!r}"

    def test_non_string_items_are_filtered_from_array(self):
        """'[1, \"time\", null, true]' → {'time'} (only string items are kept)."""
        result = _names_from_llm_json('[1, "time", null, true]')
        assert result == {"time"}, f"got {result!r}"

    def test_envelope_with_result_key_is_unwrapped(self):
        """JSON envelope with 'result' string key → server names extracted from result value.

        This is the actual format produced by `claude -p --output-format json`:
          {"result": "[\"server-name\"]", ...}
        The parser detects the dict with a 'result' string key and searches for [...] in it.
        """
        envelope = json.dumps({"result": '["hatago", "time"]', "other": "ignored"})
        result = _names_from_llm_json(envelope)
        assert result == {"hatago", "time"}, f"got {result!r}"

    def test_malformed_json_array_in_envelope_yields_empty_set(self):
        """A result field with a malformed JSON array → empty set (no exception)."""
        envelope = json.dumps({"result": "[not valid json"})
        result = _names_from_llm_json(envelope)
        assert result == set(), f"got {result!r}"

    def test_multiple_arrays_in_prose_yields_empty_set(self):
        """Two JSON arrays in prose → empty set (parser limitation, documented here).

        The parser uses re.search(r"\\[.*\\]", text, re.DOTALL) which greedily spans from
        the first '[' to the last ']'. A response like 'Active: ["time"] Disabled: ["other"]'
        produces the span '["time"] Disabled: ["other"]', which is not valid JSON, so the
        parser returns empty set rather than extracting either array. This is an inherent
        limitation of the greedy single-array regex: multi-array prose is not supported.
        Claude is expected to return a single JSON array for the MCP-list prompt.
        """
        result = _names_from_llm_json('Active: ["time"] Disabled: ["other"]')
        # Greedy span: '["time"] Disabled: ["other"]' → JSON parse fails → empty set
        assert result == set(), f"got {result!r}"
