"""Small progress window for a background conversion job (Houdini stays usable meanwhile)."""
import hou

from . import widgets
from .frameless import RoundedWindow, TitleBar
from .qt import *  # noqa: F403
from .theme import COLORS

WINDOW_WIDTH = 380
WINDOW_HEIGHT = 165
MARGIN = 20
POLL_MS = 200
OBJECT_NAME = "DinoWriteJobWindow"

PROGRESS_STYLE = f"""
QProgressBar {{
    background-color: {COLORS['grey-dark']};
    border: 1px solid #343434;
    border-radius: 4px;
    color: {COLORS['white']};
    text-align: center;
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 3px;
}}
"""


class JobWindow(RoundedWindow, QWidget):
    """Polls job.step() from a QTimer; Cancel stops the external processes.

    Args:
        job: ConversionJob-like object (start/step/cancel, progress, status, finished, succeeded, video)
        on_finished (callable, optional): called once when the job ends (any outcome)
    """

    def __init__(self, job, on_finished=None, parent=None):
        super().__init__(parent if parent is not None else hou.qt.mainWindow())
        self.job = job
        self.on_finished = on_finished
        self._notified = False

        # Tool window that doesn't steal focus. Stays on top: MPlay opens after the flipbook as a separate
        # application window over Houdini and would hide the progress otherwise
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setupRoundedWindow(OBJECT_NAME)
        self.setWindowTitle("DinoWrite - converting")

        title = TitleBar(self, "Converting to video", icon_size=30, title_size=11, on_close=self.close)
        self.name = widgets.Label(job.video.name, weight="bold")
        self.status = widgets.Label(job.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(PROGRESS_STYLE)

        self.button = widgets.PushButton("Cancel")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.cancelOrClose)

        frame = widgets.Frame(background_color=COLORS["grey"])
        body = QVBoxLayout(frame)
        body.setContentsMargins(10, 6, 10, 8)
        body.addWidget(self.name)
        body.addWidget(self.status)
        body.addWidget(self.bar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.addWidget(title)
        inner = QVBoxLayout()
        inner.setContentsMargins(10, 0, 10, 0)
        inner.addWidget(frame)
        inner.addWidget(self.button)
        layout.addLayout(inner)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.tick)

        self._placeCenter()
        self.show()
        self.timer.start()

    def _placeCenter(self):
        """Center of the Houdini window (where the user looks), other running jobs stacked below"""
        parent = self.parentWidget()
        if parent is None:
            return
        geometry = parent.frameGeometry()
        others = [w for w in parent.findChildren(QWidget) if w is not self and w.isVisible()
                  and w.objectName() == OBJECT_NAME]
        x = geometry.center().x() - WINDOW_WIDTH // 2
        y = geometry.center().y() - WINDOW_HEIGHT // 2 + (WINDOW_HEIGHT + MARGIN) * len(others)
        self.move(x, min(y, geometry.bottom() - WINDOW_HEIGHT))

    def tick(self):
        finished = self.job.step()
        self.status.setText(self.job.status)
        self.bar.setValue(int(self.job.progress * 1000))
        self._statusBar(finished)
        if finished:
            self._finished()

    def _statusBar(self, finished: bool):
        """Same progress in Houdini's status bar, visible even when the window is behind something"""
        try:
            severity = hou.severityType.Message
            if finished and not self.job.succeeded:
                severity = hou.severityType.Warning
            hou.ui.setStatusMessage(f"DinoWrite {self.job.video.name}: {self.job.status}", severity=severity)
        except Exception:  # status bar is a nicety, never break the job over it
            pass

    def _finished(self):
        self.timer.stop()
        self.button.setText("Close")
        color = COLORS["green"] if self.job.succeeded else COLORS["crimson"]
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setToolTip(getattr(self.job, "error", ""))
        if not self._notified:
            self._notified = True
            if self.on_finished is not None:
                # From the event loop, not from inside this tick: opening the result may take a moment
                QTimer.singleShot(0, self.on_finished)
        if self.job.succeeded:
            self.close()  # the result opens right away, nothing to read here; failures stay open

    def cancelOrClose(self):
        if self.job.finished:
            self.close()
        else:
            self.job.cancel()
            self.tick()

    def closeEvent(self, event):
        # Closing the window while converting cancels the job: nothing keeps running unseen
        if not self.job.finished:
            self.job.cancel()
            self.tick()
        self.timer.stop()
        super().closeEvent(event)
