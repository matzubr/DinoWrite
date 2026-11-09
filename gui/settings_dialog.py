"""Settings dialog: edits settings.json values, saves only overrides to the user settings file."""
import copy
import posixpath
import re

from .. import config
from ..core import acescg, ffmpeg
from ..core.log import log
from . import animation, widgets
from .frameless import RoundedWindow, TitleBar
from .qt import *  # noqa: F403
from .resources import ICONS_FOLDER
from .theme import COLORS

EXR_COMPRESSION = (("dwaa", "DWAA (small, for previews)"), ("zip", "ZIP (lossless)"),
                   ("piz", "PIZ (lossless, grainy images)"), ("none", "None"))
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
FOLDER_TOKENS = (("{name}", "Flipbook name from the window"),
                 ("$HIP", "Folder of the .hip file"), ("$JOB", "Project folder ($JOB)"))
NAME_TOKENS = (("{name}", "Flipbook name from the window"), ("{version}", "v001, v002...: the next free version"),
               ("{fileformat}", "exr / png / jpg"), ("$F4", "Frame number, 4 digits: 1001"))
PREVIEW_VALUES = {"name": "shot_010", "version": "v001", "fileformat": "exr"}
PREVIEW_COLOR = "#8a8a8a"
CHIP_STYLE = """
QPushButton { padding: 1px 8px; border-radius: 9px; color: #e0c27a; }
"""


def expand(path: str) -> str:
    """$HIP/$JOB expanded like Houdini does (unchanged when it can't)"""
    try:
        import hou

        expanded = hou.text.expandString(path)
    except Exception:  # noqa: BLE001
        return path
    return expanded if isinstance(expanded, str) else path


def pickFolder(start: str) -> str:
    """Houdini's file browser (keeps $HIP / $JOB in the path), Qt's when hou can't show it"""
    try:
        import hou

        chosen = hou.ui.selectFile(start_directory=start or None, title="Flipbooks folder",
                                   file_type=hou.fileType.Directory, chooser_mode=hou.fileChooserMode.Read)
        if isinstance(chosen, str):
            return chosen
    except Exception:  # noqa: BLE001
        pass
    return QFileDialog.getExistingDirectory(None, "Flipbooks folder", expand(start)) or ""


OBJECT_NAME = "DinoWriteSettings"
BODY_NAME = "DinoWriteSettingsBody"
DIALOG_WIDTH = 620
LABEL_WIDTH = 140
SECTION_NAME = "DinoWriteSettingsSection"
TAB_CHECKED_STYLE = """
QPushButton:checked { background-color: rgba(183, 134, 32, 20%); border: 1px solid #b78620; color: #ffffff; }
"""


def bodyStyle() -> str:
    """Same look as the main window: stylesheets.json entries + text edits, tooltips, scroll bars in that palette"""
    styles = widgets.styles
    line_edit = styles.get("lineedit")
    return "".join([
        styles.get("label"), line_edit, styles.get("mainbutton"), styles.get("combobox"),
        styles.get("checkbox"), styles.get("menu"),
        line_edit.replace("QLineEdit", "QPlainTextEdit"),
        f"""
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
        self.setFont(QFont(widgets.MAIN_FONT, widgets.MAIN_SIZE))
        self.settings = config.load()

        # Tabs as buttons (same animated buttons as the main window), pages of grey section frames
        self.pages = QStackedWidget()
        self.tab_buttons = []
        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        for index, (title, page) in enumerate((("General", self._generalTab()), ("Video", self._videoTab()),
                                                ("Presets", self._presetsTab()))):
            self.pages.addWidget(page)
            button = widgets.PushButton(title)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(widgets.styles.get("mainbutton") + TAB_CHECKED_STYLE)
            button.clicked.connect(lambda _=False, i=index: self.showPage(i))
            self.tab_buttons.append(button)
            tab_row.addWidget(button)
        self.tab_buttons[0].setChecked(True)

        user_file = widgets.ElidedLabel(f"User settings: {config.userSettingsPath().as_posix()}")
        user_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        user_file.setCursor(Qt.IBeamCursor)

        save_button = widgets.PushButton("Save")
        cancel_button = widgets.PushButton("Cancel")
        reset_button = widgets.PushButton("Reset to defaults")
        folder_button = widgets.PushButton("Open settings folder")
        for button in (save_button, cancel_button, reset_button, folder_button):
            button.setCursor(Qt.PointingHandCursor)
        save_button.clicked.connect(self.save)
        cancel_button.clicked.connect(lambda: self.fadeOut(self.reject))
        reset_button.clicked.connect(self.resetToDefaults)
        folder_button.clicked.connect(self.openSettingsFolder)
        buttons = QHBoxLayout()
        buttons.addWidget(reset_button)
        buttons.addWidget(folder_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        self.save_button = save_button

        footer = self._frame()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(10, 6, 10, 8)
        footer_layout.addWidget(user_file)
        footer_layout.addLayout(buttons)

        body = QWidget()
        body.setObjectName(BODY_NAME)
        body.setStyleSheet(bodyStyle())
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 0, 10, 10)
        body_layout.addLayout(tab_row)
        body_layout.addWidget(self.pages)
        body_layout.addWidget(footer)
        self.footer = footer

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
        self.delete_incomplete = widgets.CheckBox("Delete flipbook if it doesn't cover the frame range")
        self.exr_acescg = widgets.CheckBox("Convert EXR to ACEScg (for Nuke)")
        self.exr_acescg.setToolTip(
            "Opens right in Nuke with an ACES config (ACEScg is the default for EXR there).\n"
            "After recording, the kept EXR are converted from the viewport look back to ACEScg\n"
            "(inverse of the viewer's OCIO display/view, hoiiotool 2.5+). A viewer with the same\n"
            "display/view shows exactly what the viewport showed. Off: EXR stay as recorded.")
        self.exr_compression = QComboBox()
        for key, label in EXR_COMPRESSION:
            self.exr_compression.addItem(label, key)
        self.exr_compression.setToolTip(
            "Kept EXR are rewritten after recording (hoiiotool) with this compression and the flipbook\n"
            "passport in the header (hip, camera, frame range...: Nuke Read -> Metadata).\n"
            "DWAA: several times smaller, visually lossless for a preview, fast in Nuke.")
        self.true_resolution = QComboBox()
        for key, label in TRUE_RESOLUTION:
            self.true_resolution.addItem(label, key)
        self.true_resolution.setToolTip(
            "A 4K flipbook on a 2K monitor: a floating copy of the viewer is sized to the resolution\n"
            "(bigger than the screen), so frames are rendered at true 4K instead of being stretched")

        browse = widgets.PushButton("")
        browse.setIcon(QIcon((ICONS_FOLDER / "folder-open.svg").as_posix()))
        browse.setFixedSize(QSize(28, 28))
        browse.setCursor(Qt.PointingHandCursor)
        browse.setToolTip("Choose the folder (Houdini file browser: keeps $HIP / $JOB)")
        browse.clicked.connect(self.browseFolder)
        self.browse_button = browse
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.fb_folder)
        folder_layout.addWidget(browse)

        self.folder_preview = self._previewLabel()
        self.name_preview = self._previewLabel()
        for field in (self.fb_folder, self.fb_name):
            field.textChanged.connect(self.updatePreviews)

        return self._page(
            self._section([("Flipbooks folder", folder_row),
                           ("", self._tokens(self.fb_folder, FOLDER_TOKENS)),
                           ("", self.folder_preview),
                           ("File name", self.fb_name),
                           ("", self._tokens(self.fb_name, NAME_TOKENS)),
                           ("", self.name_preview),
                           ("Video extension", self.fb_video_ext)]),
            self._section([("Record viewer", self.true_resolution), ("", self.delete_incomplete)]),
            self._section([("EXR compression", self.exr_compression), ("", self.exr_acescg)]))

    def _videoTab(self) -> QWidget:
        self.delete_input = widgets.CheckBox("Delete image sequence after successful conversion")
        self.video_audio = widgets.CheckBox("Add scene audio (the file in the Audio panel)")
        self.video_audio.setToolTip("The sound file set in Houdini's Audio panel (playbar sound), synced\n"
                                    "like in the playbar. Nothing happens when no file is set.")
        self.open_after = QComboBox()
        for key, label in OPEN_AFTER:
            self.open_after.addItem(label, key)
        self.tools_status = widgets.Label()
        # no word wrap: QFormLayout gets the height of a wrapped label wrong and rows overlap
        self.tools_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.tools_status.setCursor(Qt.IBeamCursor)
        self.tools_status.setToolTip("ffmpeg path, encoder and the command: advanced.ffmpeg_path, "
                                     "advanced.video_codec, ffmpeg_cmd in the user settings file")

        return self._page(
            self._section([("Open result", self.open_after), ("", self.video_audio), ("", self.delete_input)]),
            self._section([("Found tools", self.tools_status)]))

    def _presetsTab(self) -> QWidget:
        self.resolutions = QPlainTextEdit()
        self.resolutions.setPlaceholderText("1920 1080")
        self.frame_ranges = QPlainTextEdit()
        self.frame_ranges.setPlaceholderText("From Current Frame To Global End = $F $FEND")
        for edit in (self.resolutions, self.frame_ranges):
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            edit.setMinimumHeight(90)
        return self._page(
            self._section([("Resolutions", self.resolutions)], hint="one per line: width height"),
            self._section([("Frame ranges", self.frame_ranges)], hint="one per line: name = start end"))

    def _tokens(self, field: QLineEdit, tokens) -> QWidget:
        """Small buttons with the variables a template understands: click inserts it at the cursor"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for token, meaning in tokens:
            chip = widgets.PushButton(token, size=widgets.MAIN_SIZE - 3, radius=9)
            chip.setStyleSheet(widgets.styles.get("mainbutton") + CHIP_STYLE)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(meaning)
            chip.clicked.connect(lambda _=False, t=token: self.insertToken(field, t))
            layout.addWidget(chip)
        layout.addStretch()
        return row

    def insertToken(self, field: QLineEdit, token: str):
        field.insert(token)
        field.setFocus()

    @staticmethod
    def _previewLabel() -> QLabel:
        label = widgets.ElidedLabel("")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setCursor(Qt.IBeamCursor)
        return label

    def updatePreviews(self):
        """What the templates turn into for an example flipbook"""
        folder, name = self.fb_folder.text().strip(), self.fb_name.text().strip()
        try:
            folder_text = "→ " + posixpath.normpath(expand(folder.format(**PREVIEW_VALUES)).replace("\\", "/"))
            folder_ok = True
        except (KeyError, IndexError, ValueError) as e:
            folder_text, folder_ok = f"Unknown placeholder {e}", False
        try:
            name_text = "→ " + FRAME_TOKEN.sub("1001", name.format(**PREVIEW_VALUES))
            name_ok = bool(FRAME_TOKEN.search(name))
            if not name_ok:
                name_text += "   (needs a frame token like $F4)"
        except (KeyError, IndexError, ValueError) as e:
            name_text, name_ok = f"Unknown placeholder {e}", False
        for label, text, ok in ((self.folder_preview, folder_text, folder_ok), (self.name_preview, name_text, name_ok)):
            color = PREVIEW_COLOR if ok else COLORS["crimson"]
            label.setStyleSheet(f"background: transparent; color: {color};")
            animation.setTextAnimated(label, text)

    def browseFolder(self):
        """Pick the flipbooks folder; a trailing /{name} (one folder per flipbook name) is kept"""
        current = self.fb_folder.text().strip()
        keeps_name = current.rstrip("/").endswith("{name}")
        base = current.rstrip("/")[:-len("{name}")].rstrip("/") if keeps_name else current
        chosen = pickFolder(base)
        if not chosen:
            return
        chosen = chosen.rstrip("/")
        self.fb_folder.setText(f"{chosen}/{{name}}" if keeps_name else chosen)

    def _section(self, rows, hint: str = "") -> QWidget:
        """Grey frame like the main window's blocks, bold right-aligned labels"""
        frame = self._frame()
        form = QFormLayout(frame)
        form.setContentsMargins(10, 8, 10, 8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        for label, field in rows:
            if label:
                title = widgets.HBLabel(label)
                title.setFixedWidth(LABEL_WIDTH)
                if hint:
                    title.setToolTip(hint)
                    field.setToolTip(hint)
                form.addRow(title, field)
            else:
                form.addRow(self._spacer(), field)
        return frame

    @staticmethod
    def _frame() -> QFrame:
        """Grey block like the main window's; the style is scoped to the frame so fields keep theirs"""
        frame = QFrame()
        frame.setObjectName(SECTION_NAME)
        frame.setStyleSheet(f"QFrame#{SECTION_NAME} {{ background-color: {COLORS['grey']}; border-radius: 5px; }}")
        return frame

    @staticmethod
    def _spacer() -> QWidget:
        spacer = QWidget()
        spacer.setFixedWidth(LABEL_WIDTH)
        return spacer

    def _page(self, *sections) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        for section in sections:
            layout.addWidget(section)
        layout.addStretch()
        page.sections = list(sections)
        return page

    def showPage(self, index: int):
        """Switch tab: the page's sections come in one after another"""
        for i, button in enumerate(self.tab_buttons):
            button.setChecked(i == index)
        if self.pages.currentIndex() != index:
            self.pages.setCurrentIndex(index)
            animation.stagger(self.pages.currentWidget().sections)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_staggered", False):
            self._staggered = True
            QTimer.singleShot(0, lambda: animation.stagger(self.pages.currentWidget().sections + [self.footer]))

    # ---------- load / collect ----------

    def load(self, settings: dict):
        paths, advanced = settings["paths"], settings["advanced"]
        self.fb_folder.setText(paths.get("fb_folder", ""))
        self.fb_name.setText(paths.get("fb_name", ""))
        self.fb_video_ext.setCurrentText(paths.get("fb_video_ext", "mov"))
        self.delete_incomplete.setChecked(bool(advanced.get("delete_incomplete_fb")))
        self.exr_acescg.setChecked(bool(advanced.get("exr_acescg", True)))
        self.exr_compression.setCurrentIndex(max(self.exr_compression.findData(advanced.get("exr_compression", "dwaa")), 0))
        self.video_audio.setChecked(bool(advanced.get("video_audio", True)))
        self.true_resolution.setCurrentIndex(max(self.true_resolution.findData(advanced.get("true_resolution", "auto")), 0))

        self.delete_input.setChecked(bool(advanced.get("conversion_delete_input_sequence")))
        self.open_after.setCurrentIndex(max(self.open_after.findData(advanced.get("open_after", "video")), 0))

        self.resolutions.setPlainText("\n".join(settings.get("custom_resolution", [])))
        self.frame_ranges.setPlainText("\n".join(
            f"{name} = {value}" for name, value in settings.get("custom_framerange", {}).items()))

        self._updateToolsStatus(advanced)
        self.updatePreviews()

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
        advanced["exr_compression"] = self.exr_compression.currentData()
        advanced["video_audio"] = self.video_audio.isChecked()
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
        oiiotool_text = (oiiotool + (f" ({version})" if version else "")) if oiiotool else \
            "NOT FOUND, EXR stay as recorded"
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
