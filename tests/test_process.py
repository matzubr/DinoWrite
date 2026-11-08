import sys
import time

from DinoWrite.core import ffmpeg, process


def _wait(proc):
    while (result := proc.poll()) is None:
        time.sleep(0.01)
    return result


def test_success_collects_output():
    result = _wait(process.Process([sys.executable, "-c", "print('hello')"], "test"))
    assert result.ok and result
    assert "hello" in result.output


def test_failure_is_falsy_with_tail():
    result = _wait(process.Process([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"], "test"))
    assert not result
    assert result.returncode == 3
    assert result.tail() == "boom"


def test_cancel_kills_process():
    proc = process.Process([sys.executable, "-c", "import time; time.sleep(30)"], "test")
    started = time.monotonic()
    assert proc.poll() is None
    assert proc.cancel().cancelled
    assert time.monotonic() - started < 10


def test_missing_executable():
    result = process.Process(["/no/such/tool"], "test").poll()
    assert not result and result.error


def test_ffmpeg_progress_from_file(tmp_path):
    progress = tmp_path / "progress.txt"
    assert ffmpeg.progressFromFile(progress, 100) is None
    progress.write_text("frame=10\nfps=24\nprogress=continue\nframe=25\nfps=")
    assert ffmpeg.progressFromFile(progress, 100) == 0.25
    assert ffmpeg.progressFromFile(progress, 0) is None
