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
