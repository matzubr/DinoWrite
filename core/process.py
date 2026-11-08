"""Run external tools (ffmpeg, hoiiotool) without blocking Houdini.

Processes runs a group of commands in parallel and is polled (no threads: hou isn't thread safe,
the GUI polls from a QTimer). run() is the blocking variant with Houdini progress/cancel,
used when there's no UI (hython).
"""
import subprocess
import sys
import tempfile
import time

import hou

from .log import log

POLL_SECONDS = 0.2
OUTPUT_TAIL_LINES = 15

# Houdini is a GUI app: on Windows every console tool started from it pops up its own console window
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class Result:
    """Outcome of external processes. Truthy only when they finished successfully."""

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


class Processes:
    """A group of commands running in parallel. Poll it until it returns a Result."""

    def __init__(self, cmds: list, label: str):
        self.label = label
        self._procs = []
        self._outputs = []
        self._result = None
        for cmd in cmds:
            log.info("%s: %s", label, subprocess.list2cmdline(cmd))
            # Output goes to a temp file, not a pipe: a full pipe buffer would block the process
            output = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            try:
                proc = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, **NO_WINDOW)
            except OSError as e:
                output.close()
                log.error("%s: can't start %s: %s", label, cmd[0], e)
                self.kill()
                self._result = Result(error=str(e))
                return
            self._procs.append(proc)
            self._outputs.append(output)

    def poll(self):
        """None while running, Result when every process has finished (or one failed)"""
        if self._result is not None:
            return self._result
        codes = [proc.poll() for proc in self._procs]
        failed = [code for code in codes if code not in (None, 0)]
        if failed:
            self.kill()  # one chunk failed: the rest is useless
        elif any(code is None for code in codes):
            return None
        self._result = Result(returncode=failed[0] if failed else 0, output=self._readOutput())
        if not self._result:
            log.error("%s failed with exit code %s:\n%s", self.label, self._result.returncode, self._result.tail())
        return self._result

    def cancel(self) -> Result:
        self.kill()
        self._result = Result(cancelled=True, output=self._readOutput())
        log.warning("%s: cancelled", self.label)
        return self._result

    def kill(self):
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def _readOutput(self) -> str:
        texts = []
        for output in self._outputs:
            output.seek(0)
            texts.append(output.read())
            output.close()
        self._outputs = []
        return "\n".join(texts)


def run(cmd: list, label: str, progress=None) -> Result:
    """Run cmd blocking, with Houdini progress; the user can cancel it (Esc / interrupt dialog).

    Args:
        cmd (list): argv
        label (str): text in Houdini progress / interrupt dialog
        progress (callable, optional): returns progress 0..1 or None when unknown
    """
    return wait(Processes([cmd], label), label, progress)


def wait(processes, label: str, progress=None) -> Result:
    """Block until processes finish, showing Houdini progress. Works without UI too."""
    try:
        with hou.InterruptableOperation(label, open_interrupt_dialog=True) as operation:
            while (result := processes.poll()) is None:
                fraction = progress() if progress else None
                # updateProgress also raises OperationInterrupted when the user cancels
                operation.updateProgress(min(max(fraction or 0.0, 0.0), 1.0))
                time.sleep(POLL_SECONDS)
    except hou.OperationInterrupted:
        return processes.cancel()
    return result
