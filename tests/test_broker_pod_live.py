"""A real pod, a real broker, the broker's CA mounted read-only — issue #438, live.

tests/test_broker_cert_mount.py pins the argv. This is the half an argv cannot show: that the seven
CA-path variables `varlock proxy env --full` emits resolve to readable files inside a pod, that the
pod cannot write to them, and that a proxy-aware client completes a TLS handshake against the
broker's CA.

The handshake only proves the CA if the broker intercepts it. varlock tunnels an unmatched host
untouched, and then the client sees the upstream's real certificate. So the fixture schema routes
`example.com` with `@proxy`, and the value it injects comes from `printf`: no secrets backend, no
unlock prompt.

podman only. The broker door is a pasta option on `pod create` (#437); docker has no pods, and what
docker gets is #468.
"""

import json
import os
import subprocess
import uuid

import pytest

from harnessed import broker, mounts, paths
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


def _image_present(image: str) -> bool:
    return subprocess.run(
        ["podman", "image", "exists", image], capture_output=True
    ).returncode == 0


def _guest_env(session: str, port: int) -> dict[str, str]:
    """What #439 will hand the pod: the broker's env, repointed at the door and the mount."""
    proc = subprocess.run(
        ["varlock", "proxy", "env", "--session", session, "--full", "--format", "json",
         "--proxy-url", f"http://{paths.BROKER_HOST_DOOR}:{port}",
         "--cert-dir", paths.BROKER_GUEST_CERT_DIR],
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
            ["podman", "pod", "create", "--name", pod,
             *mounts._mcp_remote_pod_args([], "", broker=True)],
            check=True, capture_output=True, timeout=60,
        )
        try:
            env = _guest_env(brk.session, brk.port)
            env_args = [a for k, v in env.items() if "\n" not in v for a in ("-e", f"{k}={v}")]

            def run(script: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    ["podman", "run", "--rm", "--pod", pod,
                     *mounts._broker_cert_mount_args(brk), *env_args,
                     "--entrypoint", "bash", _BASE_IMAGE, "-c", script],
                    capture_output=True, text=True, timeout=120,
                )

            yield run
        finally:
            subprocess.run(["podman", "pod", "rm", "-f", pod], capture_output=True, timeout=60)
    finally:
        broker.stop(inst)


@podman
class TestTheBrokersCaInsideAPod:
    def test_every_ca_path_var_resolves_to_a_readable_file(self, pod_with_broker):
        script = "; ".join(
            f'[ -r "${v}" ] && echo "ok {v}" || echo "MISSING {v}=${v}"' for v in _CA_VARS
        )
        out = pod_with_broker(script).stdout
        assert all(f"ok {v}" in out for v in _CA_VARS), out

    def test_the_pod_cannot_write_into_the_cert_dir(self, pod_with_broker):
        proc = pod_with_broker(f"touch {paths.BROKER_GUEST_CERT_DIR}/planted && echo WROTE")
        assert "WROTE" not in proc.stdout
        assert "Read-only file system" in proc.stderr, proc.stderr

    def test_a_proxy_aware_client_completes_tls_against_the_broker(self, pod_with_broker):
        """curl honours HTTPS_PROXY and CURL_CA_BUNDLE. A CA it did not trust fails with exit 60."""
        proc = pod_with_broker(
            'curl -sS -o /dev/null -w "%{http_code}" --max-time 30 https://example.com/'
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith(("2", "3")), proc.stdout
