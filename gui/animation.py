"""Animations in the HotBox style.

- windows fade in when shown, fade out when closed with the title bar button
- buttons: on hover a white wave spreads from the cursor, the button gets lighter and a bit bigger;
  playPress() grows and fades the button out (WRITE: together with the window, then recording starts)

Buttons keep their stylesheet look: the styled button is rendered into a pixmap and the window's
AnimationOverlay paints it scaled on top of everything, so the zoom isn't cut by the layout.
"""
import math

from .qt import *  # noqa: F403

FADE_IN_MS = 180
FADE_OUT_MS = 220
HOVER_MS, RIPPLE_MS, PRESS_MS = 150, 450, 220
HOVER_SCALE, PRESS_SCALE = 1.07, 1.19  # small buttons, as in HotBox
HOVER_GROW_PX, PRESS_GROW_PX = 6, 24  # at most per side: a wide WRITE button doesn't fill the window
HOVER_WHITE = 0.08  # white over the button on hover
RIPPLE_ALPHA = 0.35


def _animation(owner, duration: int, curve, on_value) -> QVariantAnimation:
    animation = QVariantAnimation(owner)
    animation.setDuration(duration)
    animation.setEasingCurve(curve)
    animation.valueChanged.connect(lambda value: on_value(float(value)))
    return animation


def _run(animation: QVariantAnimation, start: float, end: float):
    animation.stop()
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.start()


def _eventPos(event) -> QPointF:
    if hasattr(event, "position"):  # Qt6
        return QPointF(event.position())
    if hasattr(event, "pos"):
        return QPointF(event.pos())
    return QPointF()


class FadingWindow:
    """Mixin for top level windows: fade in on show, fadeClose() fades out and closes"""

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_faded_in", False):
            self._faded_in = True
            self._fade(0.0, 1.0, FADE_IN_MS)

    def _fade(self, start: float, end: float, duration: int, finished=None):
        self.setWindowOpacity(start)
        self._fadeAnimation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fadeAnimation.setDuration(duration)
        self._fadeAnimation.setStartValue(start)
        self._fadeAnimation.setEndValue(end)
        self._fadeAnimation.setEasingCurve(QEasingCurve.OutCubic)
        if finished is not None:
            self._fadeAnimation.finished.connect(finished)
        self._fadeAnimation.start()

    def fadeOut(self, finished=None, duration: int = FADE_OUT_MS):
        self._fade(self.windowOpacity(), 0.0, duration, finished)

    def fadeClose(self):
        self.fadeOut(self.close)

    def animationOverlay(self):
        overlay = getattr(self, "_animationOverlay", None)
        if overlay is None:
            overlay = self._animationOverlay = AnimationOverlay(self)
        return overlay


class AnimatedButton:
    """Mixin for QPushButton subclasses. Call setupAnimation() in __init__."""

    def setupAnimation(self, radius: float = 5):
        self.radius = radius
        self.hover = 0.0
        self.ripple = 1.0  # 1: finished
        self.press = 0.0
        self.ripplePos = QPointF()
        self._snapshot = False
        self._hoverAnimation = _animation(self, HOVER_MS, QEasingCurve.OutCubic, self._setter("hover"))
        self._rippleAnimation = _animation(self, RIPPLE_MS, QEasingCurve.OutQuad, self._setter("ripple"))
        self._pressAnimation = _animation(self, PRESS_MS, QEasingCurve.OutCubic, self._setter("press"))
        self.setAttribute(Qt.WA_Hover)

    def _setter(self, attribute: str):
        def apply(value):
            setattr(self, attribute, value)
            self._repaint()
        return apply

    def _overlay(self):
        window = self.window()
        return window.animationOverlay() if hasattr(window, "animationOverlay") else None

    def _repaint(self):
        self.update()
        overlay = self._overlay()
        if overlay is not None:
            overlay.follow()

    def scale(self) -> float:
        size = max(self.width(), self.height(), 1)
        hover_max = min(HOVER_SCALE, 1 + 2 * HOVER_GROW_PX / size)
        press_max = min(PRESS_SCALE, 1 + 2 * PRESS_GROW_PX / size)
        hover_scale = 1 + (hover_max - 1) * self.hover
        return hover_scale + (press_max - hover_scale) * self.press

    def isAnimated(self) -> bool:
        return self.isVisible() and (self.scale() > 1.0005 or self.press > 0 or self.ripple < 1.0)

    # --- painting ---

    def paintEvent(self, event):
        if not self._snapshot and self.isAnimated() and self._overlay() is not None:
            return  # the overlay paints the zoomed button
        super().paintEvent(event)
        if self.hover > 0 or self.ripple < 1.0:
            painter = QPainter(self)
            self._paintEffects(painter)
            painter.end()

    def _paintEffects(self, painter: QPainter):
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipPath(path)
        if self.hover > 0:
            painter.fillRect(rect, QColor(255, 255, 255, int(255 * HOVER_WHITE * self.hover)))
        if self.ripple < 1.0:  # white wave from the cursor
            radius = max(1.0, math.hypot(rect.width(), rect.height()) * self.ripple)
            alpha = RIPPLE_ALPHA * (1.0 - self.ripple)
            gradient = QRadialGradient(self.ripplePos, radius)
            gradient.setColorAt(0.0, QColor(255, 255, 255, int(255 * alpha * 0.35)))
            gradient.setColorAt(0.8, QColor(255, 255, 255, int(255 * alpha)))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(rect, gradient)

    def snapshot(self) -> QPixmap:
        """The button as it looks now (stylesheet + hover effects), unscaled"""
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(self.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        self._snapshot = True
        try:
            self.render(pixmap, QPoint(), QRegion(), QWidget.DrawChildren)
        finally:
            self._snapshot = False
        return pixmap

    def paintTo(self, painter: QPainter, top_left: QPointF):
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(1.0 - self.press)
        center = top_left + QPointF(self.width() / 2, self.height() / 2)
        painter.translate(center)
        painter.scale(self.scale(), self.scale())
        painter.translate(-center)
        painter.drawPixmap(top_left, self.snapshot())
        painter.restore()

    # --- animation ---

    def startHover(self, pos: QPointF = None):
        self.ripplePos = pos if pos is not None else QPointF(self.width() / 2, self.height() / 2)
        _run(self._rippleAnimation, 0.0, 1.0)
        _run(self._hoverAnimation, self.hover, 1.0)

    def endHover(self):
        _run(self._hoverAnimation, self.hover, 0.0)

    def playPress(self, finished=None):
        """Grow and fade out; finished() is called at the end"""
        if finished is not None:
            self._pressAnimation.finished.connect(finished)
        _run(self._pressAnimation, 0.0, 1.0)

    def enterEvent(self, event):
        if self.isEnabled():
            self.startHover(_eventPos(event))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.endHover()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.ripplePos = _eventPos(event)
        _run(self._rippleAnimation, 0.0, 1.0)  # a wave from the click point
        super().mousePressEvent(event)


class AnimationOverlay(QWidget):
    """Transparent layer over the whole window painting the zoomed (hovered/pressed) buttons on top"""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setGeometry(window.rect())
        self.show()

    def follow(self):
        """Cover the whole window, above widgets added after the overlay, and repaint"""
        window = self.parentWidget()
        if self.geometry() != window.rect():
            self.setGeometry(window.rect())
        self.raise_()
        self.update()

    def paintEvent(self, event):
        window = self.parentWidget()
        buttons = [b for b in window.findChildren(QPushButton)
                   if isinstance(b, AnimatedButton) and b.isAnimated() and b.window() is window]
        if not buttons:
            return
        painter = QPainter(self)
        for button in sorted(buttons, key=lambda b: (b.press, b.hover)):  # the pressed one on top
            button.paintTo(painter, QPointF(button.mapTo(window, QPoint(0, 0))))
        painter.end()
