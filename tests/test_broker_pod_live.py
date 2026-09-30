"""A real pod, a real broker, the broker's CA mounted read-only — issues #438 and #468, live.

tests/test_broker_cert_mount.py and tests/test_broker_door.py pin the argv. This is the half an
argv cannot show: that a pod reaches the exposed broker at `host.containers.internal`, that the
seven CA-path variables `varlock proxy env --full` emits resolve to readable files inside it, that
the pod cannot write to them, that a proxy-aware client completes TLS against the broker's CA with
the data-plane token, and that the broker refuses it without one.

The handshake only proves the CA if the broker intercepts it. varlock tunnels an unmatched host
untouched, and then the client sees the upstream's real certificate. So the fixture schema routes
`example.com` with `@proxy`, and the value it injects comes from `printf`: no secrets backend, no
unlock prompt.

The first run of this file, against #437's pasta door, failed on GitHub's runner with
"pasta: unrecognized option '--map-host-loopback'". That is why the door changed (#468).
"""

import json
import os
import subprocess
import uuid

import pytest

from harnessed import broker, launcher, mounts, paths
from support import podman

_BASE_IMAGE = "localhost/harnessed-base:latest"

# Every CA-path variable varlock 1.16.1 emits, measured from `proxy env --full`.
_CA_VARS = (
    "CARGO_HTTP_CAINFO", "CURL_CA_BUNDLE", "DENO_CERT", "GIT_SSL_CAINFO",
    "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
)

_SCHEMA = "\n".join([
    '# @sensitive @proxy(domain="example.com") @placeholder="ph_00000000000000000000000000000000"',
    'DEMO_TOKEN=exec("printf %s not-a-real-secret")',
    "",
])

_CURL = 'curl -sS -o /dev/null -w "%{http_code}" --max-time 30 https://example.com/'


def _image_present(image: str) -> bool:
    return subprocess.run(
        ["podman", "image", "exists", image], capture_output=True
    ).returncode == 0


def _guest_env(session: str, proxy_url: str) -> dict[str, str]:
    """What #439 will hand the pod: the broker's env, repointed at the door and the mount."""
    proc = subprocess.run(
        ["varlock", "proxy", "env", "--session", session, "--full", "--format", "json",
         "--proxy-url", proxy_url, "--cert-dir", paths.BROKER_GUEST_CERT_DIR],
        capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, "FORCE_COLOR": "0"},
    )
    return json.loads(proc.stdout)


@pytest.fixture
def pod_with_broker(tmp_path, monkeypatch):
    if not _image_present(_BASE_IMAGE):
        pytest.skip(f"{_BASE_IMAGE} not built — run `harnessed build` first")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / ".env.schema").write_text(_SCHEMA)
    monkeypatch.chdir(schema)

    tag = uuid.uuid4().hex[:8]
    inst, pod = f"hn-438-{tag}", f"hn-438-{tag}-pod"
    brk = broker.start(inst, pod, [schema], cert_dir=tmp_path / "certs")
    try:
        subprocess.run(
            ["podman", "pod", "create", "--name", pod], check=True, capture_output=True, timeout=60,
        )
        try:
            door = f"{paths.broker_door('podman')}:{brk.port}"

            def run(script: str, *, with_token: bool = True) -> subprocess.CompletedProcess:
                cred = f"varlock:{broker.token(brk)}@" if with_token else ""
                env = _guest_env(brk.session, f"http://{cred}{door}")
                env_args = [a for k, v in env.items() if "\n" not in v for a in ("-e", f"{k}={v}")]
                return subprocess.run(
                    ["podman", "run", "--rm", "--pod", pod,
                     *mounts._broker_cert_mount_args(brk), *env_args,
                     "--entrypoint", "bash", _BASE_IMAGE, "-c", script],
                    capture_output=True, text=True, timeout=120,
                )

            yield brk, pod, run
        finally:
            subprocess.run(["podman", "pod", "rm", "-f", pod], capture_output=True, timeout=60)
    finally:
        broker.stop(inst)


@podman
class TestTheBrokerFromAPod:
    def test_the_probe_finds_the_door(self, pod_with_broker):
        brk, pod, _ = pod_with_broker
        assert launcher._broker_gateway("podman", _BASE_IMAGE, brk.port, pod), (
            "a pod could not reach the exposed broker; a launch would refuse here"
        )

    def test_every_ca_path_var_resolves_to_a_readable_file(self, pod_with_broker):
        _, _, run = pod_with_broker
        script = "; ".join(
            f'[ -r "${v}" ] && echo "ok {v}" || echo "MISSING {v}=${v}"' for v in _CA_VARS
        )
        out = run(script).stdout
        assert all(f"ok {v}" in out for v in _CA_VARS), out

    def test_the_pod_cannot_write_into_the_cert_dir(self, pod_with_broker):
        _, _, run = pod_with_broker
        proc = run(f"touch {paths.BROKER_GUEST_CERT_DIR}/planted && echo WROTE")
        assert "WROTE" not in proc.stdout
        assert "Read-only file system" in proc.stderr, proc.stderr

    def test_a_proxy_aware_client_completes_tls_with_the_token(self, pod_with_broker):
        """curl honours HTTPS_PROXY and CURL_CA_BUNDLE. A CA it did not trust fails with exit 60."""
        _, _, run = pod_with_broker
        proc = run(_CURL)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith(("2", "3")), proc.stdout

    def test_without_the_token_the_broker_refuses(self, pod_with_broker):
        """The 0.0.0.0 bind is safe only because of this."""
        _, _, run = pod_with_broker
        proc = run(_CURL, with_token=False)
        assert proc.returncode != 0
        assert "407" in proc.stderr + proc.stdout, (proc.stdout, proc.stderr)
