"""Qt resources: stylesheets and icons"""
import json
import random
from pathlib import Path

from .qt import QIcon
from ..core.log import log

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ICONS_FOLDER = PACKAGE_ROOT / "icons"
FONT_FILE = PACKAGE_ROOT / "misc" / "font.ttf"
STYLESHEETS_FILE = Path(__file__).resolve().parent / "stylesheets.json"

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

class Icons:
    def __init__(self) -> None:
        self.iconfolder = ICONS_FOLDER

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
