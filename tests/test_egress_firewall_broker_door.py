"""`catalog/base/egress-firewall.sh` must open the broker's door, and only that — #436, #468.

#436 opened a fixed `169.254.1.1` for the pasta `--map-host-loopback` door #437 added. That pasta
option does not exist on the pasta GitHub's runner ships, so #468 replaced the door on both
runtimes: the broker is exposed and token-gated, the container reaches it at its runtime's
host-gateway name, and the launcher's reachability probe returns the address that name resolved
to. The launcher passes that address as `--broker=<ip>`, and the script installs it with
`require`, as #436's fixed rule was: a door that did not open must fail the launch, not hang the
agent later.

These tests run the REAL script under `bash` with a stub `PATH`. Only the kernel-touching binaries
at its boundary are replaced (`iptables`, `ip6tables`, `ip`, `getent`); every line of the script's
own logic executes. The stubs record their argv, so the assertions are about the rules the script
actually installs, not about the text it is written in.

What this file CANNOT prove: that a container reaches the broker. tests/test_broker_pod_live.py and
tests/test_broker_docker_live.py do, per runtime.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

FIREWALL = Path(__file__).resolve().parents[1] / "catalog" / "base" / "egress-firewall.sh"

# What the probe hands the launcher on docker's default bridge.
GATEWAY = "172.17.0.1"
RETIRED_DOOR = "169.254.1.1"

# The stub `getent` resolves from this table, so every expected IP in an assertion is one the test
# chose. Unlisted names fall back to a single documentation-range address.
DEFAULT_GETENT_MAP = {
    "host.containers.internal": "169.254.1.2",
}
FALLBACK_IP = "203.0.113.1"

_IPTABLES_STUB = r"""#!/usr/bin/env bash
# Records argv, then answers the two queries the script makes of iptables.
printf '%s\n' "$*" >> "$IPT_LOG"
if [ -n "${IPT_FAIL_MATCH:-}" ] && [[ "$*" == *"$IPT_FAIL_MATCH"* ]]; then
    exit 1
fi
if [ "${1:-}" = "-S" ]; then
    [ -z "${IPT_NO_DROP:-}" ] && printf -- '-P OUTPUT DROP\n'
    exit 0
fi
exit 0
"""

_IP6TABLES_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$IP6T_LOG"
exit 0
"""

_IP_STUB = r"""#!/usr/bin/env bash
# Only `ip route` is called, and only the default line is read.
[ "${1:-}" = "route" ] && printf 'default via 10.0.2.2 dev eth0\n'
exit 0
"""

_GETENT_STUB = r"""#!/usr/bin/env bash
# `getent ahosts <name>` — resolve from the table the test supplied.
name="${2:-}"
ip=""
while read -r key value; do
    [ "$key" = "$name" ] && ip="$value"
done < "$GETENT_MAP"
[ -z "$ip" ] && ip="__FALLBACK__"
printf '%s STREAM %s\n' "$ip" "$name"
exit 0
""".replace("__FALLBACK__", FALLBACK_IP)


def _run_firewall(tmp_path, *args, getent_map=None, env=None):
    """Execute the real script with stubbed boundary binaries. Returns (proc, ipt, ip6t).

    `ipt` and `ip6t` are the recorded argv lines, one per invocation.
    """
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    for name, body in (
        ("iptables", _IPTABLES_STUB),
        ("ip6tables", _IP6TABLES_STUB),
        ("ip", _IP_STUB),
        ("getent", _GETENT_STUB),
    ):
        path = stub_dir / name
        path.write_text(body)
        path.chmod(0o755)

    table = dict(DEFAULT_GETENT_MAP)
    table.update(getent_map or {})
    map_file = tmp_path / "hosts"
    map_file.write_text("".join(f"{k} {v}\n" for k, v in table.items()))

    ipt_log = tmp_path / "iptables.log"
    ip6t_log = tmp_path / "ip6tables.log"
    ipt_log.touch()
    ip6t_log.touch()

    child_env = dict(os.environ)
    child_env.update(
        {
            "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
            "IPT_LOG": str(ipt_log),
            "IP6T_LOG": str(ip6t_log),
            "GETENT_MAP": str(map_file),
        }
    )
    child_env.update(env or {})

    proc = subprocess.run(
        ["bash", str(FIREWALL), *args],
        capture_output=True,
        text=True,
        env=child_env,
        check=False,
    )
    return proc, ipt_log.read_text().splitlines(), ip6t_log.read_text().splitlines()


class TestTheProbedGateway:
    """The address the launcher's probe found, passed as `--broker=<ip>`."""

    def _run(self, tmp_path, **kw):
        return _run_firewall(tmp_path, f"--broker={GATEWAY}", **kw)

    def test_a_failed_broker_rule_is_fatal(self, tmp_path):
        # #429's property: an agent holding placeholders behind a blocked broker would hang at
        # runtime, so the door is `require`d like the rules that make the firewall a firewall.
        proc, _ipt, _ip6t = self._run(tmp_path, env={"IPT_FAIL_MATCH": GATEWAY})
        assert proc.returncode != 0
        assert "FATAL" in proc.stderr
        assert "Egress active" not in proc.stdout

    @pytest.mark.parametrize("value", [
        "", "host.docker.internal", "10.0.0.0/8", "!10.0.0.1",
        # Hex-only strings pass a charset test, and iptables -d resolves hostnames.
        "cafe", "beef",
        # Shape, not alphabet: these fail later inside `require` with a vaguer message.
        "999.1.2.3", "1.2.3.4.5", "1.2.3",
        # A leading zero reads as octal to inet_aton: 010.0.0.1 would open 8.0.0.1.
        "010.0.0.1", "10.0.0.01",
        # The rule is installed with iptables, which is IPv4 only.
        "fd00::1",
        # The any-address and the broadcast address are never a broker, and the first can act
        # as an any-destination match in the rule.
        "0.0.0.0",  # noqa: S104 - a value the script must refuse, not a bind
        "255.255.255.255",
    ])
    def test_a_value_that_is_not_an_address_is_refused(self, tmp_path, value):
        # A hostname, a CIDR or a `!` would change what the rule allows; an empty value would
        # silently install none. All are launcher bugs, and each should stop the script here.
        proc, ipt, _ip6t = _run_firewall(tmp_path, f"--broker={value}")
        assert proc.returncode != 0
        assert "--broker" in proc.stderr
        assert "-F OUTPUT" not in ipt, "refused before touching the ruleset"

    def test_a_second_broker_is_refused(self, tmp_path):
        # One launch has one broker; two values mean the launcher is confused, and silently
        # keeping the last would open whichever address happened to come second.
        proc, ipt, _ip6t = _run_firewall(tmp_path, "--broker=10.0.0.1", "--broker=10.0.0.2")
        assert proc.returncode != 0
        assert "--broker" in proc.stderr
        assert "-F OUTPUT" not in ipt

    @pytest.mark.parametrize("value", ["172.17.0.1", "10.0.2.2", "192.168.1.254"])
    def test_a_dotted_quad_is_accepted(self, tmp_path, value):
        proc, ipt, _ip6t = _run_firewall(tmp_path, f"--broker={value}")
        assert proc.returncode == 0, proc.stderr
        assert f"-A OUTPUT -d {value} -j ACCEPT" in ipt

    def test_the_flag_is_not_treated_as_a_domain(self, tmp_path):
        proc, _ipt, _ip6t = self._run(tmp_path)
        assert "--broker" not in proc.stdout + proc.stderr

    def test_it_is_accepted(self, tmp_path):
        # Without it the agent cannot open a socket to the broker under a DROP policy.
        _proc, ipt, _ip6t = self._run(tmp_path)
        assert f"-A OUTPUT -d {GATEWAY} -j ACCEPT" in ipt

    def test_it_is_opened_after_the_flush(self, tmp_path):
        # In a real netns `-F OUTPUT` discards a rule issued before it; the stubs hold no ruleset,
        # so the ordering is what is asserted.
        _proc, ipt, _ip6t = self._run(tmp_path)
        door = ipt.index(f"-A OUTPUT -d {GATEWAY} -j ACCEPT")
        assert ipt.index("-F OUTPUT") < door
        assert ipt.index("-P OUTPUT DROP") < door

    def test_no_ipv6_rule_for_it(self, tmp_path):
        _proc, _ipt, ip6t = self._run(tmp_path)
        assert not [line for line in ip6t if GATEWAY in line]


class TestNoWidening:
    """Nothing is opened for the broker that the launcher did not pass."""

    def test_the_retired_pasta_door_is_gone(self, tmp_path):
        # #468: the fixed 169.254.1.1 rule served a pasta option the runner's pasta lacks.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        assert not [line for line in ipt if RETIRED_DOOR in line]

    def test_only_podmans_own_link_local_gateway_is_accepted(self, tmp_path):
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        seen = set()
        for line in ipt:
            seen.update(re.findall(r"169\.254\.[0-9]+\.[0-9]+", line))
        assert seen == {"169.254.1.2"}

    def test_no_link_local_cidr_is_ever_accepted(self, tmp_path):
        # A /16 here would hand the pod the whole link-local range. Asserted on argv, so it also
        # catches a CIDR arriving via a lookup.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        assert not [line for line in ipt if re.search(r"169\.254\.[0-9.]+/[0-9]+", line)]


class TestFailsLoudly:
    """N1 — the #429 property: a firewall that did not take must not report success."""

    def test_a_policy_that_is_not_drop_is_still_fatal(self, tmp_path):
        # N1 regression guard: the end-state verification still gates the success message.
        proc, _ipt, _ip6t = _run_firewall(tmp_path, env={"IPT_NO_DROP": "1"})
        assert proc.returncode != 0
        assert "no firewall is in effect" in proc.stderr


class TestPreservedBehaviour:
    """N2, N3 — everything the script already did, still done."""

    def test_success_path_reports_and_exits_zero(self, tmp_path):
        proc, _ipt, _ip6t = _run_firewall(tmp_path)
        assert proc.returncode == 0
        assert "Egress active:" in proc.stdout

    def test_recipe_declared_egress_domains_are_still_appended(self, tmp_path):
        # Recipes pass extra hosts as positional args; the launcher relies on it.
        proc, ipt, _ip6t = _run_firewall(
            tmp_path,
            "api.z.ai",
            getent_map={"api.z.ai": "198.51.100.7"},
        )
        assert proc.returncode == 0
        assert "-A OUTPUT -d 198.51.100.7 -j ACCEPT" in ipt

    def test_the_four_load_bearing_rules_are_still_installed(self, tmp_path):
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        for rule in (
            "-F OUTPUT",
            "-P OUTPUT DROP",
            "-A OUTPUT -o lo -j ACCEPT",
            "-A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
        ):
            assert rule in ipt


def test_the_stubs_can_actually_fail(tmp_path):
    """Negative control for the harness itself.

    Every assertion above rests on the stubs reporting what the script did. A stub that silently
    succeeded no matter what would make each of them vacuous, and nothing else in this file would
    notice. Fail an invocation the script requires and the script must die.
    """
    proc, _ipt, _ip6t = _run_firewall(tmp_path, env={"IPT_FAIL_MATCH": "-P OUTPUT DROP"})
    assert proc.returncode != 0


def test_script_is_present():
    """Guards against every test above erroring identically if the script is ever moved."""
    assert FIREWALL.is_file()
