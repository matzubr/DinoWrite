"""Run ffmpeg without blocking Houdini.

Process is polled (no threads: hou isn't thread safe): the GUI polls it from a QTimer.
"""
import subprocess
import sys
import tempfile

from .log import log

POLL_SECONDS = 0.2
OUTPUT_TAIL_LINES = 15

# Houdini is a GUI app: on Windows every console tool started from it pops up its own console window
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class Result:
    """Outcome of an external process. Truthy only when it finished successfully."""

    def __init__(self, returncode=None, output: str = "", cancelled: bool = False, error: str = ""):
        self.returncode = returncode
        self.output = output
        self.cancelled = cancelled
        self.error = error

    @property
    def ok(self) -> bool:
        return not self.cancelled and not self.error and self.returncode == 0

    def __bool__(self) -> bool:
        return self.ok

    def tail(self, lines: int = OUTPUT_TAIL_LINES) -> str:
        return "\n".join(self.output.strip().splitlines()[-lines:])


class Process:
    """A running command. Poll it until it returns a Result."""

    def __init__(self, cmd: list, label: str):
        self.label = label
        self._proc = None
        self._result = None
        log.info("%s: %s", label, subprocess.list2cmdline(cmd))
        # Output goes to a temp file, not a pipe: a full pipe buffer would block the process
        self._output = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        try:
            self._proc = subprocess.Popen(cmd, stdout=self._output, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, **NO_WINDOW)
        except OSError as e:
            log.error("%s: can't start %s: %s", label, cmd[0], e)
            self._result = Result(error=str(e), output=self._readOutput())

    def poll(self):
        """None while running, Result when finished"""
        if self._result is not None:
            return self._result
        code = self._proc.poll()
        if code is None:
            return None
        self._result = Result(returncode=code, output=self._readOutput())
        if not self._result:
            log.error("%s failed with exit code %s:\n%s", self.label, code, self._result.tail())
        return self._result

    def cancel(self) -> Result:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        self._result = Result(cancelled=True, output=self._readOutput())
        log.warning("%s: cancelled", self.label)
        return self._result

    def _readOutput(self) -> str:
        if self._output is None:
            return ""
        self._output.seek(0)
        text = self._output.read()
        self._output.close()
        self._output = None
        return text
