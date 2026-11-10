"""Frameless DinoWrite windows: rounded antialiased background and a draggable title bar."""
from . import widgets
from .animation import FadingWindow
from .qt import *  # noqa: F403
from .resources import Icons as _Icons
from .theme import COLORS, TITLE_BUTTON_SIZE, WINDOW_RADIUS

Icons = _Icons()


class RoundedWindow(FadingWindow):
    """Mixin for QWidget/QDialog: transparent frameless window painting a rounded rect, fades in/out.

    A setMask() region is 1-bit and gives jagged edges, so the window is translucent and
    paints an antialiased rounded rect itself. Children keep the background color via stylesheet.
    Call setupRoundedWindow() in __init__ after setting window flags.
    """

    def setupRoundedWindow(self, object_name: str, extra_style: str = ""):
        self.setObjectName(object_name)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(f"background-color:{COLORS['grey-bright']};"
                           f"QWidget#{object_name} {{background-color: transparent;}}" + extra_style)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["grey-bright"]))
        painter.drawRoundedRect(QRectF(self.rect()), WINDOW_RADIUS, WINDOW_RADIUS)
        painter.end()


class WidthResizable:
    """Mixin: drag the left/right edge of a frameless window to change its width (the height follows the content).
    Call setupWidthResize(minimum, maximum, on_resized) in __init__; on_resized() runs when the drag ends."""
    RESIZE_EDGE = 8  # px from the window edge where the drag starts

    def setupWidthResize(self, minimum: int, maximum: int, on_resized=None):
        self._width_range = (minimum, maximum)
        self._on_resized = on_resized
        self._resize_drag = None
        self.setMouseTracking(True)

    def _resizeEdge(self, pos) -> int:
        """-1 left edge, 1 right edge, 0 elsewhere"""
        if pos.x() <= self.RESIZE_EDGE:
            return -1
        if pos.x() >= self.width() - self.RESIZE_EDGE:
            return 1
        return 0

    def setWidthClamped(self, width: int) -> int:
        minimum, maximum = self._width_range
        width = int(min(max(width, minimum), maximum))
        self.setFixedWidth(width)
        return width

    def mousePressEvent(self, event):
        edge = self._resizeEdge(event.position().toPoint() if hasattr(event, "position") else event.pos())
        if event.button() == Qt.LeftButton and edge:
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self._resize_drag = (edge, pos.x(), self.width(), self.x())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_drag:
            edge, start, width, x = self._resize_drag
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            new_width = self.setWidthClamped(width + (pos.x() - start) * edge)
            if edge < 0:  # the right edge stays in place
                self.move(x + width - new_width, self.y())
            return
        local = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._resizeEdge(local):
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_drag:
            self._resize_drag = None
            if self._on_resized:
                self._on_resized()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resize_drag:
            self.unsetCursor()
        super().leaveEvent(event)


def _roundButton(icon: str, color: str, hover: str, icon_size: int = 0) -> QPushButton:
    button = widgets.PushButton(radius=TITLE_BUTTON_SIZE / 2)
    button.setFixedSize(TITLE_BUTTON_SIZE, TITLE_BUTTON_SIZE)
    button.setIcon(Icons.get(icon))
    if icon_size:
        button.setIconSize(QSize(icon_size, icon_size))
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(f"QPushButton {{background-color:{color}; border-radius: {TITLE_BUTTON_SIZE // 2}px;}}"
                         f"QPushButton::hover {{background-color:{hover};}}")
    return button


class TitleBar(QWidget):
    """Dino icon, title (drag the window by it), optional settings button and close button"""

    def __init__(self, window, title: str, icon_size: int = 40, title_size: int = 14,
                 title_width: int = 0, on_settings=None, on_close=None):
        super().__init__()
        self.window_ = window

        icon = widgets.HIcon(Icons.getRandom(type="Path"), size=icon_size)
        self.title = widgets.Label(title, size=title_size)
        if title_width:
            self.title.setMaximumWidth(title_width)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"background-color:{COLORS['grey']}; border-radius: 10px; color:{COLORS['white']};")
        self.title.setCursor(Qt.OpenHandCursor)

        items = [icon, self.title]
        if on_settings is not None:
            self.settings_button = _roundButton("gear.svg", COLORS["grey"], COLORS["orange"], icon_size=14)
            self.settings_button.setToolTip("Settings")
            self.settings_button.clicked.connect(on_settings)
            items.append(self.settings_button)
        self.close_button = _roundButton("close.svg", COLORS["crimson"], COLORS["red"])
        self.close_button.setToolTip("Close")
        self.close_button.clicked.connect(on_close or getattr(window, "fadeClose", window.close))
        items.append(self.close_button)

        layout = widgets.HLayout(items, align=None)
        layout.setContentsMargins(15, 10, 15, 3)
        self.setLayout(layout)
        self._drag_offset = None

    def mousePressEvent(self, event):
        self._drag_offset = self.mapToGlobal(event.pos()) - self.window_.pos()
        self.title.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.window_.move(self.mapToGlobal(event.pos()) - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self.title.setCursor(Qt.OpenHandCursor)
