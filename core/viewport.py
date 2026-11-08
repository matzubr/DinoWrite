"""Wrapper around Houdini Scene Viewer used for flipbooking"""
import time

import hou

from .log import log

# advanced.true_resolution:
#   auto   - record in a torn off copy of the viewer only when the resolution doesn't fit the maximized viewport
#   always - always record in a torn off copy sized to the resolution
#   off    - record in the maximized viewport, Houdini scales the image to the resolution
TRUE_RESOLUTION_MODES = ("auto", "always", "off")

# Toolbars hidden in the torn off copy so the viewport takes the whole window
_VIEWER_BARS = ("showOperationBar", "showDisplayOptionsBar", "showSelectionBar",
                "showColorCorrectionBar", "showMemoryBar")
_PANEL_PARTS = ("setContainsPlaybar", "setContainsShelf", "setContainsStatusBar", "setContainsMenuBar")


def processEvents():
    """Let Qt apply window resizes before measuring the viewport (Qt imported lazily: core stays Qt-free)"""
    try:
        from ..gui.qt import QApplication
        QApplication.processEvents()
    except ImportError:
        pass


def fitsResolution(viewport_size: tuple, resolution: tuple) -> bool:
    return viewport_size[0] >= resolution[0] and viewport_size[1] >= resolution[1]


def fitPanel(set_size, get_panel_size, get_viewport_size, resolution: tuple,
             device_pixel_ratio: float = 1.0, process_events=processEvents, attempts: int = 4) -> tuple:
    """Resize a floating panel until the viewport inside it is `resolution` pixels.

    Window chrome and toolbars around the viewport are unknown, so the difference between
    wanted and actual viewport size is added to the window size and measured again.
    Window size is in logical (Qt) pixels, viewport size in device pixels: on HiDPI screens
    a 3840x2160 viewport needs only a 1920x1080 window at 2x scale.
    The OS may refuse windows bigger than the screen, then the result stays smaller.

    Returns:
        tuple: achieved viewport size (width, height) in device pixels
    """
    target_w, target_h = resolution
    for _ in range(attempts):
        viewport_w, viewport_h = get_viewport_size()
        delta_w, delta_h = target_w - viewport_w, target_h - viewport_h
        if abs(delta_w) <= 1 and abs(delta_h) <= 1:
            break
        panel_w, panel_h = get_panel_size()
        set_size((max(1, round(panel_w + delta_w / device_pixel_ratio)),
                  max(1, round(panel_h + delta_h / device_pixel_ratio))))
        process_events()
    return tuple(get_viewport_size())

def _usdValue(attribute):
    """USD attribute value at the current frame. Karma Render Settings writes a resolution computed from the
    camera as time samples; without a time USD returns the default value (e.g. 2048x1080 instead of 1400x788)."""
    try:
        return attribute.Get(hou.frame())
    except Exception:  # noqa: BLE001 - no current frame (tests, no UI): the default value
        return attribute.Get()


# Display set types whose shading options are copied to the torn off viewer (missing ones are skipped)
_DISPLAY_SETS = ("SceneObject", "SelectedObject", "GhostObject", "DisplayModel", "CurrentModel", "TemplateModel")


def copySettings(source, target) -> int:
    """Copy every value that has a getter/setter pair (lighting() / setLighting(...)) from source to target.

    A cloned Scene Viewer starts with default display options (Normal Lighting etc.): the torn off copy
    must look like the viewer the user set up. Pairs that need arguments or fail are skipped.
    Returns how many values were changed.
    """
    changed = 0
    for setter_name in dir(target):
        if not setter_name.startswith("set") or len(setter_name) < 4 or not setter_name[3].isupper():
            continue
        getter_name = setter_name[3].lower() + setter_name[4:]
        getter = getattr(source, getter_name, None)
        target_getter = getattr(target, getter_name, None)
        if not callable(getter) or not callable(target_getter):
            continue
        try:
            value = getter()
            if target_getter() != value:
                getattr(target, setter_name)(value)
                changed += 1
        except Exception:  # noqa: BLE001 - getters with arguments, read-only/unsupported options
            continue
    return changed


def copyViewportSettings(source, target):
    """Viewport display options and per display set shading (wireframe, shaded...) from source to target"""
    changed = copySettings(source, target)
    display_set_type = getattr(hou, "displaySetType", None)
    for name in _DISPLAY_SETS:
        set_type = getattr(display_set_type, name, None)
        if set_type is None:
            continue
        try:
            changed += copySettings(source.displaySet(set_type), target.displaySet(set_type))
        except Exception:  # noqa: BLE001
            continue
    log.info("Torn off viewer: %d display options copied from the viewer", changed)


class HouViewport:
    def __init__(self,kwargs) -> None:
        # Started from a viewer (its shelf/hotkey): that one. From a shelf: the first Scene Viewer
        pane_tab = kwargs.get("pane")
        if pane_tab is not None and pane_tab.type() == hou.paneTabType.SceneViewer:
            self.viewport_panetab = pane_tab
        else:
            self.viewport_panetab = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if hou.ui.paneTabOfType(hou.paneTabType.SceneViewer, 1):
                log.warning("Multiple viewers detected! Run the tool from the shelf/hotkey of the viewer to record")

        if not self.viewport_panetab.isCurrentTab():
            self.viewport_panetab.setIsCurrentTab()  # a hidden tab can't be recorded

        self.viewport_pane = self.viewport_panetab.pane()
        self.settings = self.viewport_panetab.curViewport().settings()
        self.torn_off_panel = None

    @classmethod
    def fromPaneTab(cls, panetab):
        viewer = cls.__new__(cls)
        viewer.viewport_panetab = panetab
        viewer.viewport_pane = panetab.pane()
        viewer.settings = panetab.curViewport().settings()
        viewer.torn_off_panel = None
        return viewer

    def settle(self, timeout: float = 2.0, stable_checks: int = 3) -> tuple:
        """Wait until the viewport has redrawn at its new size.

        After a resize Houdini resizes the GL buffers on the next redraw; a flipbook started right
        away renders its first frame with the old (smaller) buffer.

        Returns:
            tuple: viewport size after it stopped changing
        """
        deadline = time.monotonic() + timeout
        last, stable = None, 0
        while time.monotonic() < deadline:
            processEvents()
            try:
                self.viewport_panetab.curViewport().draw()
            except (AttributeError, hou.Error):
                pass
            size = self.viewportSize()
            stable = stable + 1 if size == last else 0
            last = size
            if stable >= stable_checks:
                break
            time.sleep(0.05)
        return last

    def viewportSize(self) -> tuple:
        """Current viewport size (width, height) in device pixels"""
        size = self.viewport_panetab.curViewport().size()
        return int(size[2]), int(size[3])

    def tearOff(self, resolution: tuple):
        """Floating copy of this viewer (like 'Tear off pane tab copy') with the viewport sized to resolution.

        The window may be bigger than the monitor: the flipbook is then rendered at true resolution
        instead of a stretched smaller viewport. Call close() on the result when done.

        Returns:
            tuple: (HouViewport of the copy, achieved viewport size)
        """
        clone = self.viewport_panetab.clone()
        torn = HouViewport.fromPaneTab(clone)
        panel = clone.floatingPanel()
        torn.torn_off_panel = panel
        try:
            for name in _VIEWER_BARS:
                getattr(clone, name, lambda show: None)(False)
            for name in _PANEL_PARTS:
                getattr(panel, name, lambda on: None)(False)
            try:
                clone.setViewportLayout(hou.geometryViewportLayout.Single)
            except (AttributeError, hou.Error):
                pass
            torn._copyCameraFrom(self)
            torn.settings = clone.curViewport().settings()
            copyViewportSettings(self.settings, torn.settings)

            panel.setPosition(self._screenOrigin())
            processEvents()
            window = panel.qtParentWindow()
            fitPanel(set_size=panel.setSize,
                     get_panel_size=lambda: tuple(panel.size()),
                     get_viewport_size=torn.viewportSize,
                     resolution=resolution,
                     device_pixel_ratio=window.devicePixelRatioF() if window else 1.0)
            achieved = torn.settle()
        except Exception:
            torn.close()
            raise
        return torn, achieved

    def _copyCameraFrom(self, source):
        """Look through the same camera (or copy the free view) as the source viewer"""
        source_vp = source.viewport_panetab.curViewport()
        target_vp = self.viewport_panetab.curViewport()
        if target_vp.cameraPath() and target_vp.cameraPath() == source_vp.cameraPath():
            return  # clone already looks through the same camera
        try:
            camera = source_vp.camera()
            if camera is not None:
                target_vp.setCamera(camera)
            elif source_vp.cameraPath():
                target_vp.setCamera(source_vp.cameraPath())  # LOP camera prim path
            else:
                target_vp.setDefaultCamera(source_vp.defaultCamera().stash())
        except (AttributeError, TypeError, hou.Error) as e:
            log.warning("Can't copy camera to torn off viewer: %s", e)

    def _screenOrigin(self) -> tuple:
        """Top-left corner of the screen with the source viewer"""
        try:
            geometry = self.viewport_panetab.qtScreenGeometry()
            from ..gui.qt import QGuiApplication
            screen = QGuiApplication.screenAt(geometry.center()) or QGuiApplication.primaryScreen()
            origin = screen.availableGeometry().topLeft()
            return origin.x(), origin.y()
        except Exception:
            return 0, 0

    def close(self):
        """Close torn off copy (no-op for the main viewer)"""
        if self.torn_off_panel is not None:
            try:
                self.torn_off_panel.close()
            except hou.Error as e:
                log.warning("Can't close torn off viewer: %s", e)
            self.torn_off_panel = None

    def startFlipbook(self,options):
        float_fullscreen=False
        float_panetab = ""
        if self.torn_off_panel is not None:
            # torn off copy is already sized to the resolution, fullscreen would shrink it
            self.viewport_panetab.flipbook(self.viewport_panetab.curViewport(), options)
            return
        if self.viewport_panetab.isFloating():
            float_panetab = self.viewport_panetab.floatingPanel()
            float_fullscreen = float_panetab.isFullscreen()
            float_panetab.setIsFullscreen(True)

        self.viewport_panetab.flipbook(self.viewport_panetab.curViewport(), options)

        if self.viewport_panetab.isFloating():
            float_panetab.setIsFullscreen(float_fullscreen)

    def getPaneTab(self):
        return self.viewport_panetab

    def maximize_viewport(self,type=True):
        if self.viewport_pane is not None:
            self.viewport_pane.setIsMaximized(type)

    def isMaximized(self) -> bool:
        return self.viewport_pane is not None and self.viewport_pane.isMaximized()

    def colorScheme(self,color=None):
        """Get current viewport color scheme (hou.viewportColorScheme) or set it.

        Args:
            color (str | hou.viewportColorScheme, optional): "dark", "grey", "light" or any hou.viewportColorScheme value
        """
        scheme = {  "dark":hou.viewportColorScheme.Dark,
                    "grey":hou.viewportColorScheme.Grey,
                    "light":hou.viewportColorScheme.Light}

        if color is None:
            return self.settings.colorScheme()
        else:
            self.settings.setColorScheme(scheme[color] if isinstance(color,str) else color)

    def displayBackgroundImage(self,type=None):
        """Background image visibility: get it (no argument) or set it"""
        if type is None:
            return self.settings.displayBackgroundImage()
        self.settings.setDisplayBackgroundImage(type)

    def cameraResolution(self):
        """Resolution of the viewport camera (LOP: render settings prim), viewport size without one"""
        try:
            return self._cameraResolution()
        except Exception as e:  # noqa: BLE001 - no stage, light as camera, ...: never break the window
            log.warning("Can't read camera resolution, using viewport size: %s", e)
            size = self.viewport_panetab.curViewport().size()
            return (size[2], size[3])

    def _cameraResolution(self):
        viewport = self.viewport_panetab.curViewport()
        size = viewport.size()
        if self._isLop():
            resolution = self._renderSettingsResolution()
            if resolution:
                return resolution
            # No render settings: Houdini shows the camera at the viewport width with the camera's aspect
            # (e.g. "1295 x 728" in the viewer). The whole viewport (1295x1096) would squash the image.
            aspect = self._usdCameraAspect()
            if aspect:
                return (size[2], max(1, round(size[2] / aspect)))
            log.info("No camera in the viewport, returning the viewport size")
            return (size[2], size[3])

        camera = viewport.camera()
        if camera:
            return (camera.evalParm("resx"), camera.evalParm("resy"))
        log.info("No camera in the viewport, returning the viewport size")
        return (size[2], size[3])

    def _isLop(self) -> bool:
        return self.viewport_panetab.pwd().childTypeCategory().name() == "Lop"

    def _renderSettingsPrim(self):
        """Render settings the viewer uses: the stage's renderSettingsPrimPath (set by Karma Render Settings),
        else one whose camera is the viewport camera, else the only one. None when it isn't clear."""
        stage = self.viewport_panetab.stage()
        if not stage:
            return None
        path = stage.GetMetadata("renderSettingsPrimPath")
        prim = stage.GetPrimAtPath(path) if path else None
        if prim and prim.IsValid():
            return prim
        render_prims = [p for p in stage.Traverse() if p.GetTypeName() == "RenderSettings"]
        camera_path = self.viewport_panetab.curViewport().cameraPath()
        for prim in render_prims:
            relationship = prim.GetRelationship("camera")
            targets = [str(t) for t in relationship.GetTargets()] if relationship else []
            if camera_path and camera_path in targets:
                return prim
        if len(render_prims) > 1:
            log.warning("Several render settings prims and none is the stage's or uses the viewport camera, "
                        "using the camera aspect")
            return None
        return render_prims[0] if render_prims else None

    def _renderSettingsResolution(self):
        prim = self._renderSettingsPrim()
        attribute = prim.GetAttribute("resolution") if prim else None
        # Only an authored value: the schema fallback is 2048x1080, not what the viewer shows
        if not attribute or not attribute.HasAuthoredValue():
            return None
        resolution = _usdValue(attribute)
        log.info("Camera resolution from %s: %sx%s", prim.GetPath(), resolution[0], resolution[1])
        return (int(resolution[0]), int(resolution[1]))

    def _usdCameraAspect(self):
        """Image aspect of the viewport's USD camera (horizontalAperture / verticalAperture), None without one"""
        stage = self.viewport_panetab.stage()
        path = self.viewport_panetab.curViewport().cameraPath()
        prim = stage.GetPrimAtPath(path) if stage and path else None
        if not prim or not prim.IsValid():
            return None
        horizontal = _usdValue(prim.GetAttribute("horizontalAperture"))
        vertical = _usdValue(prim.GetAttribute("verticalAperture"))
        return float(horizontal) / float(vertical) if horizontal and vertical else None

    def cameraAspect(self):
        """Image aspect (width / height) the camera renders with, None without a camera or when unknown.
        A flipbook resolution with another aspect comes out stretched."""
        try:
            if self._isLop():
                resolution = self._renderSettingsResolution()
                return resolution[0] / resolution[1] if resolution else self._usdCameraAspect()
            camera = self.viewport_panetab.curViewport().camera()
            return camera.evalParm("resx") / camera.evalParm("resy") if camera else None
        except Exception:  # noqa: BLE001 - only a status hint
            return None

    def cameraPixelAspect(self):
        try:
            return float(self._cameraPixelAspect())
        except Exception as e:  # noqa: BLE001 - no stage, light as camera, ...: WRITE must still work
            log.warning("Can't read camera pixel aspect, using 1: %s", e)
            return 1.0

    def _cameraPixelAspect(self):
        if self._isLop():
            prim = self._renderSettingsPrim()
            attribute = prim.GetAttribute("pixelAspectRatio") if prim else None
            aspect = _usdValue(attribute) if attribute and attribute.HasAuthoredValue() else None
            return float(aspect) if aspect else 1.0
        camera = self.viewport_panetab.curViewport().camera()
        return camera.evalParm("aspect") if camera else 1.0

    def cameraName(self):
        viewport = self.viewport_panetab.curViewport()
        camera_path = viewport.cameraPath()
        if camera_path=="":        
            return "Viewport Default Camera"
        else:
            return camera_path.split("/")[-1]
    
    def flipbook_settings(self):
        return self.viewport_panetab.flipbookSettings().stash()
