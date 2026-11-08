"""Wrapper around Houdini Scene Viewer used for flipbooking"""
import hou

from .log import log

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

    def startFlipbook(self,options):
        float_fullscreen=False
        float_panetab = ""
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
