"""Background conversion progress window (offscreen PySide6)"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402
from conftest import waitUntil  # noqa: E402


class FakeJob:
    def __init__(self, steps=3):
        self.steps_left = steps
        self.video = Path("/tmp/shot.v001.mov")
        self.title = self.video.name
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
        try:
            window.deleteLater()
        except RuntimeError:  # closed on success, already deleted
            pass


def test_progress_and_single_finish_callback(make_window):
    calls = []
    job = FakeJob()
    window = make_window(job, on_finished=lambda: calls.append("done"))
    assert window.isVisible() and window.name.text() == "shot.v001.mov"

    window.tick()
    assert window.status.text() == "Encoding 33%"
    assert waitUntil(lambda: window.bar.value() == 333), "the bar glides to the progress"
    window.tick()
    window.tick()
    window.tick()
    assert window.status.text() == "Done"
    assert calls == []  # deferred to the event loop
    QApplication.processEvents()
    assert calls == ["done"]
    assert waitUntil(lambda: not window.isVisible())  # fades out and closes at once on success


def test_cancel_button_stops_job(make_window):
    calls = []
    job = FakeJob(steps=100)
    window = make_window(job, on_finished=lambda: calls.append("finished"))
    window.button.click()
    assert job.cancelled and window.status.text() == "Cancelled"
    QApplication.processEvents()
    assert calls == ["finished"]


def test_closing_window_cancels_running_job(make_window):
    job = FakeJob(steps=100)
    window = make_window(job)
    window.close()
    assert job.cancelled


def test_window_is_centered_and_jobs_stack_below(make_window, houdini):
    houdini.setGeometry(0, 0, 1600, 1000)
    first = make_window(FakeJob())
    second = make_window(FakeJob())
    center = houdini.frameGeometry().center()
    assert abs(first.geometry().center().x() - center.x()) <= 2
    assert abs(first.geometry().center().y() - center.y()) <= 2
    assert second.y() > first.y()


def test_progress_window_stays_on_top_and_reports_to_status_bar(make_window, hou, monkeypatch):
    from types import SimpleNamespace

    from DinoWrite.gui.qt import Qt

    messages = []
    monkeypatch.setattr(hou, "ui", SimpleNamespace(setStatusMessage=lambda text, severity=None: messages.append(text)),
                        raising=False)
    window = make_window(FakeJob())
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    window.tick()
    assert messages == ["DinoWrite shot.v001.mov: Encoding 33%"]
