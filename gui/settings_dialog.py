"""Settings dialog: edits settings.json values, saves only overrides to the user settings file."""
import copy
import re

import hou

from .. import config
from ..core import ffmpeg, ocio
from ..core.log import log
from .qt import *  # noqa: F403

COLOR_TRANSFORMS = (
    ("ocio", "OCIO display/view (like the viewer)"),
    ("srgb", "sRGB transfer"),
    ("gamma22", "Gamma 2.2"),
    ("bt709", "Rec.709 transfer"),
    ("none", "None (sequence is already display-encoded)"),
)
TRUE_RESOLUTION = (
    ("auto", "Separate viewer window when resolution is bigger than the viewport"),
    ("always", "Always record in a separate viewer window"),
    ("off", "Maximized viewport (Houdini scales to the resolution)"),
)
OPEN_AFTER = (
    ("video", "Converted video (or the folder without conversion)"),
    ("folder", "Folder with the sequence"),
)
FROM_VIEWER = "From viewer"
FRAME_TOKEN = re.compile(r"\$F\d+")


def _ocioList(getter, *args) -> list:
    try:
        return list(getter(*args))
    except Exception:  # hou.Color OCIO calls fail without a valid config
        return []


class SettingsDialog(QDialog):
    """Edit DinoWrite settings. exec() returns Accepted when settings were saved."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DinoWrite Settings")
        self.setMinimumWidth(560)
        self.settings = config.load()

        tabs = QTabWidget()
        tabs.addTab(self._generalTab(), "General")
        tabs.addTab(self._videoTab(), "Video")
        tabs.addTab(self._presetsTab(), "Presets")
        tabs.addTab(self._ffmpegTab(), "ffmpeg command")

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

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(user_file)
        layout.addWidget(buttons)

        self.load(self.settings)

    # ---------- tabs ----------

    def _generalTab(self) -> QWidget:
        self.fb_folder = QLineEdit()
        self.fb_folder.setToolTip("Folder for flipbooks, {name} is the flipbook name. Versions are created inside")
        self.fb_name = QLineEdit()
        self.fb_name.setToolTip("File name template: {name}, {version}, {fileformat} and a frame token like $F4")
        self.fb_video_ext = QComboBox()
        self.fb_video_ext.addItems(self.settings["formats"]["video_exts"])
        self.tmp_folder = QLineEdit()
        self.tmp_folder.setToolTip("Where the window remembers last used values")
        self.delete_incomplete = QCheckBox("Delete flipbook if it doesn't cover the frame range")
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
        form.addRow("Temp folder", self.tmp_folder)
        form.addRow("Record viewer", self.true_resolution)
        form.addRow("", self.delete_incomplete)
        return self._page(form)

    def _videoTab(self) -> QWidget:
        self.color_transform = QComboBox()
        for key, label in COLOR_TRANSFORMS:
            self.color_transform.addItem(label, key)

        self.ocio_display = QComboBox()
        self.ocio_display.setEditable(True)
        self.ocio_display.addItems([FROM_VIEWER] + _ocioList(lambda: hou.Color.ocio_activeDisplays()))
        self.ocio_view = QComboBox()
        self.ocio_view.setEditable(True)
        self.ocio_input_space = QComboBox()
        self.ocio_input_space.setEditable(True)
        self.ocio_input_space.addItems(
            _ocioList(lambda: hou.Color.ocio_roles()) + _ocioList(lambda: hou.Color.ocio_spaces()))
        self.ocio_display.currentTextChanged.connect(self._updateViews)
        self.color_transform.currentIndexChanged.connect(self._updateOcioEnabled)

        self.video_codec = QComboBox()
        self.video_codec.setEditable(True)
        self.video_codec.addItems(["auto"] + list(ffmpeg.CODECS))
        self.video_codec.setToolTip("auto: the best encoder this ffmpeg has (Houdini's hffmpeg has no libx264),\n"
                                    "falls back to the next one if it fails")
        self.ffmpeg_path, ffmpeg_row = self._pathRow("Empty: $PDG_FFMPEG, $HFS/bin/hffmpeg, system PATH")
        self.oiiotool_path, oiiotool_row = self._pathRow("Empty: $HFS/bin/hoiiotool, system PATH")
        self.tools_status = QLabel()
        self.tools_status.setWordWrap(True)
        self.tools_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ffmpeg_path.editingFinished.connect(self._updateToolsStatus)
        self.oiiotool_path.editingFinished.connect(self._updateToolsStatus)

        self.delete_input = QCheckBox("Delete image sequence after successful conversion")
        self.open_after = QComboBox()
        for key, label in OPEN_AFTER:
            self.open_after.addItem(label, key)

        form = QFormLayout()
        form.addRow("Color", self.color_transform)
        form.addRow("OCIO display", self.ocio_display)
        form.addRow("OCIO view", self.ocio_view)
        form.addRow("EXR color space", self.ocio_input_space)
        form.addRow("Video codec", self.video_codec)
        form.addRow("ffmpeg", ffmpeg_row)
        form.addRow("oiiotool", oiiotool_row)
        form.addRow("", self.tools_status)
        form.addRow("", self.delete_input)
        form.addRow("Open result", self.open_after)
        return self._page(form)

    def _presetsTab(self) -> QWidget:
        self.resolutions = QPlainTextEdit()
        self.resolutions.setPlaceholderText("1920 1080")
        self.frame_ranges = QPlainTextEdit()
        self.frame_ranges.setPlaceholderText("From Current Frame To Global End = $F $FEND")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Resolutions, one per line: width height"))
        layout.addWidget(self.resolutions)
        layout.addWidget(QLabel("Frame ranges, one per line: name = start end"))
        layout.addWidget(self.frame_ranges)
        return self._page(layout)

    def _ffmpegTab(self) -> QWidget:
        self.ffmpeg_cmd = QPlainTextEdit()
        self.ffmpeg_cmd.setLineWrapMode(QPlainTextEdit.NoWrap)
        hint = QLabel("One option per line. Placeholders: {fps} {start_frame} {input} {resolution} {aspect} "
                      "{vf} {codec} {output}.\nA line whose placeholder is empty is skipped. "
                      "First line 'ffmpeg' is replaced by the found executable.")
        hint.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(hint)
        layout.addWidget(self.ffmpeg_cmd)
        return self._page(layout)

    def _page(self, layout) -> QWidget:
        page = QWidget()
        page.setLayout(layout)
        return page

    def _pathRow(self, placeholder: str):
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        browse = QPushButton("...")
        browse.setFixedWidth(30)
        browse.clicked.connect(lambda: self._browse(line))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line)
        row.addWidget(browse)
        widget = QWidget()
        widget.setLayout(row)
        return line, widget

    def _browse(self, line: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select executable", line.text())
        if path:
            line.setText(path)
            self._updateToolsStatus()

    # ---------- load / collect ----------

    def load(self, settings: dict):
        paths, advanced = settings["paths"], settings["advanced"]
        self.fb_folder.setText(paths.get("fb_folder", ""))
        self.fb_name.setText(paths.get("fb_name", ""))
        self.fb_video_ext.setCurrentText(paths.get("fb_video_ext", "mov"))
        self.tmp_folder.setText(paths.get("tmp_folder", ""))
        self.delete_incomplete.setChecked(bool(advanced.get("delete_incomplete_fb")))
        self.true_resolution.setCurrentIndex(max(self.true_resolution.findData(advanced.get("true_resolution", "auto")), 0))

        index = self.color_transform.findData(advanced.get("color_transform", "ocio"))
        self.color_transform.setCurrentIndex(max(index, 0))
        self.ocio_display.setCurrentText(advanced.get("ocio_display") or FROM_VIEWER)
        self._updateViews()
        self.ocio_view.setCurrentText(advanced.get("ocio_view") or FROM_VIEWER)
        self.ocio_input_space.setCurrentText(advanced.get("ocio_input_space", ocio.DEFAULT_INPUT_SPACE))
        self.ffmpeg_path.setText(advanced.get("ffmpeg_path", ""))
        self.video_codec.setCurrentText(advanced.get("video_codec", "auto") or "auto")
        self.oiiotool_path.setText(advanced.get("oiiotool_path", ""))
        self.delete_input.setChecked(bool(advanced.get("conversion_delete_input_sequence")))
        self.open_after.setCurrentIndex(max(self.open_after.findData(advanced.get("open_after", "video")), 0))

        self.resolutions.setPlainText("\n".join(settings.get("custom_resolution", [])))
        self.frame_ranges.setPlainText("\n".join(
            f"{name} = {value}" for name, value in settings.get("custom_framerange", {}).items()))
        self.ffmpeg_cmd.setPlainText("\n".join(settings.get("ffmpeg_cmd", [])))

        self._updateOcioEnabled()
        self._updateToolsStatus()

    def collect(self) -> tuple:
        """Returns (settings, errors)"""
        settings = copy.deepcopy(self.settings)
        errors = []
        paths, advanced = settings["paths"], settings["advanced"]

        paths["fb_folder"] = self.fb_folder.text().strip()
        paths["fb_name"] = self.fb_name.text().strip()
        paths["fb_video_ext"] = self.fb_video_ext.currentText()
        paths["tmp_folder"] = self.tmp_folder.text().strip()
        if "{name}" not in paths["fb_folder"] and "{name}" not in paths["fb_name"]:
            errors.append("Flipbooks folder or file name must contain {name}")
        if not FRAME_TOKEN.search(paths["fb_name"]):
            errors.append("File name must contain a frame token like $F4")

        advanced["delete_incomplete_fb"] = self.delete_incomplete.isChecked()
        advanced["true_resolution"] = self.true_resolution.currentData()
        advanced["color_transform"] = self.color_transform.currentData()
        advanced["ocio_display"] = self._ocioValue(self.ocio_display)
        advanced["ocio_view"] = self._ocioValue(self.ocio_view)
        advanced["ocio_input_space"] = self.ocio_input_space.currentText().strip()
        advanced["ffmpeg_path"] = self.ffmpeg_path.text().strip()
        advanced["video_codec"] = self.video_codec.currentText().strip() or "auto"
        advanced["oiiotool_path"] = self.oiiotool_path.text().strip()
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

        settings["ffmpeg_cmd"] = self._lines(self.ffmpeg_cmd)
        if not any("{input}" in line for line in settings["ffmpeg_cmd"]) or \
                not any("{output}" in line for line in settings["ffmpeg_cmd"]):
            errors.append("ffmpeg command must contain {input} and {output}")

        return settings, errors

    @staticmethod
    def _lines(edit: QPlainTextEdit) -> list:
        return [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]

    @staticmethod
    def _ocioValue(combo: QComboBox) -> str:
        text = combo.currentText().strip()
        return "" if text == FROM_VIEWER else text

    # ---------- reactions ----------

    def _updateViews(self):
        current = self.ocio_view.currentText()
        display = self._ocioValue(self.ocio_display)
        views = _ocioList(lambda: hou.Color.ocio_views(display)) if display else []
        self.ocio_view.blockSignals(True)
        self.ocio_view.clear()
        self.ocio_view.addItems([FROM_VIEWER] + views)
        self.ocio_view.setCurrentText(current or FROM_VIEWER)
        self.ocio_view.blockSignals(False)

    def _updateOcioEnabled(self):
        enabled = self.color_transform.currentData() == "ocio"
        for widget in (self.ocio_display, self.ocio_view, self.ocio_input_space, self.oiiotool_path):
            widget.setEnabled(enabled)

    def _updateToolsStatus(self):
        ffmpeg_found = ffmpeg.findFFmpeg(self.ffmpeg_path.text().strip())
        oiiotool_found = ocio.findOiiotool(self.oiiotool_path.text().strip())
        encoders = ffmpeg.codecCandidates("auto", ffmpeg.availableEncoders(ffmpeg_found)) if ffmpeg_found else []
        self.tools_status.setText(
            f"ffmpeg: {ffmpeg_found or 'NOT FOUND'}\n"
            f"encoders (auto order): {', '.join(encoders) or 'unknown'}\n"
            f"oiiotool: {oiiotool_found or 'NOT FOUND (OCIO falls back to sRGB)'}\n"
            f"OCIO config: {ocio.configPath() or 'unknown'}")

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
