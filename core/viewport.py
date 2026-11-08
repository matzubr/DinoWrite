"""Wrapper around Houdini Scene Viewer used for flipbooking"""
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

class HouViewport:
    def __init__(self,kwargs) -> None:
        self.viewport_panetab = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)

        if not self.viewport_panetab.isCurrentTab():
            log.info("Starting the tool from a shelf leads to the recording of a flipbook from the first SceneViewer that comes across")
            self.viewport_panetab.setIsCurrentTab()

        if hou.ui.paneTabOfType(hou.paneTabType.SceneViewer,1):
            paneTab = kwargs.get("pane")
            if paneTab and paneTab.type() == hou.paneTabType.SceneViewer:
                self.viewport_panetab = paneTab
            else:
                log.warning("Multiple viewers detected!\nYou can select a viewer by executing the tool from the desired")

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

            panel.setPosition(self._screenOrigin())
            processEvents()
            window = panel.qtParentWindow()
            achieved = fitPanel(set_size=panel.setSize,
                                get_panel_size=lambda: tuple(panel.size()),
                                get_viewport_size=torn.viewportSize,
                                resolution=resolution,
                                device_pixel_ratio=window.devicePixelRatioF() if window else 1.0)
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

    def displayBackgroundImage(self,type=True):
        self.settings.setDisplayBackgroundImage(type)

    def cameraResolution(self):
        network = self.viewport_panetab.pwd().childTypeCategory().name()
        viewport = self.viewport_panetab.curViewport()

        if network=="Lop":

            stage = self.viewport_panetab.stage()
            render_prims = [p for p in stage.Traverse() if p.GetTypeName()=="RenderSettings"]
            if len(render_prims)==0:
                size = viewport.size()
                resx = size[2]
                resy = size[3]
                
            elif len(render_prims)>0:
                if len(render_prims)>1:
                    log.warning("Multiple rendersettings prims detected!\nResolution will be taken from the first alphabetically ordered prim")
                render_prim = render_prims[0]
                resolution_prop = render_prim.GetProperty("resolution")
                resolution = resolution_prop.Get() if resolution_prop else None
                if resolution:
                    resx = resolution[0]
                    resy = resolution[1]
                else:
                    log.warning("No resolution authored on rendersettings prim\nReturning resolution from viewport size")
                    size = viewport.size()
                    resx = size[2]
                    resy = size[3]
        
        else: #proccess obj and sops
            
            camera = viewport.camera()
            if camera:
                resx = camera.evalParm("resx")
                resy = camera.evalParm("resy")
            else:
                log.info("No Camera Found in viewport\nReturning resolution from viewport size")
                size = viewport.size()
                resx = size[2]
                resy = size[3]
                
            
        return tuple((resx, resy))
    
    def cameraPixelAspect(self):
        network = self.viewport_panetab.pwd().childTypeCategory().name()
        viewport = self.viewport_panetab.curViewport()

        if network=="Lop":

            stage = self.viewport_panetab.stage()
            render_prims = [p for p in stage.Traverse() if p.GetTypeName()=="RenderSettings"]
            if len(render_prims)==0:
                aspect = 1
            elif len(render_prims)>0:
                render_prim = render_prims[0]
                aspect_prop = render_prim.GetProperty("pixelAspectRatio")
                aspect = aspect_prop.Get() if aspect_prop else None
                aspect = float(aspect) if aspect else 1
        
        else: #procces obj and sops

            camera = viewport.camera()
            if camera:
                aspect = camera.evalParm("aspect")
            else:
                # log.debug("No Camera Found in viewport\nReturning aspect 1")
                aspect = 1
        
        
        return aspect

    def cameraName(self):
        viewport = self.viewport_panetab.curViewport()
        camera_path = viewport.cameraPath()
        if camera_path=="":        
            return "Viewport Default Camera"
        else:
            return camera_path.split("/")[-1]
    
    def flipbook_settings(self):
        return self.viewport_panetab.flipbookSettings().stash()
