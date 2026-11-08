"""Frameless DinoWrite windows: rounded antialiased background and a draggable title bar."""
from . import widgets
from .qt import *  # noqa: F403
from .resources import Icons as _Icons
from .theme import COLORS, TITLE_BUTTON_SIZE, WINDOW_RADIUS

Icons = _Icons()


class RoundedWindow:
    """Mixin for QWidget/QDialog: transparent frameless window painting a rounded rect.

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


def _roundButton(icon: str, color: str, hover: str, icon_size: int = 0) -> QPushButton:
    button = widgets.PushButton()
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
        self.close_button.clicked.connect(on_close or window.close)
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
