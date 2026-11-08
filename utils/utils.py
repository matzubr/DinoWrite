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
import string
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

def findFFmpeg(custom_path: str = "") -> str:
    """Find ffmpeg executable, same lookup order as Houdini's FFmpeg Encode Video TOP.

    1. custom_path from settings.json (advanced.ffmpeg_path)
    2. $PDG_FFMPEG environment variable
    3. ffmpeg that ships with Houdini: $HFS/bin/hffmpeg
    4. ffmpeg from system PATH

    Returns:
        str: Path to executable or empty string if nothing found
    """
    candidates = []
    if custom_path:
        candidates.append(hou.text.expandString(custom_path))
    if osenviron.get("PDG_FFMPEG"):
        candidates.append(osenviron["PDG_FFMPEG"])
    hfs = hou.getenv("HFS")
    if hfs:
        exe = ".exe" if hou.getenv("OS") == "Windows_NT" else ""
        candidates.append((Path(hfs) / "bin" / f"hffmpeg{exe}").as_posix())

    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
        log.warning("ffmpeg not found at: %s", candidate)

    return shutil.which("ffmpeg") or ""

# Transfer functions to encode linear EXR for display, applied as a 16-bit LUT before RGB -> YUV.
# Done with lutrgb filter instead of exr decoder "-apply_trc" option: that option was removed in newer ffmpeg.
EXR_TRANSFER_EXPRESSIONS = {
    "srgb":    "if(lte(val/maxval,0.0031308),12.92*val,maxval*(1.055*pow(val/maxval,1/2.4)-0.055))",
    "gamma22": "maxval*pow(val/maxval,1/2.2)",
    "bt709":   "if(lt(val/maxval,0.018),4.5*val,maxval*(1.099*pow(val/maxval,0.45)-0.099))",
}

def videoFilter(exr_transfer: str = "") -> str:
    """ffmpeg -vf chain: optional linear -> display transfer, then BT.709 RGB -> YUV conversion.

    Without explicit out_color_matrix swscale converts with BT.601 matrix while the file is tagged BT.709,
    which shifts hues (reds/greens) in players.
    """
    filters = []
    if exr_transfer:
        expr = EXR_TRANSFER_EXPRESSIONS.get(exr_transfer)
        if expr is None:
            log.warning("Unknown exr_transfer '%s', expected one of: %s", exr_transfer, ", ".join(EXR_TRANSFER_EXPRESSIONS))
        else:
            filters += ["format=rgb48le", f"lutrgb=r='{expr}':g='{expr}':b='{expr}'"]
    filters += ["scale=out_color_matrix=bt709:out_range=tv", "format=yuv420p",
                # Tag frames explicitly: newer ffmpeg passes EXR "linear" trc through filters
                # and it overrides -color_trc/-color_primaries output options
                "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709:range=tv"]
    return ",".join(filters)

class FFmpeg:
    """Wrapper around ffmpeg
    """
    def __init__(self, config_path: str, cmd: list, binary: str = "") -> None:

        self.config_path = config_path
        self.cmdvar = cmd
        self.binary = findFFmpeg(binary)
        self.available = bool(self.binary)

        if not config_path and not cmd:
            log.warning("No config path or cmd set")

        if self.available:
            log.info("Using ffmpeg: %s", self.binary)
        else:
            hmsg("No ffmpeg found (settings, $PDG_FFMPEG, $HFS/bin/hffmpeg, system PATH)\n"
                 "Video conversion skipped, sequence is kept")

    def cmd(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", exr_transfer="") -> list:
        """Build ffmpeg argv from template.

        Template entry whose placeholder is empty is skipped entirely,
        so optional flags can be switched off from settings.json.
        {vf} is the video filter chain built by videoFilter().
        """

        if input == "" or output == "":
            log.error("No input or output set")
            return 0

        if self.cmdvar:
            template = self.cmdvar
        else:
            with open(self.config_path) as cmd:
                template = json.load(cmd)['cmd']

        # Split template entries before formatting, so paths with spaces stay single arguments
        values = dict(fps=fps, resolution=resolution, aspect=aspect,
                    start_frame=start_frame, input=input, output=output,
                    vf=videoFilter(exr_transfer))
        commands = []
        for key in template:
            fields = [field for _, field, _, _ in string.Formatter().parse(key) if field]
            if any(str(values.get(field, "")) == "" for field in fields):
                continue
            for token in key.split():
                commands.append(token.format(**values))

        # "ffmpeg" in template means "the resolved executable"
        if commands and commands[0] == "ffmpeg" and getattr(self, "binary", ""):
            commands[0] = self.binary

        return commands

    def convert_to_video(self, fps=24, resolution="1920x1080", aspect=1, start_frame=1001, input="", output="", delete_input=False, exr_transfer=""):
        if not self.available:
            log.warning("ffmpeg is not available, video conversion skipped")
            return 0

        ffmpeg_cmd = self.cmd(fps=fps, resolution=resolution, aspect=aspect, exr_transfer=exr_transfer,
                            start_frame=start_frame, input=input, output=output)
        
        folder = Path(input).parent
        if folder.exists():
            files = [x for x in folder.iterdir()]
        else:
            files = []

        log.info("Running: %s", subprocess.list2cmdline(ffmpeg_cmd))
        try:
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL)
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