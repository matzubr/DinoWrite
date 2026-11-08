import hou
import json
import logging
import sys
from pathlib import Path
import subprocess
from os import environ as osenviron
import random
import re
import shutil
from pxr import Sdf,Usd

from PySide2.QtWidgets import *
from PySide2.QtGui import *
from PySide2.QtCore import *

LOGGER_NAME = "DinoWrite"

class _HoudiniConsoleHandler(logging.Handler):
    """Writes to the current sys.stdout on every record.

    Houdini swaps sys.stdout for its Python Shell / console, so a StreamHandler
    bound to the stream at creation time may print to the wrong place.
    """
    def emit(self, record):
        try:
            print(self.format(record), file=sys.stdout)
        except Exception:
            self.handleError(record)

def getLogger() -> logging.Logger:
    """Module logger. Handler is added once, so reload(utils) doesn't duplicate messages."""
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(h, _HoudiniConsoleHandler) for h in logger.handlers):
        handler = _HoudiniConsoleHandler()
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

log = getLogger()

def hmsg(message:str,buttons=("Sorry,Dino!",),level="message") -> None:
    """Houdini message window 

    Args:
        message (str): Message to display
        buttons (tuple, optional): Buttons to provide to user. Defaults to ("Sorry,Dino!",).
        level (str, optional): Importance level of message. Defaults to "message" , available "warning" and "error".
    """
    levels = {
        "message": hou.severityType.Message,
        "warning": hou.severityType.Warning,
        "error": hou.severityType.Error
    }

    if message:
        hou.ui.displayMessage(message,buttons=buttons,severity=levels[level],title="DinoWrite say")
    else:
        log.warning("No message set in hsmg function")

VERSION_FOLDER_PATTERN = re.compile(r"^v(\d+)$")
VERSION_MIN_PADDING = 3

def nextVersion(folder: Path) -> str:
    """Get next version string (like 'v004') based on 'vNNN' subfolders in folder.

    Folders that don't match 'vNNN' pattern are ignored.
    Versions compared as numbers, so v1000 is newer than v999.
    """
    last_digit = 0
    padding = VERSION_MIN_PADDING
    if folder.exists():
        for x in folder.iterdir():
            match = VERSION_FOLDER_PATTERN.match(x.name)
            if x.is_dir() and match:
                digit = int(match[1])
                if digit >= last_digit:
                    last_digit = digit
                    padding = max(padding, len(match[1]))
    return f"v{str(last_digit+1).zfill(padding)}"

def evalFrame(value: str):
    """Evaluate frame value from line edit: plain number or hscript expression like '$F+10'.

    Returns:
        int | float | None: Frame number or None if value can't be evaluated
    """
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        result = hou.hscriptExpression(value)
        return int(result) if float(result).is_integer() else float(result)
    except (hou.Error, TypeError, ValueError):
        return None

def toInt(value: str, default=None):
    """Safe int conversion of line edit text"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def ffmpegFps(fps: float) -> str:
    """Format fps for ffmpeg, keeping fractional (NTSC) frame rates exact"""
    if float(fps).is_integer():
        return str(int(fps))
    ntsc = round(fps * 1.001)
    if abs(ntsc * 1000 / 1001 - fps) < 0.001:
        return f"{ntsc*1000}/1001"
    return f"{fps:.3f}"

class StyleSheet:
    """Parsing info from stylesheet json file
    """
    def __init__(self, config_path: str) -> None:
        self.config_path = config_path

    def get(self, element: str) -> str:
        """Get element from stylesheet file

        Args:
            element (str): Name of the element

        Returns:
            str: Stylesheet style string
        """
        data = {}
        with open(self.config_path) as theme:
            data = json.load(theme)

        if element != "main":
            label_style = data[element]
            style = ""
            for i in label_style:
                data = label_style[i]
                settings = ""
                for j in data:
                    settings += j
                style += f"{i}{ {settings} }".replace("'", "")
            return style
        else:
            return data[element]

class FFmpeg:
    """Wrapper around ffmpeg
    """
    def __init__(self, config_path: str, bin: str,cmd: dict) -> None:
        
        self.config_path = config_path
        self.cmdvar = cmd
        self.available = True
        system_os = hou.getenv("OS")

        if not config_path and not cmd:
            log.warning("No config path or cmd set")

        # Check for ffmpeg availability in system envs on different os (i believe)
        if system_os=="Windows_NT" and (Path(bin) / "ffmpeg.exe").exists():
            path = osenviron["PATH"]
            if str(bin) not in path.split(";"):
                osenviron["PATH"] = f"{bin};{path}"
        elif not shutil.which("ffmpeg"):
            self.available = False
            location = f" or in {bin}" if system_os=="Windows_NT" else ""
            hmsg(f"No ffmpeg found in system PATH env{location}\nVideo conversion skipped, sequence is kept")

    def cmd(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="") -> list:

        if input == "" or output == "":
            log.error("No input or output set")
            return 0

        if self.cmdvar:
            template = self.cmdvar
        else:
            with open(self.config_path) as cmd:
                template = json.load(cmd)['cmd']

        # Split template entries before formatting, so paths with spaces stay single arguments
        commands = []
        for key in template:
            for token in key.split():
                commands.append(token.format(fps=fps, resolution=resolution, aspect=aspect,
                                            start_frame=start_frame, input=input, output=output))

        return commands

    def convert_to_video(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", delete_input=False):
        if not self.available:
            log.warning("ffmpeg is not available, video conversion skipped")
            return 0

        ffmpeg_cmd = self.cmd(fps=fps, resolution=resolution, aspect=aspect,
                            start_frame=start_frame, input=input, output=output)
        
        folder = Path(input).parent
        if folder.exists():
            files = [x for x in folder.iterdir()]
        else:
            files = []

        log.info("Running: %s", subprocess.list2cmdline(ffmpeg_cmd))
        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            stderr_tail = "\n".join((e.stderr or "").strip().splitlines()[-15:])
            log.error("ffmpeg failed with exit code %s:\n%s", e.returncode, stderr_tail)
            return 0
        except FileNotFoundError as e:
            log.error("ffmpeg executable not found: %s", e)
            return 0

        if len(files) != 0 and delete_input:
            for file in files:
                file.unlink()

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

class FileParser:
    def __init__(self) -> None:
        settings_file = (Path(__file__).parents[1] / "settings.json").as_posix()
        data = {}
        with open(settings_file) as f:
            data = json.load(f)
        self.paths = data.get("paths")

    def getVersion(self,flipbook_name:str) -> str:
        if len(flipbook_name)==0:
            return "v001"
        fb_folder = Path(hou.text.expandString(self.paths.get("fb_folder")).format(name=flipbook_name)).resolve()
        return nextVersion(fb_folder)

class Icons:
    def __init__(self) -> None:
        self.iconfolder = Path(__file__).parents[1] / "icons"

    def get(self,name:str,type:str="Icon") -> QIcon:
        iconpath = Path(self.iconfolder) / name
        if not iconpath.exists():
            log.warning(f"No icon found:\n{iconpath.as_posix()}")
        else:
            if type=="Icon":
                return QIcon(iconpath.as_posix())
            elif type=="Path":
                return iconpath.as_posix()

    def getRandom(self,prefix="app",type="Icon"):
        iconpath = Path(self.iconfolder)
        icons = [x for x in iconpath.iterdir() if x.stem.startswith(prefix)]
        
        if len(icons)==0:
            log.warning(f"No files found with current prefix: {prefix}")
            return QIcon()
        else:
            icon = (random.choice(icons)).as_posix()
            if type=="Icon":
                return QIcon(icon)
            elif type=="Path":
                return icon