"""Camera resolution/aspect in LOP and OBJ: a flipbook with another aspect than the camera comes out stretched"""
from types import SimpleNamespace

import pytest

from DinoWrite.core.viewport import HouViewport


FALLBACKS = {"resolution": (2048, 1080), "pixelAspectRatio": 1.0}  # USD schema fallbacks


class Attr:
    def __init__(self, name, value):
        self.name, self.value = name, value

    def Get(self):
        return self.value if self.value is not None else FALLBACKS.get(self.name)

    def HasAuthoredValue(self):
        return self.value is not None


class Relationship:
    def __init__(self, targets):
        self.targets = targets

    def GetTargets(self):
        return list(self.targets)


class Prim:
    def __init__(self, type_name="Camera", path="/cam", **attrs):
        self.type_name, self.path, self.attrs = type_name, path, attrs

    def GetTypeName(self):
        return self.type_name

    def GetPath(self):
        return self.path

    def IsValid(self):
        return True

    def GetAttribute(self, name):
        return Attr(name, self.attrs.get(name))

    def GetRelationship(self, name):
        return Relationship(self.attrs.get(name, ()))


class Stage:
    def __init__(self, prims, metadata=None):
        self.prims = prims
        self.metadata = metadata or {}

    def GetMetadata(self, key):
        return self.metadata.get(key, "")

    def Traverse(self):
        return iter(self.prims)

    def GetPrimAtPath(self, path):
        return next((p for p in self.prims if p.GetPath() == path), None)


def viewer(network="Lop", prims=(), camera_path="/cam", obj_camera=None, size=(0, 0, 1295, 1096), metadata=None):
    pane = SimpleNamespace(
        pwd=lambda: SimpleNamespace(childTypeCategory=lambda: SimpleNamespace(name=lambda: network)),
        stage=lambda: Stage(list(prims), metadata),
        curViewport=lambda: SimpleNamespace(size=lambda: size, cameraPath=lambda: camera_path,
                                            camera=lambda: obj_camera))
    view = HouViewport.__new__(HouViewport)
    view.viewport_panetab = pane
    return view


CAMERA_16_9 = Prim(horizontalAperture=20.955, verticalAperture=11.787)


def test_lop_camera_without_render_settings_keeps_camera_aspect():
    """Viewport 1295x1096, 16:9 camera: Houdini shows '1295 x 728', the whole viewport would squash"""
    view = viewer(prims=[CAMERA_16_9])
    assert view.cameraResolution() == (1295, 728)
    assert view.cameraPixelAspect() == 1.0
    assert view.cameraAspect() == pytest.approx(20.955 / 11.787)


def test_lop_render_settings_resolution_wins():
    view = viewer(prims=[CAMERA_16_9, Prim("RenderSettings", "/Render/rs", resolution=(1920, 800),
                                           pixelAspectRatio=2.0)])
    assert view.cameraResolution() == (1920, 800)
    assert view.cameraPixelAspect() == 2.0
    assert view.cameraAspect() == pytest.approx(1920 / 800)


def test_lop_uses_the_stage_render_settings_not_a_fallback_resolution():
    """Karma Render Settings 1280x720 is the stage's render settings; another prim without an authored
    resolution reports the USD fallback 2048x1080 and must not be used"""
    other = Prim("RenderSettings", "/Render/aaa_default")  # no authored resolution
    karma = Prim("RenderSettings", "/Render/rendersettings", resolution=(1280, 720), camera=("/cam",))
    view = viewer(prims=[other, karma, CAMERA_16_9], metadata={"renderSettingsPrimPath": "/Render/rendersettings"})
    assert view.cameraResolution() == (1280, 720)
    # no stage metadata: the one with the viewport camera
    view = viewer(prims=[other, karma, CAMERA_16_9])
    assert view.cameraResolution() == (1280, 720)
    # only an unauthored one: camera aspect, not 2048x1080
    view = viewer(prims=[other, CAMERA_16_9])
    assert view.cameraResolution() == (1295, 728)


def test_lop_without_camera_uses_viewport():
    view = viewer(prims=[], camera_path="")
    assert view.cameraResolution() == (1295, 1096)
    assert view.cameraAspect() is None


def test_obj_camera():
    camera = SimpleNamespace(evalParm=lambda name: {"resx": 2048, "resy": 858}[name])
    view = viewer(network="Object", obj_camera=camera)
    assert view.cameraResolution() == (2048, 858)
    assert view.cameraAspect() == pytest.approx(2048 / 858)


def test_status_warns_about_stretched_image(houdini, monkeypatch):
    import DinoWrite

    window = DinoWrite.show({})
    monkeypatch.setattr(window.hou_viewport, "cameraAspect", lambda: 16 / 9, raising=False)
    monkeypatch.setattr(window.hou_viewport, "getPaneTab", lambda: SimpleNamespace(qtScreenGeometry=lambda: 1 / 0))
    window.resx.setText("1295")
    window.resy.setText("1096")
    window.updateStatus()
    assert "≠ camera aspect 1.78" in window.statusline.text()
    window.resy.setText("728")
    window.updateStatus()
    assert window.statusline.text().startswith("Record: 1295×728 in")
    window.close()
