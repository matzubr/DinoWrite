"""README images, rendered offscreen with the real widgets.

    uv run --with pillow python docs/make_images.py

hou is stubbed like in the tests; the viewer, tools and paths are fakes, so no personal paths get into the images.
"""
import random
import sys
import tempfile
import types
from pathlib import Path

from PIL import Image

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
sys.path.insert(0, (ROOT / "tests").as_posix())
import conftest  # noqa: F401,E402  (hou stub, offscreen Qt, DinoWrite on sys.path)
from PySide6 import QtWidgets  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, QSize  # noqa: E402
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

BACKGROUND = QColor("#262626")
FRAME_MS = 33
PREF_DIR = "C:/Users/artist/Documents/houdini21.0"


def onBackground(widget, pad: int = 16) -> QPixmap:
    image = widget.grab()
    result = QPixmap(image.size() + QSize(2 * pad, 2 * pad))
    result.fill(BACKGROUND)
    painter = QPainter(result)
    painter.drawPixmap(pad, pad, image)
    painter.end()
    return result


def stopFade(window):
    animation = getattr(window, "_fadeAnimation", None)
    if animation is not None:
        animation.stop()
    window.setWindowOpacity(1)


def fakeHoudini(temp: Path):
    """Houdini session for the screenshots: $HIP with a preview folder, a viewer with a camera, found tools"""
    hou = sys.modules["hou"]
    main_window = QtWidgets.QWidget()
    hip = temp / "hip"
    hip.mkdir()
    (temp / "preview").mkdir()
    variables = {"$HIP": hip.as_posix()}

    def expand(text):
        for key, value in variables.items():
            text = text.replace(key, value)
        return text

    hou.text = types.SimpleNamespace(expandString=expand)
    hou.qt = types.SimpleNamespace(mainWindow=lambda: main_window)
    hou.getenv = lambda name, default=None: PREF_DIR if name == "HOUDINI_USER_PREF_DIR" else default
    hou.fps = lambda: 24.0

    from DinoWrite.core import acescg, ffmpeg, helpers, viewport

    viewer = types.SimpleNamespace(cameraName=lambda: "shotCam", cameraPixelAspect=lambda: 1.0,
                                   cameraResolution=lambda: (3840, 2160), cameraAspect=lambda: 16 / 9,
                                   getPaneTab=lambda: types.SimpleNamespace(qtScreenGeometry=lambda: 1 / 0))
    viewport.HouViewport.__init__ = lambda self, kwargs: self.__dict__.update(viewer.__dict__)
    ffmpeg.findFFmpeg = lambda custom="": "$HFS/bin/hffmpeg"
    ffmpeg.availableEncoders = lambda binary: {"h264_mf", "h264_nvenc", "mpeg4"}
    acescg.findOiiotool = lambda custom="": "$HFS/bin/hoiiotool"
    acescg.oiiotoolVersion = lambda tool: ()
    helpers.freeSpace = lambda path: 512 * 1024 ** 3
    return main_window


class FakeJob:
    """Conversion in the middle of EXR -> ACEScg, for the progress window"""
    title = "shot_010.v003.mov"
    status = "EXR -> ACEScg, DWAA: 42/100 frames"
    progress = 0.42
    finished = succeeded = False
    error = ""

    def step(self):
        return False

    def cancel(self):
        pass


def main():
    random.seed(7)  # title bar dino is random
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory() as temp:
        main_window = fakeHoudini(Path(temp))
        import DinoWrite
        from DinoWrite.gui.job_window import JobWindow
        from DinoWrite.gui.settings_dialog import SettingsDialog

        window = DinoWrite.show({})
        stopFade(window)
        QTest.qWait(900)  # parts of the window come in one after another
        window.filename.setText("shot_010")
        window.resx.setText("3840")
        window.resy.setText("2160")
        window.framestart.setText("1001")
        window.frameend.setText("1100")
        window.convertvideo.setChecked(True)
        for update in (window.updateRamUsage, window.updateColorfulLabel, window.updateStatus):
            update()
        QTest.qWait(600)  # changed text blinks in
        onBackground(window).save((DOCS / "dinowrite.png").as_posix())

        # Animation: hover a menu button, toggle a checkbox, new name (dino hops), then WRITE
        frames = []

        def record(count: int, wait: bool = True):
            for _ in range(count):
                if wait:
                    QTest.qWait(FRAME_MS)
                app.processEvents()
                frames.append(onBackground(window).toImage())

        record(4, wait=False)
        window.res_menu.startHover(QPointF(6, 6))
        record(12)
        window.res_menu.endHover()
        window.convertvideo.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        record(6)
        window.convertvideo.setChecked(False)
        record(10)
        window.convertvideo.leaveEvent(QEvent(QEvent.Leave))
        window.filename.setText("shot_020")
        window.updateColorfulLabel()
        record(14)
        window.writebutton.startHover(QPointF(90, 20))
        record(18)
        window.writebutton.endHover()
        record(8)
        record(4, wait=False)
        saveGif(frames, DOCS / "dinowrite_animation.gif")

        # Resolution with another aspect than the camera: orange warning in the status line
        window.resy.setText("1600")
        window.updateRamUsage()
        window.updateStatus()
        QTest.qWait(600)
        onBackground(window.statusline.parentWidget(), pad=8).save((DOCS / "aspect_warning.png").as_posix())
        window.close()

        from DinoWrite.gui import settings_dialog
        settings_dialog.expand = lambda path: path.replace("$HIP", "C:/projects/sh010/houdini")  # not the temp folder
        dialog = SettingsDialog()
        stopFade(dialog)
        dialog.show()
        QTest.qWait(700)
        onBackground(dialog).save((DOCS / "settings.png").as_posix())
        dialog.showPage(1)
        QTest.qWait(700)  # the page's sections come in
        onBackground(dialog).save((DOCS / "settings_video.png").as_posix())
        dialog.close()

        progress = JobWindow(FakeJob(), parent=main_window)
        progress.timer.stop()
        stopFade(progress)
        progress.tick()
        app.processEvents()
        onBackground(progress).save((DOCS / "progress.png").as_posix())
        progress.close()
    print("docs images updated")


def saveGif(frames, path: Path):
    with tempfile.TemporaryDirectory() as folder:
        images = []
        for index, frame in enumerate(frames):
            png = Path(folder, f"{index:03d}.png")
            frame.save(png.as_posix())
            image = Image.open(png).convert("RGB")
            image = image.resize((image.width * 3 // 4, image.height * 3 // 4), Image.LANCZOS)
            images.append(image.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    durations = [FRAME_MS] * len(images)
    durations[-1] = 900
    images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True,
                   disposal=1)


if __name__ == "__main__":
    main()
