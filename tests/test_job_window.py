"""Background conversion progress window (offscreen PySide6)"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")


class FakeJob:
    def __init__(self, steps=3):
        self.steps_left = steps
        self.video = Path("/tmp/shot.v001.mov")
        self.finished = self.succeeded = self.cancelled = False
        self.progress = 0.0
        self.error = ""

    @property
    def status(self):
        return "Cancelled" if self.cancelled else ("Done" if self.succeeded else f"Encoding {self.progress:.0%}")

    def step(self):
        if not self.finished:
            self.steps_left -= 1
            self.progress = 1 - self.steps_left / 3
            if self.steps_left <= 0:
                self.finished = self.succeeded = True
        return self.finished

    def cancel(self):
        self.finished, self.cancelled = True, True


@pytest.fixture
def make_window(houdini):
    from DinoWrite.gui.job_window import JobWindow

    windows = []

    def make(job, **kwargs):
        window = JobWindow(job, parent=houdini, **kwargs)
        window.timer.stop()  # drive ticks by hand
        windows.append(window)
        return window
    yield make
    for window in windows:
        window.deleteLater()


def test_progress_and_single_finish_callback(make_window):
    calls = []
    job = FakeJob()
    window = make_window(job, on_finished=lambda: calls.append("done"))
    assert window.isVisible() and window.name.text() == "shot.v001.mov"

    window.tick()
    assert window.bar.value() == 333 and window.status.text() == "Encoding 33%"
    window.tick()
    window.tick()
    window.tick()
    assert window.status.text() == "Done" and window.button.text() == "Close"
    assert calls == ["done"]


def test_cancel_button_stops_job(make_window):
    calls = []
    job = FakeJob(steps=100)
    window = make_window(job, on_finished=lambda: calls.append("finished"))
    window.button.click()
    assert job.cancelled and window.status.text() == "Cancelled"
    assert calls == ["finished"]


def test_closing_window_cancels_running_job(make_window):
    job = FakeJob(steps=100)
    window = make_window(job)
    window.close()
    assert job.cancelled


def test_windows_stack_above_each_other(make_window):
    first = make_window(FakeJob())
    second = make_window(FakeJob())
    assert second.y() < first.y()
