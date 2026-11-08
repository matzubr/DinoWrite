"""Recording at true resolution in a torn off viewer copy"""
import pytest

from DinoWrite import flipbook
from DinoWrite.core import viewport as viewport_mod


class FakeWindow:
    """Floating panel: viewport = (window - chrome) * dpr, optionally clamped by the OS to the screen"""

    def __init__(self, size, chrome=(40, 90), dpr=1.0, screen=None):
        self.size = list(size)
        self.chrome, self.dpr, self.screen = chrome, dpr, screen

    def set_size(self, size):
        w, h = size
        if self.screen:
            w, h = min(w, self.screen[0]), min(h, self.screen[1])
        self.size = [w, h]

    def viewport(self):
        return ((self.size[0] - self.chrome[0]) * self.dpr, (self.size[1] - self.chrome[1]) * self.dpr)


def _fit(window, resolution):
    return viewport_mod.fitPanel(window.set_size, lambda: tuple(window.size), window.viewport,
                                 resolution, window.dpr, process_events=lambda: None)


def test_fit_panel_bigger_than_screen():
    window = FakeWindow((800, 600))
    assert _fit(window, (3840, 2160)) == (3840, 2160)
    assert window.size == [3880, 2250]


def test_fit_panel_hidpi_needs_half_size_window():
    window = FakeWindow((800, 600), dpr=2.0)
    assert _fit(window, (3840, 2160)) == (3840, 2160)
    assert window.size == [1960, 1170]


def test_fit_panel_clamped_by_os_returns_achieved_size():
    window = FakeWindow((800, 600), screen=(2560, 1440))
    assert _fit(window, (3840, 2160)) == (2520, 1350)


class FakeViewer:
    def __init__(self, size, tear_off_result=None, tear_off_error=None):
        self.size = size
        self.tear_off_result, self.tear_off_error = tear_off_result, tear_off_error
        self.events = []
        self.scheme = "grey"
        self.background_image = True
        self.maximized = False

    def viewportSize(self):
        return self.size

    def settle(self):
        self.events.append(("settle",))
        return self.size

    def maximize_viewport(self, on=True):
        self.events.append(("maximize", on))

    def isMaximized(self):
        return self.maximized

    def tearOff(self, resolution):
        if self.tear_off_error:
            raise self.tear_off_error
        return self.tear_off_result, resolution

    def colorScheme(self, color=None):
        if color is None:
            return self.scheme
        self.events.append(("scheme", color))

    def displayBackgroundImage(self, on=None):
        if on is None:
            return self.background_image
        self.events.append(("bgimage", on))

    def startFlipbook(self, options):
        self.events.append(("warmup",) if options is not None and options.is_warmup else ("flipbook",))

    def close(self):
        self.events.append(("close",))


@pytest.fixture(autouse=True)
def no_qt(monkeypatch):
    monkeypatch.setattr(viewport_mod, "processEvents", lambda: None)


class FakeOptions:
    def __init__(self, is_warmup=False):
        self.is_warmup = is_warmup
        self.range, self.out, self.mplay = (1001, 1100), "/shots/v001/shot.$F4.exr", True

    def stash(self):
        return FakeOptions(is_warmup=True)

    def frameRange(self, value=None):
        if value is None:
            return self.range
        self.range = value

    def output(self, value=None):
        if value is None:
            return self.out
        self.out = value

    def outputToMPlay(self, value):
        self.mplay = value


def test_auto_uses_viewport_when_resolution_fits():
    viewer = FakeViewer((2560, 1400))
    assert flipbook.chooseRecorder(viewer, (1920, 1080), "auto") is viewer


def test_auto_tears_off_when_resolution_is_bigger():
    torn = FakeViewer((3840, 2160))
    viewer = FakeViewer((2560, 1400), tear_off_result=torn)
    assert flipbook.chooseRecorder(viewer, (3840, 2160), "auto") is torn
    assert viewer.events == [("maximize", True), ("settle",), ("maximize", False)]


def test_off_never_tears_off():
    viewer = FakeViewer((100, 100), tear_off_result=FakeViewer((1, 1)))
    assert flipbook.chooseRecorder(viewer, (3840, 2160), "off") is viewer


def test_solaris_never_tears_off():
    viewer = FakeViewer((100, 100), tear_off_result=FakeViewer((1, 1)))
    viewer.isLop = lambda: True
    assert flipbook.chooseRecorder(viewer, (3840, 2160), "always") is viewer
    assert flipbook.chooseRecorder(viewer, (3840, 2160), "auto") is viewer


def test_solaris_keeps_viewport_options():
    viewer = FakeViewer((2560, 1400))
    viewer.isLop = lambda: True
    flipbook.record(viewer, FakeOptions(), (1920, 1080), black_background=True, hide_background_image=True)
    assert not any(event[0] in ("scheme", "bgimage") for event in viewer.events)
    assert ("flipbook",) in viewer.events


def test_tear_off_failure_falls_back_to_viewport():
    viewer = FakeViewer((100, 100), tear_off_error=RuntimeError("no clone"))
    assert flipbook.chooseRecorder(viewer, (3840, 2160), "always") is viewer


def test_record_in_torn_off_copy_leaves_main_viewer_untouched():
    torn = FakeViewer((3840, 2160))
    viewer = FakeViewer((1920, 1000), tear_off_result=torn)
    flipbook.record(viewer, FakeOptions(), (3840, 2160), mode="always", black_background=True,
                    hide_background_image=True)
    assert torn.events == [("scheme", "dark"), ("bgimage", False), ("warmup",), ("flipbook",),
                           ("scheme", "grey"), ("bgimage", True), ("close",)]
    assert ("scheme", "dark") not in viewer.events


def test_record_restores_state_when_flipbook_fails():
    class Failing(FakeViewer):
        def startFlipbook(self, options):
            raise RuntimeError("flipbook failed")

    torn = Failing((3840, 2160))
    viewer = FakeViewer((1920, 1000), tear_off_result=torn)
    with pytest.raises(RuntimeError):
        flipbook.record(viewer, FakeOptions(), (3840, 2160), mode="always", black_background=True)
    assert torn.events[-2:] == [("scheme", "grey"), ("close",)]
    assert viewer.events[-1] == ("maximize", False)


class FakeGeoViewport:
    def __init__(self, window=None, camera=None, camera_path=""):
        self.window, self._camera, self._camera_path = window, camera, camera_path
        self.set_camera = None

    def size(self):
        w, h = self.window.viewport()
        return (0, 0, w, h)

    def camera(self):
        return self._camera

    def cameraPath(self):
        return self._camera_path

    def setCamera(self, camera):
        self.set_camera = camera

    def settings(self):
        return "settings"


class FakePanel:
    def __init__(self, window):
        self.window, self.calls, self.closed = window, [], False

    def __getattr__(self, name):  # setContainsPlaybar etc.
        return lambda *args: self.calls.append((name, args))

    def setSize(self, size):
        self.window.set_size(size)

    def size(self):
        return tuple(self.window.size)

    def qtParentWindow(self):
        return type("W", (), {"devicePixelRatioF": lambda self: 1.0})()

    def close(self):
        self.closed = True


class FakePaneTab:
    def __init__(self, viewport, panel=None, clone=None):
        self.viewport, self.panel, self._clone, self.calls = viewport, panel, clone, []

    def clone(self):
        return self._clone

    def floatingPanel(self):
        return self.panel

    def pane(self):
        return None

    def curViewport(self):
        return self.viewport

    def qtScreenGeometry(self):
        raise RuntimeError("no Qt in this test")

    def __getattr__(self, name):  # showOperationBar etc.
        return lambda *args: self.calls.append((name, args))


def test_tear_off_hides_bars_copies_camera_and_sizes_window(monkeypatch, hou):
    monkeypatch.setattr(viewport_mod, "processEvents", lambda: None)
    window = FakeWindow((800, 600))
    panel = FakePanel(window)
    clone = FakePaneTab(FakeGeoViewport(window), panel=panel)
    source = viewport_mod.HouViewport.fromPaneTab(
        FakePaneTab(FakeGeoViewport(camera="/obj/cam1", camera_path="/obj/cam1"), clone=clone))

    torn, achieved = source.tearOff((3840, 2160))

    assert achieved == (3840, 2160)
    assert clone.viewport.set_camera == "/obj/cam1"
    assert ("showOperationBar", (False,)) in clone.calls
    assert ("setContainsPlaybar", (False,)) in panel.calls
    torn.close()
    assert panel.closed


def test_warm_up_renders_one_frame_to_temp_not_to_mplay():
    seen = []

    class Recorder(FakeViewer):
        def startFlipbook(self, options):
            seen.append((options.frameRange(), options.output(), options.mplay))

    options = FakeOptions()
    flipbook.warmUp(Recorder((1, 1)), options)
    (frames, output, mplay), = seen
    assert frames == (1001, 1001) and mplay is False
    assert "dinowrite_warmup_" in output and output.endswith("warmup.$F4.jpg")
    assert options.out == "/shots/v001/shot.$F4.exr", "real flipbook settings untouched"


def test_warm_up_failure_does_not_block_recording():
    class Broken(FakeViewer):
        def startFlipbook(self, options):
            raise RuntimeError("no GL")

    flipbook.warmUp(Broken((1, 1)), FakeOptions())  # only logs


def test_settle_waits_for_stable_size(monkeypatch):
    sizes = iter([(800, 600), (1600, 900), (3840, 2160), (3840, 2160), (3840, 2160), (3840, 2160)])
    viewer = viewport_mod.HouViewport.__new__(viewport_mod.HouViewport)
    viewer.viewport_panetab = type("T", (), {"curViewport": lambda self: type("V", (), {"draw": lambda s: None})()})()
    monkeypatch.setattr(viewer, "viewportSize", lambda: next(sizes))
    monkeypatch.setattr(viewport_mod.time, "sleep", lambda s: None)
    assert viewer.settle() == (3840, 2160)


def test_record_restores_background_image_and_maximize_as_they_were():
    """Background image was off and the pane maximized before: both stay that way after recording"""
    viewer = FakeViewer((2560, 1400))
    viewer.background_image, viewer.maximized = False, True
    flipbook.record(viewer, FakeOptions(), (1920, 1080), mode="auto", hide_background_image=True)
    assert ("bgimage", True) not in viewer.events
    assert viewer.events[-1] == ("maximize", True)


class FakeSettings:
    """GeometryViewportSettings-like: getter/setter pairs, one getter that needs an argument"""

    def __init__(self, lighting="normal", ao=False, shading="smooth"):
        self._lighting, self._ao = lighting, ao
        self.sets = {"scene": FakeDisplaySet(shading)}

    def lighting(self):
        return self._lighting

    def setLighting(self, value):
        self._lighting = value

    def ambientOcclusion(self):
        return self._ao

    def setAmbientOcclusion(self, value):
        self._ao = value

    def visibleObjects(self, kind):  # needs an argument: skipped
        return kind

    def setVisibleObjects(self, value):
        raise AssertionError("must not be called")

    def displaySet(self, set_type):
        return self.sets[set_type]


class FakeDisplaySet:
    def __init__(self, shading):
        self._shading = shading

    def shadedMode(self):
        return self._shading

    def setShadedMode(self, value):
        self._shading = value


def test_torn_off_viewer_gets_the_viewer_display_options(monkeypatch, hou):
    """Headlight only in the viewer must stay headlight only in the torn off copy (clone starts with Normal)"""
    monkeypatch.setattr(hou, "displaySetType", type("T", (), {"SceneObject": "scene"}), raising=False)
    source = FakeSettings(lighting="headlight", ao=True, shading="flat")
    target = FakeSettings()
    viewport_mod.copyViewportSettings(source, target)
    assert target.lighting() == "headlight" and target.ambientOcclusion() is True
    assert target.sets["scene"].shadedMode() == "flat"
