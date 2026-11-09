"""HotBox style animations: hover wave/zoom painted by the window overlay, press grows and fades"""
import pytest

pytest.importorskip("PySide6.QtWidgets")
from conftest import waitUntil  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402


@pytest.fixture
def window(houdini):
    import DinoWrite

    win = DinoWrite.show({})
    yield win
    win.close()


def test_window_fades_in(window):
    assert waitUntil(lambda: window.windowOpacity() == 1.0)


def test_hover_zooms_button_over_its_neighbours(window):
    button = window.writebutton
    rect = button.geometry()
    outside = rect.topLeft() + type(rect.topLeft())(-3, rect.height() // 2)  # just left of the button
    before = window.grab().toImage().pixelColor(outside)

    button.startHover(QPointF(10, 10))
    assert waitUntil(lambda: button.hover == 1.0 and button.ripple == 1.0)
    assert button.isAnimated() and button.scale() > 1.0
    image = window.grab().toImage()
    import os
    if os.environ.get("DINOWRITE_SHOTS"):
        image.save(os.path.join(os.environ["DINOWRITE_SHOTS"], "hover.png"))
    assert image.pixelColor(outside) != before, "zoomed button is painted over the space around it"

    button.endHover()
    assert waitUntil(lambda: button.hover == 0.0)
    assert not button.isAnimated()


def test_press_grows_and_fades_out(window):
    done = []
    window.writebutton.playPress(lambda: done.append(True))
    assert waitUntil(lambda: done == [True])
    assert window.writebutton.press == 1.0 and window.writebutton.scale() > 1.05


def test_close_button_fades_out_then_closes(window):
    title_close = [b for b in window.findChildren(type(window.writebutton)) if b.toolTip() == "Close"][0]
    title_close.click()
    assert window.isVisible(), "fading out first"
    assert waitUntil(lambda: not window.isVisible())


def test_stagger_text_shake_hop_end_where_they_started(houdini):
    from PySide6.QtWidgets import QLabel, QWidget

    from DinoWrite.gui import animation
    from conftest import waitUntil

    parent = QWidget()
    parent.resize(200, 100)
    label = QLabel("a", parent)
    label.move(10, 20)
    parent.show()
    animation.stagger([label])
    animation.setTextAnimated(label, "b")
    assert label.text() == "b"
    assert waitUntil(lambda: label.graphicsEffect() is None), "effects are removed when done"
    assert label.pos().x() == 10 and label.pos().y() == 20
    animation.shake(label)
    animation.shake(label)  # again while shaking: still comes back to the same place
    animation.hop(label)
    assert waitUntil(lambda: not animation._running(label, "shake") and not animation._running(label, "hop"))
    assert label.pos().x() == 10 and label.pos().y() == 20
    parent.close()


def test_checkbox_flashes_on_toggle_not_on_open(houdini):
    from DinoWrite.gui import widgets
    from conftest import waitUntil

    box = widgets.CheckBox("x", default=True)
    box.setChecked(False)  # loading values before the window is shown
    assert box.flash == 0.0, "no flash for the initial state"
    box.show()
    box.setChecked(True)
    assert waitUntil(lambda: box.flash > 0)
    assert waitUntil(lambda: box.flash == 0.0)
