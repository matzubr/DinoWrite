"""Run external tools (ffmpeg, hoiiotool) with Houdini progress and cancel (Esc / interrupt dialog)."""
import subprocess
import sys
import tempfile
import time

import hou

from .log import log

POLL_SECONDS = 0.2

# Houdini is a GUI app: on Windows every console tool started from it pops up its own console window
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
OUTPUT_TAIL_LINES = 15


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


def run(cmd: list, label: str, progress=None) -> Result:
    """Run cmd while showing Houdini progress; user can cancel it.

    Args:
        cmd (list): argv
        label (str): text in Houdini progress / interrupt dialog
        progress (callable, optional): returns progress 0..1 or None when unknown
    """
    log.info("%s: %s", label, subprocess.list2cmdline(cmd))
    # Output goes to a temp file, not a pipe: a full pipe buffer would block the process
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
        try:
            proc = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    **NO_WINDOW)
        except OSError as e:
            log.error("%s: can't start %s: %s", label, cmd[0], e)
            return Result(error=str(e))

        try:
            with hou.InterruptableOperation(label, open_interrupt_dialog=True) as operation:
                while proc.poll() is None:
                    fraction = progress() if progress else None
                    # updateProgress also raises OperationInterrupted when the user cancels
                    operation.updateProgress(min(max(fraction or 0.0, 0.0), 1.0))
                    time.sleep(POLL_SECONDS)
        except hou.OperationInterrupted:
            proc.kill()
            proc.wait()
            log.warning("%s: cancelled", label)
            return Result(returncode=proc.returncode, cancelled=True)

        output.seek(0)
        result = Result(returncode=proc.returncode, output=output.read())

    if not result.ok:
        log.error("%s failed with exit code %s:\n%s", label, result.returncode, result.tail())
    return result
