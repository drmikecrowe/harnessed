"""`catalog/base/egress-firewall.sh` must open the loopback broker door — issue #436.

Epic #388 Phase 1 ruled Topology B: `varlock proxy start` binds `127.0.0.1` on the HOST only, and
the pod reaches it at `169.254.1.1` through podman's `pasta --map-host-loopback,169.254.1.1`. The
firewall sets `OUTPUT` policy to DROP and whitelists from there, so without an ACCEPT for that one
address the pod cannot reach the broker at all.

These tests run the REAL script under `bash` with a stub `PATH`. Only the kernel-touching binaries
at its boundary are replaced (`iptables`, `ip6tables`, `ip`, `getent`); every line of the script's
own logic executes. The stubs record their argv, so the assertions are about the rules the script
actually installs, not about the text it is written in.

What this file CANNOT prove: no test in this repo runs `podman build` or `harnessed container-run`,
so nothing here shows a pod reaching the host broker. The routability half of #436's acceptance
belongs to #437, which adds the pasta flag.
"""

import os
import re
import subprocess
from pathlib import Path

FIREWALL = Path(__file__).resolve().parents[1] / "catalog" / "base" / "egress-firewall.sh"

BROKER_DOOR = "169.254.1.1"

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


class TestBrokerDoor:
    """S1, S2, S5 — the one address the pod needs, installed the one way it works."""

    def test_broker_door_is_accepted(self, tmp_path):
        # S1. Without this rule the pod cannot open a socket to the broker under a DROP policy.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        assert f"-A OUTPUT -d {BROKER_DOOR} -j ACCEPT" in ipt

    def test_door_is_opened_after_the_drop_policy_is_set(self, tmp_path):
        # S2. `-F OUTPUT` flushes; a rule appended before `-P OUTPUT DROP` would be discarded.
        # This asserts the rule actually survives to the end state, not merely that it was issued.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        assert ipt.index("-P OUTPUT DROP") < ipt.index(f"-A OUTPUT -d {BROKER_DOOR} -j ACCEPT")

    def test_no_ipv6_rule_for_the_broker(self, tmp_path):
        # S5. 169.254.1.1 is IPv4 link-local. An ip6tables counterpart would be meaningless.
        _proc, _ipt, ip6t = _run_firewall(tmp_path)
        assert not [line for line in ip6t if BROKER_DOOR in line]


class TestNoWidening:
    """S4 — the point of Topology B is that nothing but the pod can reach the broker."""

    def test_only_the_two_known_link_local_addresses_are_accepted(self, tmp_path):
        # The broker door plus podman's own host-gateway. Nothing else in 169.254.0.0/16.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        seen = set()
        for line in ipt:
            seen.update(re.findall(r"169\.254\.[0-9]+\.[0-9]+", line))
        assert seen == {BROKER_DOOR, "169.254.1.2"}

    def test_no_link_local_cidr_is_ever_accepted(self, tmp_path):
        # A /16 here would hand the pod the whole link-local range, which is the opposite of
        # what #436 asks for. Asserted on argv, so it also catches a CIDR arriving via a lookup.
        _proc, ipt, _ip6t = _run_firewall(tmp_path)
        assert not [line for line in ipt if re.search(r"169\.254\.[0-9.]+/[0-9]+", line)]


class TestFailsLoudly:
    """S3 and N1 — the #429 property: a rule that did not install must not report success."""

    def test_a_failed_broker_rule_is_fatal(self, tmp_path):
        # #429: for most of this project's life every iptables call failed and the script still
        # printed "Egress active" and exited 0. The broker door must not reintroduce that silence.
        proc, _ipt, _ip6t = _run_firewall(tmp_path, env={"IPT_FAIL_MATCH": BROKER_DOOR})
        assert proc.returncode != 0
        assert "FATAL" in proc.stderr
        assert "Egress active" not in proc.stdout

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
