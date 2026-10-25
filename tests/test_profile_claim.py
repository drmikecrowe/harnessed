"""GH-631: a host launch claims its stack's profile before it assembles.

SPEC S1, S3, S4.2, S5 and S7, against real `flock` and real subprocesses. The in-process launch
scenarios (S2, S4.1, S6) live in `tests/test_host_acp.py`, beside the `host` fixture they use.
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harnessed import emit, paths
from harnessed.hosthome import _claim_profile

_IN_USE = (
    "profile 's' (claude) is in use by a running session; stack changes apply after every "
    "session of it closes"
)

# Each child waits for `go` before it claims, so the two claims start within milliseconds of each
# other whatever the interpreter start-up costs. The builder holds the session for 1 s after
# `done()`, standing in for the harness it would exec.
_RACER = """
import os, sys, time
from pathlib import Path
from harnessed.hosthome import _claim_profile
counter, ready, go = (Path(p) for p in sys.argv[1:4])
ready.touch()
while not go.exists():
    time.sleep(0.005)
claim = _claim_profile("s", "claude")
print(f"build={claim.build}", flush=True)
if claim.build:
    with counter.open("a") as f:
        f.write("built\\n")
    time.sleep(0.5)
    claim.done()
    time.sleep(1)
"""

_HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_SH)
print("held", flush=True)
time.sleep(60)
"""

# S4.2: A builds, waits until B is about to claim, then dies without `done()`.
_DIES = """
import sys, time
from pathlib import Path
from harnessed.hosthome import _claim_profile
waiting = Path(sys.argv[1])
claim = _claim_profile("s", "claude")
print(f"build={claim.build}", flush=True)
while not waiting.exists():
    time.sleep(0.005)
time.sleep(0.3)
sys.exit(1)
"""

_WAITER = """
import sys
from pathlib import Path
from harnessed.hosthome import _claim_profile
Path(sys.argv[1]).touch()
print(f"build={_claim_profile('s', 'claude').build}", flush=True)
"""

_EXECS = """
import os
from harnessed.hosthome import _claim_profile
claim = _claim_profile("s", "claude")  # bound, as `_launch_host` binds it, until the exec
claim.done()
os.execvp("sleep", ["sleep", "30"])
"""


@pytest.fixture
def env(tmp_path, monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    child = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "data")}
    child.pop("FORCE_COLOR", None)
    return child


def _lock() -> Path:
    return paths.profile_dir("s", "claude").parent / "claude.lock"


def _gate() -> Path:
    return paths.profile_dir("s", "claude").parent / "claude.build.lock"


def _spawn(env: dict[str, str], code: str, *args: object) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", code, *map(str, args)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.01)


def _try_exclusive(path: Path) -> bool:
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def _race(env: dict[str, str], tmp_path: Path) -> list[tuple[int, str, str]]:
    counter, go = tmp_path / "counter", tmp_path / "go"
    readies = [tmp_path / f"ready{i}" for i in range(2)]
    procs = [_spawn(env, _RACER, counter, ready, go) for ready in readies]
    for ready in readies:
        _wait_for(ready)
    go.touch()
    out = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=60)
        out.append((proc.returncode, stdout, stderr))
    return out


class TestConcurrentLaunchesBuildOnce:
    def test_s1_1_two_racing_claims_both_succeed_and_build_once(self, env, tmp_path):
        results = _race(env, tmp_path)
        assert [rc for rc, _, _ in results] == [0, 0], results
        assert (tmp_path / "counter").read_text().splitlines() == ["built"]
        assert sorted(out.strip() for _, out, _ in results) == ["build=False", "build=True"]

    def test_s1_2_the_second_claim_prints_the_in_use_line_once(self, env, tmp_path):
        results = _race(env, tmp_path)
        waiter = next(err for _, out, err in results if out.strip() == "build=False")
        builder = next(err for _, out, err in results if out.strip() == "build=True")
        assert waiter.count(_IN_USE) == 1, waiter
        assert _IN_USE not in builder


class TestAWaitIsVisible:
    """PR #636 review: a launch blocked on the gate printed nothing until the build finished."""

    _WAITING = "waiting for a concurrent build of profile 's' (claude)"

    def test_only_the_claim_that_waits_on_the_gate_says_so(self, env, tmp_path):
        results = _race(env, tmp_path)
        waiter = next(err for _, out, err in results if out.strip() == "build=False")
        builder = next(err for _, out, err in results if out.strip() == "build=True")
        assert waiter.count(self._WAITING) == 1, waiter
        assert self._WAITING not in builder


class TestAfterEverySessionEnds:
    def test_s3_1_a_killed_session_releases_the_profile(self, env):
        _lock().parent.mkdir(parents=True)
        holder = _spawn(env, _HOLDER, _lock())
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=30)
        claim = _claim_profile("s", "claude")
        try:
            assert claim.build is True
        finally:
            claim.release()

    def test_s3_2_a_first_claim_creates_the_dir_and_both_lock_files(self, env):
        assert not _lock().parent.exists()
        claim = _claim_profile("s", "claude")
        try:
            assert claim.build is True
            assert _lock().is_file() and _gate().is_file()
        finally:
            claim.release()


class TestFailedBuildReleases:
    def test_s4_2_a_builder_that_dies_hands_the_build_to_the_waiter(self, env, tmp_path):
        waiting = tmp_path / "waiting"
        a = _spawn(env, _DIES, waiting)
        assert a.stdout is not None
        assert a.stdout.readline().strip() == "build=True"
        b = _spawn(env, _WAITER, waiting)
        a_out = a.communicate(timeout=60)
        b_out, b_err = b.communicate(timeout=60)
        assert a.returncode == 1, a_out
        assert b.returncode == 0, b_err
        assert b_out.strip() == "build=True", b_err


class TestAFailedClaimReleases:
    """PR #636 review: a lock call that fails inside `_claim_profile` returned no claim, so nothing
    could release the gate it already held."""

    def test_a_session_lock_error_leaves_the_gate_free(self, env, monkeypatch):
        import errno

        from harnessed import hosthome

        real = fcntl.flock

        def flock(fd, op):
            on_session = os.readlink(f"/proc/self/fd/{fd}") == str(_lock())
            if on_session and op == fcntl.LOCK_EX | fcntl.LOCK_NB:
                raise OSError(errno.ENOLCK, "no locks available")
            return real(fd, op)

        # Kept, as a caller that logs or re-raises it keeps it: its traceback holds the frame's files,
        # so GC cannot be what frees the gate. (`pytest.raises` drops the frames, hiding the leak.)
        kept: OSError | None = None
        with monkeypatch.context() as m:
            m.setattr(hosthome.fcntl, "flock", flock)
            try:
                _claim_profile("s", "claude")
            except OSError as exc:
                kept = exc
        assert kept is not None and kept.errno == errno.ENOLCK
        assert _try_exclusive(_gate())
        assert _try_exclusive(_lock())


class TestSessionLockSurvivesExec:
    @pytest.fixture
    def execd(self, env):
        proc = _spawn(env, _EXECS)
        deadline = time.monotonic() + 30
        while Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")[0] != b"sleep":
            assert time.monotonic() < deadline, "the child never exec'd sleep"
            assert proc.poll() is None, proc.communicate()
            time.sleep(0.01)
        yield proc
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    def test_s5_1_the_session_lock_is_held_after_exec(self, execd):
        with pytest.raises(BlockingIOError):
            fd = os.open(_lock(), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)

    def test_s5_2_killing_the_execd_process_releases_it(self, execd):
        execd.kill()
        execd.communicate(timeout=30)
        assert _try_exclusive(_lock())

    def test_s5_3_the_gate_fd_does_not_reach_the_execd_process(self, execd):
        assert _try_exclusive(_gate())


class TestLockFilesOutliveAReset:
    def test_s7_1_reset_profile_leaves_both_lock_files(self, env):
        claim = _claim_profile("s", "claude")
        try:
            assert claim.build is True
            prof = paths.profile_dir("s", "claude")
            (prof / "file").parent.mkdir(parents=True, exist_ok=True)
            (prof / "file").write_text("x")
            emit.reset_profile(prof)
            assert _lock().is_file() and _gate().is_file()
        finally:
            claim.release()
