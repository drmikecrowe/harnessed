"""A real docker container, a real exposed broker — issue #468, live.

tests/test_docker_broker.py pins the argv and the refusal. This is the half an argv cannot show:
that a docker container reaches the broker at `host.docker.internal`, trusts its CA, and is refused
without the data-plane token. The token is what stands between the 0.0.0.0 bind and anyone else on
the network, so its absence failing is as much the contract as its presence working.

The schema routes `example.com` with `@proxy` so the broker intercepts it and the handshake proves
the mounted CA; its value comes from `printf`. Gated on HARNESSED_DOCKER, so it runs in live-docker.
A host whose firewall drops bridge-to-host traffic fails the first test with the probe's answer,
which is the same refusal a launch would give.
"""

import json
import os
import subprocess
import uuid

import pytest

from harnessed import broker, launcher, mounts, paths

_IMAGE = "harnessed-base:latest"

_CA_VARS = (
    "CARGO_HTTP_CAINFO", "CURL_CA_BUNDLE", "DENO_CERT", "GIT_SSL_CAINFO",
    "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
)

_SCHEMA = "\n".join([
    '# @sensitive @proxy(domain="example.com") @placeholder="ph_00000000000000000000000000000000"',
    'DEMO_TOKEN=exec("printf %s not-a-real-secret")',
    "",
])

DOCKER = pytest.mark.skipif(
    not os.environ.get("HARNESSED_DOCKER"),
    reason="set HARNESSED_DOCKER=1 for live docker tests",
)


def _guest_env(session: str, proxy_url: str) -> dict[str, str]:
    proc = subprocess.run(
        ["varlock", "proxy", "env", "--session", session, "--full", "--format", "json",
         "--proxy-url", proxy_url, "--cert-dir", paths.BROKER_GUEST_CERT_DIR],
        capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, "FORCE_COLOR": "0"},
    )
    return json.loads(proc.stdout)


@pytest.fixture
def exposed_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / ".env.schema").write_text(_SCHEMA)
    monkeypatch.chdir(schema)
    inst = f"hn-468-{uuid.uuid4().hex[:8]}"
    brk = broker.start(inst, f"{inst}-pod", [schema], cert_dir=tmp_path / "certs", expose=True)
    try:
        door = f"{paths.BROKER_DOCKER_DOOR}:{brk.port}"

        def run(script: str, *, with_token: bool = True) -> subprocess.CompletedProcess:
            cred = f"varlock:{broker.token(brk)}@" if with_token else ""
            env = _guest_env(brk.session, f"http://{cred}{door}")
            env_args = [a for k, v in env.items() if "\n" not in v for a in ("-e", f"{k}={v}")]
            return subprocess.run(
                ["docker", "run", "--rm", *launcher._broker_door_args("docker", brk),
                 *mounts._broker_cert_mount_args(brk), *env_args,
                 "--entrypoint", "bash", _IMAGE, "-c", script],
                capture_output=True, text=True, timeout=120,
            )

        yield brk, run
    finally:
        broker.stop(inst)


@DOCKER
class TestAnExposedBrokerFromDocker:
    def test_the_probe_finds_the_door(self, exposed_broker):
        brk, _ = exposed_broker
        assert launcher._broker_gateway("docker", _IMAGE, brk.port), (
            "a docker container could not reach the exposed broker; a launch would refuse here"
        )

    def test_every_ca_path_var_resolves_to_a_readable_file(self, exposed_broker):
        _, run = exposed_broker
        script = "; ".join(
            f'[ -r "${v}" ] && echo "ok {v}" || echo "MISSING {v}=${v}"' for v in _CA_VARS
        )
        out = run(script).stdout
        assert all(f"ok {v}" in out for v in _CA_VARS), out

    def test_the_container_cannot_write_into_the_cert_dir(self, exposed_broker):
        _, run = exposed_broker
        proc = run(f"touch {paths.BROKER_GUEST_CERT_DIR}/planted && echo WROTE")
        assert "WROTE" not in proc.stdout
        assert "Read-only file system" in proc.stderr, proc.stderr

    def test_tls_through_the_broker_succeeds_with_the_token(self, exposed_broker):
        _, run = exposed_broker
        proc = run('curl -sS -o /dev/null -w "%{http_code}" --max-time 30 https://example.com/')
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith(("2", "3")), proc.stdout

    def test_without_the_token_the_broker_refuses(self, exposed_broker):
        """The 0.0.0.0 bind is safe only because of this."""
        _, run = exposed_broker
        proc = run(
            'curl -sS -o /dev/null -w "%{http_code}" --max-time 30 https://example.com/',
            with_token=False,
        )
        assert proc.returncode != 0
        assert "407" in proc.stderr + proc.stdout, (proc.stdout, proc.stderr)
