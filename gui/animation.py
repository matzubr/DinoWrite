"""Animations in the HotBox style.

- windows fade in when shown, fade out when closed with the title bar button
- buttons: on hover a white wave spreads from the cursor, the button gets lighter and a bit bigger;
  playPress() grows and fades the button out (WRITE: together with the window, then recording starts)
- window parts come in one after another (stagger), changed info text blinks in (refreshText),
  a wrong field shakes, the dino hops, menus fade in, checkboxes glow on hover and flash on toggle

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
STAGGER_MS, STAGGER_STEP_MS, STAGGER_SLIDE_PX = 260, 55, 10
TEXT_MS, SHAKE_MS, HOP_MS, MENU_MS = 260, 320, 420, 140
CHECK_HOVER_MS, CHECK_FLASH_MS = 160, 380
ACCENT = QColor(183, 134, 32)


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


# --- one-shot animations for any widget ---

def _keep(widget, animation):
    """Keep a running animation alive (and replace the previous one of the same kind)"""
    name = f"_anim_{animation.objectName() or 'default'}"
    old = getattr(widget, name, None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:  # already deleted
            pass
    setattr(widget, name, animation)
    animation.start()


def _opacity(widget) -> QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    return effect


def _running(widget, name: str) -> bool:
    animation = getattr(widget, f"_anim_{name}", None)
    try:
        return animation is not None and animation.state() == QAbstractAnimation.Running
    except RuntimeError:  # deleted
        return False


def _dropEffect(widget):
    """Opacity effect off when no fade uses it anymore: it renders the widget offscreen (slower, blurry on HiDPI)"""
    if _running(widget, "stagger") or _running(widget, "text"):
        return
    try:
        widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def stagger(widgets, step: int = STAGGER_STEP_MS, slide: int = STAGGER_SLIDE_PX):
    """Window parts come in one after another: fade in, slide up a few pixels. Call after layout (shown)."""
    for index, widget in enumerate(widgets):
        effect = _opacity(widget)
        effect.setOpacity(0.0)
        group = QSequentialAnimationGroup(widget)
        group.setObjectName("stagger")
        group.addPause(index * step)
        both = QParallelAnimationGroup()
        fade = QPropertyAnimation(effect, b"opacity")
        fade.setDuration(STAGGER_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        both.addAnimation(fade)
        if slide:
            move = QPropertyAnimation(widget, b"pos")
            move.setDuration(STAGGER_MS)
            move.setStartValue(widget.pos() + QPoint(0, slide))
            move.setEndValue(widget.pos())
            move.setEasingCurve(QEasingCurve.OutCubic)
            both.addAnimation(move)
        group.addAnimation(both)
        group.finished.connect(lambda w=widget: _dropEffect(w))
        _keep(widget, group)


def refreshText(label):
    """Changed text blinks in"""
    if _running(label, "stagger"):
        return
    effect = _opacity(label)
    fade = QPropertyAnimation(effect, b"opacity", label)
    fade.setObjectName("text")
    fade.setDuration(TEXT_MS)
    fade.setStartValue(0.25)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.OutCubic)
    fade.finished.connect(lambda: _dropEffect(label))
    _keep(label, fade)


def setTextAnimated(label, text: str):
    """setText, with refreshText() when the text really changes"""
    if label.text() != text:
        label.setText(text)
        if label.isVisible():
            refreshText(label)


def _keyframes(widget, name: str, duration: int, offsets, curve=QEasingCurve.Linear):
    """Move the widget through offsets (QPoint) from its place and back.

    When the layout moves the widget meanwhile (the dino, when a longer name pushes it), that's its new
    place: the move goes on from there and ends there, not where it started.
    """
    moving = any(_running(widget, kind) for kind in ("shake", "hop"))
    for kind in ("shake", "hop"):
        if _running(widget, kind):
            getattr(widget, f"_anim_{kind}").stop()
    if not moving or getattr(widget, "_anim_home", None) is None:
        widget._anim_home = widget.pos()
        widget._anim_last = widget.pos()  # a layout move before the first frame counts too

    def apply(offset):
        position = widget.pos()
        if position != widget._anim_last:
            widget._anim_home = position  # placed by the layout since the last frame
        widget._anim_last = widget._anim_home + offset
        widget.move(widget._anim_last)

    move = QVariantAnimation(widget)
    move.setObjectName(name)
    move.setDuration(duration)
    move.setEasingCurve(curve)
    move.setStartValue(QPoint(0, 0))
    count = len(offsets) + 1
    for index, offset in enumerate(offsets, 1):
        move.setKeyValueAt(index / count, offset)
    move.setEndValue(QPoint(0, 0))
    move.valueChanged.connect(apply)
    move.finished.connect(lambda: apply(QPoint(0, 0)))
    _keep(widget, move)


def shake(widget):
    """Something is wrong here: a short horizontal shake"""
    _keyframes(widget, "shake", SHAKE_MS, [QPoint(dx, 0) for dx in (-6, 5, -4, 3, -2)])


def hop(widget):
    """A little jump (the dino, when the flipbook name changes)"""
    _keyframes(widget, "hop", HOP_MS, [QPoint(0, -7), QPoint(0, -2), QPoint(0, -3)], QEasingCurve.OutQuad)


def fadeMenus(menu):
    """QMenu fades in when it opens"""
    def opened():
        menu.setWindowOpacity(0.0)
        fade = QPropertyAnimation(menu, b"windowOpacity", menu)
        fade.setObjectName("menu")
        fade.setDuration(MENU_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        _keep(menu, fade)
    menu.aboutToShow.connect(opened)


class AnimatedCheckBox:
    """Mixin for QCheckBox subclasses: accent glow fades in on hover, flashes on toggle.

    Call setupAnimation() in __init__; the stylesheet must not set a :hover background.
    """

    def setupAnimation(self, radius: float = 4):
        self.radius = radius
        self.hover = 0.0
        self.flash = 0.0
        self._hoverAnimation = _animation(self, CHECK_HOVER_MS, QEasingCurve.OutCubic, self._set("hover"))
        self._flashAnimation = _animation(self, CHECK_FLASH_MS, QEasingCurve.OutCubic, self._set("flash"))
        self.setAttribute(Qt.WA_Hover)
        self.toggled.connect(self._flashOnToggle)

    def _flashOnToggle(self, _checked):
        if self.isVisible():  # not when a dialog loads its values before showing
            _run(self._flashAnimation, 1.0, 0.0)

    def _set(self, attribute: str):
        def apply(value):
            setattr(self, attribute, value)
            self.update()
        return apply

    def paintEvent(self, event):
        alpha = 0.20 * self.hover + 0.35 * self.flash
        if alpha > 0 and self.isEnabled():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            color = QColor(ACCENT)
            color.setAlphaF(min(alpha, 1.0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(self.rect()), self.radius, self.radius)
            painter.end()
        super().paintEvent(event)

    def enterEvent(self, event):
        if self.isEnabled():
            _run(self._hoverAnimation, self.hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        _run(self._hoverAnimation, self.hover, 0.0)
        super().leaveEvent(event)
