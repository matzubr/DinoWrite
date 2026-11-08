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
AUTO_CLOSE_MS = 5000
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

        # Tool window: stays above Houdini, doesn't steal focus from the viewport
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
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

        self._placeBottomRight()
        self.show()
        self.timer.start()

    def _placeBottomRight(self):
        """Bottom right corner of the Houdini window, stacked above other running jobs"""
        parent = self.parentWidget()
        if parent is None:
            return
        geometry = parent.frameGeometry()
        others = [w for w in parent.findChildren(JobWindow) if w is not self and w.isVisible()]
        x = geometry.right() - WINDOW_WIDTH - MARGIN
        y = geometry.bottom() - (WINDOW_HEIGHT + MARGIN) * (len(others) + 1) - MARGIN
        self.move(max(geometry.left(), x), max(geometry.top(), y))

    def tick(self):
        finished = self.job.step()
        self.status.setText(self.job.status)
        self.bar.setValue(int(self.job.progress * 1000))
        if finished:
            self._finished()

    def _finished(self):
        self.timer.stop()
        self.button.setText("Close")
        color = COLORS["green"] if self.job.succeeded else COLORS["crimson"]
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setToolTip(getattr(self.job, "error", ""))
        if self.job.succeeded:
            self.bar.setValue(1000)
            QTimer.singleShot(AUTO_CLOSE_MS, self.close)
        if not self._notified:
            self._notified = True
            if self.on_finished is not None:
                self.on_finished()

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
