import sys
import time

import pytest

from DinoWrite.core import ffmpeg, process


class FakeOperation:
    """hou.InterruptableOperation: records progress, can simulate the user pressing cancel"""

    def __init__(self, cancel_after=None):
        self.updates, self.cancel_after = [], cancel_after

    def __call__(self, label, open_interrupt_dialog=False):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def updateProgress(self, value):
        self.updates.append(value)
        if self.cancel_after is not None and len(self.updates) > self.cancel_after:
            import hou
            raise hou.OperationInterrupted()


@pytest.fixture
def operation(monkeypatch, hou):
    def install(cancel_after=None):
        op = FakeOperation(cancel_after)
        monkeypatch.setattr(hou, "InterruptableOperation", op, raising=False)
        monkeypatch.setattr(process, "POLL_SECONDS", 0.01)
        return op
    return install


def test_success_collects_output(operation):
    operation()
    result = process.run([sys.executable, "-c", "print('hello')"], "test")
    assert result.ok and result
    assert "hello" in result.output


def test_failure_is_falsy_with_tail(operation):
    operation()
    result = process.run([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"], "test")
    assert not result
    assert result.returncode == 3
    assert result.tail() == "boom"


def test_cancel_kills_process(operation):
    op = operation(cancel_after=2)
    started = time.monotonic()
    result = process.run([sys.executable, "-c", "import time; time.sleep(30)"], "test", progress=lambda: 0.5)
    assert result.cancelled and not result
    assert time.monotonic() - started < 10
    assert op.updates[:2] == [0.5, 0.5]


def test_missing_executable(operation):
    operation()
    result = process.run(["/no/such/tool"], "test")
    assert not result and result.error


def test_ffmpeg_progress_from_file(tmp_path):
    progress = tmp_path / "progress.txt"
    assert ffmpeg.progressFromFile(progress, 100) is None
    progress.write_text("frame=10\nfps=24\nprogress=continue\nframe=25\nfps=")
    assert ffmpeg.progressFromFile(progress, 100) == 0.25
    assert ffmpeg.progressFromFile(progress, 0) is None


def test_processes_parallel_success():
    group = process.Processes([[sys.executable, "-c", "print('a')"], [sys.executable, "-c", "print('b')"]], "test")
    while (result := group.poll()) is None:
        time.sleep(0.01)
    assert result and "a" in result.output and "b" in result.output


def test_processes_one_failure_kills_the_rest():
    group = process.Processes([[sys.executable, "-c", "import sys; sys.exit(2)"],
                               [sys.executable, "-c", "import time; time.sleep(30)"]], "test")
    started = time.monotonic()
    while (result := group.poll()) is None:
        time.sleep(0.01)
    assert result.returncode == 2
    assert time.monotonic() - started < 10


def test_processes_cancel():
    group = process.Processes([[sys.executable, "-c", "import time; time.sleep(30)"]], "test")
    assert group.poll() is None
    assert group.cancel().cancelled
