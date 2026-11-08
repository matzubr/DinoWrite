"""Settings dialog: edits settings.json values, saves only overrides to the user settings file."""
import copy
import re

from .. import config
from ..core import acescg, ffmpeg
from ..core.log import log
from . import widgets
from .frameless import RoundedWindow, TitleBar
from .qt import *  # noqa: F403
from .resources import ICONS_FOLDER
from .theme import COLORS

TRUE_RESOLUTION = (
    ("auto", "Separate viewer window when resolution is bigger than the viewport"),
    ("always", "Always record in a separate viewer window"),
    ("off", "Maximized viewport (Houdini scales to the resolution)"),
)
OPEN_AFTER = (
    ("video", "Converted video (or the folder without conversion)"),
    ("folder", "Folder with the sequence"),
)
FRAME_TOKEN = re.compile(r"\$F\d+")


OBJECT_NAME = "DinoWriteSettings"
BODY_NAME = "DinoWriteSettingsBody"
DIALOG_WIDTH = 620


def bodyStyle() -> str:
    """Same look as the main window: stylesheets.json entries + tabs/text edits/spin boxes in that palette"""
    styles = widgets.styles
    line_edit = styles.get("lineedit")
    return "".join([
        styles.get("label"), line_edit, styles.get("mainbutton"), styles.get("combobox"),
        styles.get("checkbox"), styles.get("menu"),
        line_edit.replace("QLineEdit", "QPlainTextEdit"),
        f"""
        QTabWidget::pane {{
            background-color: {COLORS['grey']};
            border: 1px solid #202020;
            border-radius: 5px;
            top: -1px;
        }}
        QTabWidget > QWidget > QWidget {{ background-color: {COLORS['grey']}; }}
        QTabBar::tab {{
            background-color: qlineargradient(x1:1, y1:0, x2:1, y2:1, stop:0 #545454, stop:1 #3b3b3b);
            color: #dddddd;
            border: 1px solid #202020;
            border-bottom: none;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            padding: 5px 14px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{ background-color: {COLORS['grey']}; color: #ffffff; border-color: {COLORS['accent']}; }}
        QTabBar::tab:hover:!selected {{ background-color: rgba(183, 134, 32, 20%); }}
        QToolTip {{ background-color: {COLORS['grey-dark']}; color: {COLORS['white']}; border: 1px solid #343434; }}
        QScrollBar:vertical, QScrollBar:horizontal {{ background: {COLORS['grey-dark']}; border: none; margin: 0; }}
        QScrollBar:vertical {{ width: 10px; }}
        QScrollBar:horizontal {{ height: 10px; }}
        QScrollBar::handle {{ background: #4a4a4a; border-radius: 4px; min-height: 20px; min-width: 20px; }}
        QScrollBar::handle:hover {{ background: {COLORS['accent']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        """,
    ])


class SettingsDialog(RoundedWindow, QDialog):
    """Edit DinoWrite settings. exec() returns Accepted when settings were saved."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DinoWrite Settings")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setFixedWidth(DIALOG_WIDTH)
        self.setupRoundedWindow(OBJECT_NAME)
        QDir.addSearchPath("icons", ICONS_FOLDER.as_posix())  # checkbox/combobox images in stylesheets
        self.setFont(QFont(widgets.MAIN_FONT, widgets.MAIN_SIZE - 1))
        self.settings = config.load()

        tabs = QTabWidget()
        tabs.addTab(self._generalTab(), "General")
        tabs.addTab(self._videoTab(), "Video")
        tabs.addTab(self._presetsTab(), "Presets")

        user_file = QLabel(f"User settings: {config.userSettingsPath().as_posix()}")
        user_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        user_file.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        reset_button = buttons.addButton("Reset to defaults", QDialogButtonBox.ResetRole)
        folder_button = buttons.addButton("Open settings folder", QDialogButtonBox.HelpRole)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        reset_button.clicked.connect(self.resetToDefaults)
        folder_button.clicked.connect(self.openSettingsFolder)

        body = QWidget()
        body.setObjectName(BODY_NAME)
        body.setStyleSheet(bodyStyle())
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 0, 10, 10)
        body_layout.addWidget(tabs)
        body_layout.addWidget(user_file)
        body_layout.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(TitleBar(self, "Settings", icon_size=34, title_size=12, on_close=lambda: self.fadeOut(self.reject)))
        layout.addWidget(body)

        self.load(self.settings)
        self.adjustSize()

    # ---------- tabs ----------

    def _generalTab(self) -> QWidget:
        self.fb_folder = QLineEdit()
        self.fb_folder.setToolTip("Folder for flipbooks, {name} is the flipbook name. Versions are created inside")
        self.fb_name = QLineEdit()
        self.fb_name.setToolTip("File name template: {name}, {version}, {fileformat} and a frame token like $F4")
        self.fb_video_ext = QComboBox()
        self.fb_video_ext.addItems(self.settings["formats"]["video_exts"])
        self.delete_incomplete = QCheckBox("Delete flipbook if it doesn't cover the frame range")
        self.exr_acescg = QCheckBox("Convert EXR to ACEScg (opens right in Nuke with an ACES config)")
        self.exr_acescg.setToolTip(
            "After recording, the kept EXR are converted from the viewport look back to ACEScg\n"
            "(inverse of the viewer's OCIO display/view, hoiiotool 2.5+). A viewer with the same\n"
            "display/view shows exactly what the viewport showed. Off: EXR stay as recorded.")
        self.true_resolution = QComboBox()
        for key, label in TRUE_RESOLUTION:
            self.true_resolution.addItem(label, key)
        self.true_resolution.setToolTip(
            "A 4K flipbook on a 2K monitor: a floating copy of the viewer is sized to the resolution\n"
            "(bigger than the screen), so frames are rendered at true 4K instead of being stretched")

        form = QFormLayout()
        form.addRow("Flipbooks folder", self.fb_folder)
        form.addRow("File name", self.fb_name)
        form.addRow("Video extension", self.fb_video_ext)
        form.addRow("Record viewer", self.true_resolution)
        form.addRow("", self.delete_incomplete)
        form.addRow("", self.exr_acescg)
        return self._page(form)

    def _videoTab(self) -> QWidget:
        self.delete_input = QCheckBox("Delete image sequence after successful conversion")
        self.open_after = QComboBox()
        for key, label in OPEN_AFTER:
            self.open_after.addItem(label, key)
        self.tools_status = QLabel()
        # no word wrap: QFormLayout gets the height of a wrapped label wrong and rows overlap
        self.tools_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.tools_status.setToolTip("ffmpeg path, encoder and the command: advanced.ffmpeg_path, "
                                     "advanced.video_codec, ffmpeg_cmd in the user settings file")

        form = QFormLayout()
        form.addRow("Open result", self.open_after)
        form.addRow("", self.delete_input)
        form.addRow("", self.tools_status)
        return self._page(form)

    def _presetsTab(self) -> QWidget:
        self.resolutions = QPlainTextEdit()
        self.resolutions.setPlaceholderText("1920 1080")
        self.frame_ranges = QPlainTextEdit()
        self.frame_ranges.setPlaceholderText("From Current Frame To Global End = $F $FEND")

        for edit in (self.resolutions, self.frame_ranges):
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Resolutions, one per line: width height"))
        layout.addWidget(self.resolutions)
        layout.addWidget(QLabel("Frame ranges, one per line: name = start end"))
        layout.addWidget(self.frame_ranges)
        return self._page(layout)

    def _page(self, layout) -> QWidget:
        page = QWidget()
        page.setLayout(layout)
        return page

    # ---------- load / collect ----------

    def load(self, settings: dict):
        paths, advanced = settings["paths"], settings["advanced"]
        self.fb_folder.setText(paths.get("fb_folder", ""))
        self.fb_name.setText(paths.get("fb_name", ""))
        self.fb_video_ext.setCurrentText(paths.get("fb_video_ext", "mov"))
        self.delete_incomplete.setChecked(bool(advanced.get("delete_incomplete_fb")))
        self.exr_acescg.setChecked(bool(advanced.get("exr_acescg", True)))
        self.true_resolution.setCurrentIndex(max(self.true_resolution.findData(advanced.get("true_resolution", "auto")), 0))

        self.delete_input.setChecked(bool(advanced.get("conversion_delete_input_sequence")))
        self.open_after.setCurrentIndex(max(self.open_after.findData(advanced.get("open_after", "video")), 0))

        self.resolutions.setPlainText("\n".join(settings.get("custom_resolution", [])))
        self.frame_ranges.setPlainText("\n".join(
            f"{name} = {value}" for name, value in settings.get("custom_framerange", {}).items()))

        self._updateToolsStatus(advanced)

    def collect(self) -> tuple:
        """Returns (settings, errors)"""
        settings = copy.deepcopy(self.settings)
        errors = []
        paths, advanced = settings["paths"], settings["advanced"]

        paths["fb_folder"] = self.fb_folder.text().strip()
        paths["fb_name"] = self.fb_name.text().strip()
        paths["fb_video_ext"] = self.fb_video_ext.currentText()
        if "{name}" not in paths["fb_folder"] and "{name}" not in paths["fb_name"]:
            errors.append("Flipbooks folder or file name must contain {name}")
        if not FRAME_TOKEN.search(paths["fb_name"]):
            errors.append("File name must contain a frame token like $F4")
        for label, template in (("Flipbooks folder", paths["fb_folder"]), ("File name", paths["fb_name"])):
            try:
                template.format(name="shot", version="v001", fileformat="exr")
            except (KeyError, IndexError, ValueError) as e:
                errors.append(f"{label}: unknown placeholder {e}, use {{name}}, {{version}}, {{fileformat}}")

        advanced["delete_incomplete_fb"] = self.delete_incomplete.isChecked()
        advanced["exr_acescg"] = self.exr_acescg.isChecked()
        advanced["true_resolution"] = self.true_resolution.currentData()
        advanced["conversion_delete_input_sequence"] = self.delete_input.isChecked()
        advanced["open_after"] = self.open_after.currentData()

        resolutions = []
        for line in self._lines(self.resolutions):
            parts = line.split()
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                errors.append(f"Resolution '{line}' should be: width height")
            else:
                resolutions.append(" ".join(parts))
        settings["custom_resolution"] = resolutions

        frame_ranges = {}
        for line in self._lines(self.frame_ranges):
            name, sep, value = line.partition("=")
            if not sep or not name.strip() or len(value.split()) != 2:
                errors.append(f"Frame range '{line}' should be: name = start end")
            else:
                frame_ranges[name.strip()] = " ".join(value.split())
        settings["custom_framerange"] = frame_ranges

        return settings, errors

    @staticmethod
    def _lines(edit: QPlainTextEdit) -> list:
        return [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]

    # ---------- reactions ----------

    def _updateToolsStatus(self, advanced: dict):
        ffmpeg_found = ffmpeg.findFFmpeg(advanced.get("ffmpeg_path", ""))
        encoders = ffmpeg.codecCandidates(advanced.get("video_codec", "auto"),
                                          ffmpeg.availableEncoders(ffmpeg_found)) if ffmpeg_found else []
        oiiotool = acescg.findOiiotool(advanced.get("oiiotool_path", ""))
        version = ".".join(map(str, acescg.oiiotoolVersion(oiiotool))) if oiiotool else ""
        oiiotool_text = f"{oiiotool} ({version or '?'})" if oiiotool else "NOT FOUND, EXR stay as recorded"
        try:
            import PyOpenColorIO

            ocio_text = PyOpenColorIO.__version__
        except ImportError:
            ocio_text = "NOT FOUND, EXR stay as recorded"
        self.tools_status.setText(
            f"ffmpeg: {ffmpeg_found or 'NOT FOUND, video conversion is skipped'}\n"
            f"encoders (tried in order): {', '.join(encoders) or 'unknown'}\n"
            f"oiiotool: {oiiotool_text}\n"
            f"PyOpenColorIO: {ocio_text}")
        # the form layout sized this row before the text was set: reserve height for every line
        lines = self.tools_status.text().count("\n") + 1
        self.tools_status.setMinimumHeight(self.tools_status.fontMetrics().lineSpacing() * lines + 4)

    # ---------- buttons ----------

    def save(self):
        settings, errors = self.collect()
        if errors:
            QMessageBox.warning(self, "DinoWrite Settings", "Please fix:\n\n" + "\n".join(errors))
            return
        config.save(settings)
        self.settings = settings
        self.accept()

    def resetToDefaults(self):
        answer = QMessageBox.question(self, "DinoWrite Settings",
                                      "Reset all settings to defaults?\nYour user settings file will be removed.")
        if answer != QMessageBox.Yes:
            return
        config.reset()
        self.settings = config.load()
        self.load(self.settings)
        self.accept()

    def openSettingsFolder(self):
        folder = config.userSettingsPath().parent
        folder.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder.as_posix())):
            log.warning("Can't open folder: %s", folder)


def execDialog(dialog: QDialog) -> int:
    """PySide6 has exec(), PySide2 only exec_()"""
    run = getattr(dialog, "exec", None) or dialog.exec_
    return run()
