'''
DinoWrite main window
Python Tool for Houdini to easily write flipbooks
'''

# CONSTANTs
TITLE = "DinoWrite"
WINDOW_TITLE = TITLE

WINDOW_WIDTH = 430
WINDOW_HIGHT = 508
WINDOW_OBJECT_NAME = "DinoWriterWindow"
WIDTH_OFFSET = 20
HIGHT_OFFSET = 90

MIN_RESOLUTION_X = 128
MIN_RESOLUTION_Y = 128

FILENAME_DEFAULT = "flipbook"
FILENAME_HINT = "Flipbook name"

RESOLUTION_X_DEFAULT = "1920"
RESOLUTION_X_HINT = "Width"

RESOLUTION_Y_DEFAULT = "1080"
RESOLUTION_Y_HINT = "Height"

FRAME_START_DEFAULT = "$FSTART"
FRAME_START_HINT = "Start frame"

FRAME_END_DEFAULT = "$FEND"
FRAME_END_HINT = "End frame"

FILE_FORMAT_DEFAULT = "exr"

CONVERT_VIDEO_DEFAULT = False
BLACK_BACKGROUND_DEFAULT = True
OFF_BACKGROUND_IMAGE_DEFAULT = True
OPEN_WRITE_FOLDER_DEFAULT = True
INFO_EXPANDED_DEFAULT = False
INFO_SLIDE_MS = 240

FRAME_RANGES_DROPDOWN_DICT =  { "Global Frame Range":"$FSTART $FEND",
                                "Playbar Frame Range":"$RFSTART $RFEND",
                                "---":""}
FRAME_RANGES_COMPLETER_LIST = ['$F','$FSTART','$FEND','$RFSTART','$RFEND']
RESOLUTION_DROPDOWN_LIST =    ["Camera Resolution","1/2","2/3","---"]


BYTES_TOLERANCE = 1024
# Flipbook frames on disk per pixel (rough, while recording): Houdini's EXR RGBA half, PNG, JPG
DISK_BYTES_PER_PIXEL = {"exr": 5.0, "png": 3.0, "jpg": 0.5}
DISK_WARNING_SHARE = 0.8  # orange above 80% of the free space, red when it doesn't fit

# IMPORTs
from pathlib import Path
from re import search as regsearch

import hou
import json

from . import config, flipbook
from .core import acescg, helpers
from .core.log import hmsg, log
from .core.viewport import HouViewport
from .gui import animation, widgets
from .gui.frameless import RoundedWindow, TitleBar
from .gui.qt import *  # noqa: F403
from .gui.theme import COLORS as COLORS_PALLETE
from .gui.resources import ICONS_FOLDER, Icons as _Icons
from .gui.settings_dialog import SettingsDialog, execDialog

Icons = _Icons()

def findOpenWindow(exclude=None):
    """Visible DinoWrite window among Houdini main window children, or None"""
    for w in hou.qt.mainWindow().children():
        if w is not exclude and w.isWidgetType() and w.windowTitle() == WINDOW_TITLE and w.isVisible():
            return w
    return None


class DinoWriter(RoundedWindow, QWidget):

    def __init__(self,kwargs):
        '''
        Parent widget to houdini window to make it visible
        (Qt keeps it alive, so shelf script doesn't need to store a reference)
        '''
        super().__init__(hou.qt.mainWindow())

        # Already open: focus it. Checked before touching the viewers (no tab switching for nothing)
        opened = findOpenWindow(exclude=self)
        if opened is not None:
            log.info(f"{TITLE} is already open")
            opened.raise_()
            opened.activateWindow()
            self.deleteLater()
            return
        if hou.ui.paneTabOfType(hou.paneTabType.SceneViewer) is None:
            hmsg("No Scene Viewer to record a flipbook from")
            self.deleteLater()
            return

        '''
        Adding search path to Qt to be able to using "icons:filepath" prefix in stylesheets files
        '''
        QDir.addSearchPath("icons",ICONS_FOLDER.as_posix())


        '''
        Setting some flags to widget
        WindowTitle - allows you to track the widget among others and not paint a new widget, in case of a repeat call
        QtWindow and Frameless flags - just for TitleBar
        WA_DeleteOnClose attribute - allows to delete widget in application childrens after widget is closed
        FixedSize - Blocks the user from being able to stretch the widget in different directions
        '''
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(WINDOW_WIDTH,WINDOW_HIGHT)

        # Round antialiased edges (see gui/frameless.py)
        self.setupRoundedWindow(WINDOW_OBJECT_NAME)


        '''
        Settng proper widget position
        I'm believe that in should work on any monitor setup's
        The point is that the window does NOT spawn on the border of the monitors or beyond
        '''
        mouse_pos = QCursor.pos()
        # QDesktopWidget was removed in Qt6, QScreen API works in both
        screen = QGuiApplication.screenAt(mouse_pos) or QGuiApplication.primaryScreen()
        screenGeometry = screen.availableGeometry()
        xpoint = min( max(mouse_pos.x()-WINDOW_WIDTH/2,screenGeometry.x() + WIDTH_OFFSET) , screenGeometry.x() + screenGeometry.width() - WINDOW_WIDTH - WIDTH_OFFSET )
        ypoint = max( min(mouse_pos.y()-WINDOW_HIGHT/2+HIGHT_OFFSET,screenGeometry.y() + screenGeometry.height()-WINDOW_HIGHT-100) , screenGeometry.y() + 10 )
        self.move(QPoint(int(xpoint),int(ypoint)))


        '''
        Promoting viewport settings and kwargs
        '''
        self.hou_viewport = HouViewport(kwargs)
        self.kwargs = kwargs

        settingsfile = config.load()
        self.settings = settingsfile
        self.paths = settingsfile["paths"]
        self.formats = settingsfile["formats"]
        self.addresolution = settingsfile["custom_resolution"]
        self.addframerange = settingsfile["custom_framerange"]

        self.data = self.load_json(config.lastUsedPath())
        self.initUI()

    def initUI(self):

        ### INFO LINE
        info_frame = widgets.Frame(background_color=COLORS_PALLETE["grey"])
        info_layout = QVBoxLayout(info_frame)
        info_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        info_layout.setContentsMargins(10,5,10,5)

        self.cameraname = widgets.Label("Camera: {camera}".format(camera=self.hou_viewport.cameraName()))
        self.ramusage =   widgets.ElidedLabel("RAM Usage: {ramusage}")
        # Elided labels: long status text must not widen the fixed size window
        self.statusline = widgets.ElidedLabel("")
        self.videoline = widgets.ElidedLabel("")
        self.seqname = widgets.ColorfulLabel()
        dino_paint = widgets.HIcon(Icons.get("label_dino_paint.svg",type="Path"),size=50)
        
        # Every info line can be selected and copied (paths, names, sizes)
        for label in (self.cameraname, self.ramusage, self.statusline, self.videoline, self.seqname):
            label.setCursor(Qt.IBeamCursor)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.dino_paint = dino_paint
        # Arrow: the details (record/video/camera/memory) slide out below the name; remembered, closed by default
        self.info_toggle = widgets.PushButton("", radius=11)
        self.info_toggle.setFixedSize(QSize(22, 22))
        self.info_toggle.setIconSize(QSize(12, 12))
        self.info_toggle.setCursor(Qt.PointingHandCursor)
        self.info_toggle.clicked.connect(lambda: self.setInfoExpanded(not self.info_expanded))
        sequence_layout = widgets.HLayout([self.seqname,dino_paint,self.info_toggle],align=None)

        # The flipbook name first, then how it's recorded and encoded, camera and memory/disk
        info_layout.addLayout(sequence_layout)
        lines = QWidget()
        details_layout = QVBoxLayout(lines)
        details_layout.setContentsMargins(0, 0, 0, 0)
        for line in (self.statusline, self.videoline, self.cameraname, self.ramusage):
            details_layout.addWidget(line)
        self.info_details = widgets.Reveal(lines)
        info_layout.addWidget(self.info_details)
        self.info_expanded = bool(self.read_data("infoexpanded", INFO_EXPANDED_DEFAULT))
        self._warnings = {}

        ## MAIN SETTINGS
        main_frame = widgets.Frame(background_color=COLORS_PALLETE["grey"])
        grid_layout = QGridLayout(main_frame)

        ### FIRST LINE
        label_filename =   widgets.HBLabel("Name")
        self.filename =    widgets.LineEdit(self.read_data("name", FILENAME_DEFAULT),hint=FILENAME_HINT)
        folders_list = self.flipbooks_menu()
        self.filename.setCompleter(widgets.Completer(folders_list))
        self.filename.installEventFilter(self)
        self.menu_button = widgets.DropDownButton(menu=folders_list, callback=self.setMenuItemFile)

        grid_layout.addWidget(label_filename, 0, 0)
        grid_layout.addWidget(self.filename, 0, 1, 1, 2)
        grid_layout.addWidget(self.menu_button, 0, 3)

        ### SECOND LINE
        label_res = widgets.HBLabel("Resolution")
        self.resx = widgets.LineEdit(self.read_data("resx", RESOLUTION_X_DEFAULT),hint=RESOLUTION_X_HINT)
        self.resx.setValidator(QIntValidator())
        self.resx.setCompleter(widgets.Completer([x.split(" ")[0] for x in self.addresolution]))
        self.resx.installEventFilter(self)

        self.resy = widgets.LineEdit(self.read_data("resy", RESOLUTION_Y_DEFAULT),hint=RESOLUTION_Y_HINT)
        self.resy.setValidator(QIntValidator())
        self.resy.setCompleter(widgets.Completer([x.split(" ")[1] for x in self.addresolution]))
        self.resy.installEventFilter(self)

        self.res_menu = widgets.DropDownButton(
            menu=RESOLUTION_DROPDOWN_LIST + self.addresolution, callback=self.setMenuItemResolution)

        grid_layout.addWidget(label_res, 1, 0)
        grid_layout.addWidget(self.resx, 1, 1)
        grid_layout.addWidget(self.resy, 1, 2)
        grid_layout.addWidget(self.res_menu, 1, 3)

        ### THIRD LINE
        label_range =     widgets.HBLabel("Frame Range")
        self.framestart = widgets.LineEdit(self.read_data("framestart", FRAME_START_DEFAULT),hint=FRAME_START_HINT)
        self.framestart.setCompleter(widgets.Completer(FRAME_RANGES_COMPLETER_LIST))
        self.framestart.installEventFilter(self)

        self.frameend =   widgets.LineEdit(self.read_data("frameend", FRAME_END_DEFAULT),hint=FRAME_END_HINT)
        self.frameend.setCompleter(widgets.Completer(FRAME_RANGES_COMPLETER_LIST))
        self.frameend.installEventFilter(self)

        self.native_ranges = dict(FRAME_RANGES_DROPDOWN_DICT)
        self.native_ranges.update(self.addframerange)
        self.frame_menu = widgets.DropDownButton(menu=self.native_ranges.keys(), callback=self.setMenuItemFrameRange)

        grid_layout.addWidget(label_range, 2, 0)
        grid_layout.addWidget(self.framestart, 2, 1)
        grid_layout.addWidget(self.frameend, 2, 2)
        grid_layout.addWidget(self.frame_menu, 2, 3)

        ### FOURTH LINE
        label_fileformat = widgets.HBLabel("File Format")
        self.fileformat =  widgets.ComboBox(self.formats["pic_exts"],item=self.read_data("fileformat", FILE_FORMAT_DEFAULT))

        for index in range(self.fileformat.count()):
            self.fileformat.setItemData(index, self.fileformat.itemText(index))  # the extension; text gets the colorspace
        grid_layout.addWidget(label_fileformat, 3, 0)
        grid_layout.addWidget(self.fileformat, 3, 1,1,3)

        ## CHECKBOXES
        checkbox_frame = widgets.Frame(background_color=COLORS_PALLETE["grey"])
        checkbox_layout = QGridLayout(checkbox_frame)
        checkbox_layout.setContentsMargins(8, 6, 8, 6)
        checkbox_layout.setHorizontalSpacing(12)

        self.convertvideo =       widgets.CheckBox(
            "Convert to video",self.read_data("convertvideo", CONVERT_VIDEO_DEFAULT))
        convertvideo_icon = widgets.HIcon(Icons.get("clapperboard.svg",type="Path"),size=15)
        self.blackbackground =    widgets.CheckBox(
            "Black background", self.read_data("blackbg", BLACK_BACKGROUND_DEFAULT))
        blackbackground_icon = widgets.HIcon(Icons.get("circle-half-stroke.svg",type="Path"),size=15)
        self.offbackgroundimage = widgets.CheckBox(
            "Hide BG image",self.read_data("bgimage", OFF_BACKGROUND_IMAGE_DEFAULT))
        offbackgroundimage_icon = widgets.HIcon(Icons.get("eye-slash.svg",type="Path"),size=15)
        self.openwritefolder =    widgets.CheckBox(
            "Open result",self.read_data("openfolder", OPEN_WRITE_FOLDER_DEFAULT))
        openwritefolder_icon = widgets.HIcon(Icons.get("folder-open.svg",type="Path"),size=15)
        
        self.convertvideo.setToolTip("After the end of recording the flipbook,the entire \nsequence of files will be converted to video via ffmpeg")
        self.blackbackground.setToolTip("When recording a flipbook with white/gray background colors , the final \nimage turns out to be incorrect. \n\nThis checkbox switches the background to black during the recording of the flipbook")
        self.offbackgroundimage.setToolTip("When you use a shot sequence on the background, sometimes \nyou have to turn it off to record pure 3d and put \nthe background on the composition\n\nThis checkbox disable the background for the time of recording the flipbook and then \nreturn it to its original state")
        self.openwritefolder.setToolTip("After finishing: opens the converted video in the default player,\nor the folder with the sequence (see Settings -> Video -> Open result)")

        # Solaris: setting viewport options from Python resets the viewer lighting (Houdini bug), so these
        # can't work there. Shown off and grey; the saved values are kept for OBJ/SOP viewers.
        self.solaris_kept = {}
        if getattr(self.hou_viewport, "isLop", lambda: False)():
            for key, checkbox, icon in (("blackbg", self.blackbackground, blackbackground_icon),
                                        ("bgimage", self.offbackgroundimage, offbackgroundimage_icon)):
                self.solaris_kept[key] = checkbox.isChecked()
                checkbox.setChecked(False)
                checkbox.setCursor(Qt.ForbiddenCursor)
                for widget in (checkbox, icon):
                    widget.setEnabled(False)
                    widget.setToolTip("Not available in Solaris: changing viewport options from Python\n"
                                      "resets the viewer lighting (Headlight Only -> Normal), a Houdini bug")

        convertvideo_layout =       widgets.HLayout([self.convertvideo,convertvideo_icon])
        blackbackground_layout =    widgets.HLayout([self.blackbackground,blackbackground_icon])
        offbackgroundimage_layout = widgets.HLayout([self.offbackgroundimage,offbackgroundimage_icon])
        openwritefolder_layout =    widgets.HLayout([self.openwritefolder,openwritefolder_icon])

        # 2x2: what happens after recording on the left, the viewer during recording on the right
        checkbox_layout.addLayout(convertvideo_layout, 0, 0)
        checkbox_layout.addLayout(openwritefolder_layout, 1, 0)
        checkbox_layout.addLayout(blackbackground_layout, 0, 1)
        checkbox_layout.addLayout(offbackgroundimage_layout, 1, 1)
        
        ### MAIN BUTTON
        self.writebutton = widgets.PushButton("WRITE ", default=True,size=widgets.MAIN_SIZE+4)
        self.writebutton.setIcon(Icons.get("dino_cam.svg"))
        self.writebutton.setIconSize(QSize(35,35))
        self.writebutton.setLayoutDirection(Qt.RightToLeft)

        # LAYOUTS
        TITLE_LAYOUT = QVBoxLayout() 
        TITLE_LAYOUT.setContentsMargins(0,0,0,0)

        MAIN_LAYOUT = QVBoxLayout()
        MAIN_LAYOUT.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        MAIN_LAYOUT.setContentsMargins(10,10,10,10)

        # What to record -> options -> summary of what WRITE will do, right above it
        MAIN_LAYOUT.addWidget(main_frame)
        MAIN_LAYOUT.addWidget(checkbox_frame)
        MAIN_LAYOUT.addWidget(info_frame)
        MAIN_LAYOUT.addWidget(self.writebutton)
        self.stagger_parts = [main_frame, checkbox_frame, info_frame, self.writebutton]

        TITLE_LAYOUT.addWidget(TitleBar(self, WINDOW_TITLE, title_width=int(WINDOW_WIDTH/1.5),
                                        on_settings=self.openSettings))
        TITLE_LAYOUT.addLayout(MAIN_LAYOUT)

        self.setLayout(TITLE_LAYOUT)

        # SIGNALS
        self.filename.editingFinished.connect(self.updateColorfulLabel)
        self.menu_button.menu.triggered.connect(self.updateColorfulLabel)
        self.fileformat.currentIndexChanged.connect(self.updateColorfulLabel)
        self.resx.editingFinished.connect(self.updateRamUsage)
        self.resx.editingFinished.connect(self.updateResolutions)
        self.resy.editingFinished.connect(self.updateRamUsage)
        self.resy.editingFinished.connect(self.updateResolutions)
        self.res_menu.menu.triggered.connect(self.updateRamUsage)
        self.res_menu.menu.triggered.connect(self.updateCameraLabel)
        self.framestart.editingFinished.connect(self.updateRamUsage)
        self.frameend.editingFinished.connect(self.updateRamUsage)
        self.frame_menu.menu.triggered.connect(self.updateRamUsage)
        self.convertvideo.stateChanged.connect(self.updateFileFormat)
        self.writebutton.clicked.connect(self.main)
        self.filename.textChanged.connect(self.updateStatus)
        for line in (self.resx, self.resy):
            line.editingFinished.connect(self.updateStatus)
        self.res_menu.menu.triggered.connect(self.updateStatus)
        self.convertvideo.stateChanged.connect(self.updateStatus)
        self.fileformat.currentIndexChanged.connect(self.updateStatus)
        self.fileformat.currentIndexChanged.connect(self.updateRamUsage)
        self.fileformat.currentIndexChanged.connect(
            lambda: self.fileformat.setToolTip(self.fileformat.currentData(Qt.ToolTipRole) or ""))

        # SCRIPTS
        self.updateRamUsage()
        self.updateColorfulLabel()
        self.updateFileFormat()
        self.updateResolutions()
        self.updateStatus()
        # Height from the content (fixed width): the title bar mustn't take the spare space
        self.setInfoExpanded(self.info_expanded, animate=False)
        self.show()
        # Window parts come in one after another, once the layout has placed them
        QTimer.singleShot(0, lambda: animation.stagger(self.stagger_parts))

    def eventFilter(self, source , event) -> bool:
        if  event.type() == QEvent.FocusIn or \
            event.type() == QEvent.KeyRelease and \
            event.key() not in [Qt.Key_Return,Qt.Key_Enter]:
            self.writebutton.setDefault(False)

        elif event.type() == QEvent.KeyRelease and \
            event.key() in [Qt.Key_Return,Qt.Key_Enter]:
            if self.writebutton.isDefault():
                self.writebutton.animateClick()
            self.writebutton.setDefault(True)

        if event.type() == QEvent.FocusOut and \
            source in [self.resx,self.resy]:
            self.updateResolutions()

        return super().eventFilter(source, event)
    
    # ---------- info details ----------

    def setInfoExpanded(self, expanded: bool, animate: bool = True):
        """Slide the info details out/in, the window grows/shrinks with them. Remembered for the next time."""
        self.info_expanded = expanded
        details = self.info_details
        target = details.sizeHint().height() if expanded else 0
        self._updateInfoToggle()
        if not animate or not self.isVisible():
            details.setMaximumHeight(target)
            details.setVisible(expanded)
            self.setFixedHeight(self.contentHeight())
            return
        start = details.height() if details.isVisible() else 0
        details.setMaximumHeight(start)
        details.setVisible(True)
        slide = QVariantAnimation(self)
        slide.setDuration(INFO_SLIDE_MS)
        slide.setStartValue(start)
        slide.setEndValue(target)
        slide.setEasingCurve(QEasingCurve.OutCubic)

        def step(value):
            details.setMaximumHeight(int(value))
            self.setFixedHeight(self.contentHeight())  # layout spacing included
        slide.valueChanged.connect(step)
        def done():
            details.setVisible(self.info_expanded)
            self.setFixedHeight(self.contentHeight())
        slide.finished.connect(done)
        if getattr(self, "_infoSlide", None) is not None:
            self._infoSlide.stop()
        self._infoSlide = slide
        slide.start()
        try:
            self.saveState()
        except OSError as e:
            log.warning("Can't remember the info state: %s", e)

    def contentHeight(self) -> int:
        """Window height the layout needs now (the layout is refreshed first: a hidden part must not count)"""
        # inner layouts first: a frame's layout updates its size hint only on the next event loop otherwise
        for inner in (self.info_details.parentWidget().layout(), self.layout()):
            inner.invalidate()
            inner.activate()
        return self.layout().sizeHint().height()

    def setInfoWarning(self, key: str, text: str = "", color: str = ""):
        """A warning in the details: also shown on the arrow while they're closed"""
        if text:
            self._warnings[key] = (text, color)
        else:
            self._warnings.pop(key, None)
        self._updateInfoToggle()

    def _updateInfoToggle(self):
        icon = Icons.get("angle-down2.svg", type="Path")
        pixmap = QPixmap(icon).transformed(QTransform().rotate(180 if self.info_expanded else 0),
                                           Qt.SmoothTransformation)
        self.info_toggle.setIcon(QIcon(pixmap))
        style = widgets.styles.get("mainbutton")
        tooltip = "Hide details" if self.info_expanded else "Show details: record, video, camera, memory"
        if self._warnings and not self.info_expanded:
            color = COLORS_PALLETE["crimson"] if any(c == COLORS_PALLETE["crimson"] for _, c in
                                                     self._warnings.values()) else COLORS_PALLETE["orange"]
            style += f"QPushButton {{ border: 1px solid {color}; background-color: {color}55; }}"
            tooltip += "\n\n" + "\n".join(text for text, _ in self._warnings.values())
        self.info_toggle.setStyleSheet(style)
        self.info_toggle.setToolTip(tooltip)

    def updateResolutions(self):
        # Empty/invalid values are left as is, main() reports empty fields
        for line, minimum in ((self.resx, MIN_RESOLUTION_X), (self.resy, MIN_RESOLUTION_Y)):
            value = helpers.toInt(line.text())
            if value is not None:
                line.setText(str(max(value, minimum)))

    def updateStatus(self):
        """Status line: name problems (red), how the flipbook will be recorded and encoded"""
        problem = helpers.nameProblem(self.filename.text())
        self.filename.setStyleSheet(widgets.styles.get("lineedit") +
                                    (f"QLineEdit {{border: 1px solid {COLORS_PALLETE['red']};}}" if problem else ""))
        self.writebutton.setEnabled(not problem)
        self.writebutton.setToolTip(problem)
        warning = "" if problem else self.aspectWarning()
        status_color = COLORS_PALLETE["crimson"] if problem else (COLORS_PALLETE["orange"] if warning else "#ffffff")
        self.statusline.setStyleSheet(f"background-color: transparent; color: {status_color};")
        self.statusline.setExtraToolTip(
            "Resolution aspect differs from the camera: Houdini stretches the image to it.\n"
            "Use 'Camera Resolution' in the resolution menu (or 1/2, 2/3 of it)." if warning else "")
        if problem and not getattr(self, "_name_problem", ""):
            animation.shake(self.filename)  # the name just became invalid
        self._name_problem = problem
        animation.setTextAnimated(self.statusline, problem or warning or self.recordStatus())
        self.setInfoWarning("status", problem or warning, status_color)

        self.videoline.setExtraToolTip("")
        parts = [f"Video: {self.videoStatus()}" if self.convertvideo.isChecked() else "Video: off"]
        advanced = self.settings["advanced"]
        keeps_exr = not (self.convertvideo.isChecked() and advanced.get("conversion_delete_input_sequence"))
        if self.fileFormat() == "exr" and keeps_exr:
            exr = (["ACEScg"] if advanced.get("exr_acescg", True) else []) + [
                acescg.compressionArg(advanced.get("exr_compression", "dwaa")).split(":")[0].upper()]
            parts.append("EXR: " + ", ".join(exr))
        animation.setTextAnimated(self.videoline, " · ".join(parts))

    def aspectWarning(self) -> str:
        """Resolution with another aspect than the camera: the flipbook comes out squashed/stretched"""
        resx, resy = helpers.toInt(self.resx.text()), helpers.toInt(self.resy.text())
        camera_aspect = getattr(self.hou_viewport, "cameraAspect", lambda: None)()
        if not resx or not resy or not isinstance(camera_aspect, (int, float)) or camera_aspect <= 0:
            return ""
        if abs(resx / resy - camera_aspect) <= 0.01 * camera_aspect:
            return ""
        return f"Record: {resx}×{resy} ≠ camera aspect {camera_aspect:.2f}, stretched"

    def recordStatus(self) -> str:
        resx, resy = helpers.toInt(self.resx.text()), helpers.toInt(self.resy.text())
        if resx is None or resy is None:
            return "Record: -"
        mode = self.settings["advanced"].get("true_resolution", "auto")
        separate = mode == "always" or (mode == "auto" and not self.fitsMaximizedViewport((resx, resy)))
        if separate and getattr(self.hou_viewport, "isLop", lambda: False)():
            return f"Record: {resx}×{resy} in viewport (Solaris: scaled)"
        where = "separate viewer" if separate else "viewport"
        return f"Record: {resx}×{resy} in {where}"

    def fitsMaximizedViewport(self, resolution) -> bool:
        """Estimate: maximized viewport is about the size of the screen with the viewer (in device pixels)"""
        try:
            geometry = self.hou_viewport.getPaneTab().qtScreenGeometry()
            screen = QGuiApplication.screenAt(geometry.center()) or QGuiApplication.primaryScreen()
        except Exception:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return True
        size = screen.availableGeometry().size() * screen.devicePixelRatio()
        return resolution[0] <= size.width() and resolution[1] <= size.height()

    def videoStatus(self) -> str:
        # Convert to video always records EXR (see updateFileFormat)
        self.videoline.setExtraToolTip("EXR is encoded with the sRGB curve: the video looks like MPlay after recording")
        return "sRGB (like MPlay)"

    def fileFormat(self) -> str:
        """Selected extension (the item text also shows the colorspace)"""
        return self.fileformat.currentData() or self.fileformat.currentText().split()[0]

    def updateFileFormat(self):
        state = self.convertvideo.isChecked()
        if state:
            self.fileformat.setCurrentIndex(max(self.fileformat.findData("exr"), 0))
            self.fileformat.setDisabled(True)
        else:
            self.fileformat.setDisabled(False)
        self.updateFormatColorspaces()

    def updateFormatColorspaces(self):
        """'exr (ACEScg)', 'png (ACES 1.0 - SDR Video)': how to read the files in Nuke (details in the tooltip)"""
        advanced = self.settings["advanced"]
        keeps_exr = not (self.convertvideo.isChecked() and advanced.get("conversion_delete_input_sequence"))
        viewer = getattr(self.hou_viewport, "getPaneTab", lambda: None)()
        for index in range(self.fileformat.count()):
            ext = self.fileformat.itemData(index)
            name, how = acescg.readColorspace(ext, viewer, advanced.get("exr_acescg", True), keeps_exr)
            self.fileformat.setItemText(index, f"{ext}  ({name})")
            self.fileformat.setItemData(index, how, Qt.ToolTipRole)
        self.fileformat.setToolTip(self.fileformat.currentData(Qt.ToolTipRole) or "")

    def updateColorfulLabel(self):

        label =     ["Sequence: ",COLORS_PALLETE["white"]]
        separator = [".",COLORS_PALLETE["white"]]
        final_list = label

        fb_name = self.paths.get("fb_name")
        version = helpers.flipbookVersion(self.paths.get("fb_folder"), self.filename.text())
        for name in fb_name.split("."):
            part = name.format(name=self.filename.text(),
                                version=version,
                                fileformat=self.fileFormat())
            
            if name == "{name}":
                final_list.append(part)
                final_list.append(COLORS_PALLETE["orange"])
            elif regsearch(r"\$F\d+",name):
                final_list.append(part)
                final_list.append(COLORS_PALLETE["green"])
            elif name == "{version}":
                final_list.append(part)
                final_list.append(COLORS_PALLETE["yellow"])
            elif name == "{fileformat}":
                final_list.append(part)
                final_list.append(COLORS_PALLETE["blue"])
            else:
                final_list.append(name)
                final_list.append(COLORS_PALLETE["white"])
            final_list+=separator
        previous = self.seqname.text()
        self.seqname.update(final_list)
        if previous and self.seqname.text() != previous and self.isVisible():
            animation.hop(self.dino_paint)  # new name or version
            animation.refreshText(self.seqname)

    def updateCameraLabel(self):
        animation.setTextAnimated(self.cameraname, f"Camera: {self.hou_viewport.cameraName()}")

    def setMenuItemFile(self):
        item = self.sender().text()
        self.filename.setText(item)

    def setMenuItemResolution(self):
        item = self.sender().text()

        if item == "Camera Resolution":
            camera_res = self.hou_viewport.cameraResolution()
            self.resx.setText(str(camera_res[0]))
            self.resy.setText(str(camera_res[1]))
        elif item.find("/")!=-1:
            divisible,divider = item.split("/")
            ratio = int(divisible) / int(divider)
            resx = helpers.toInt(self.resx.text())
            resy = helpers.toInt(self.resy.text())
            if resx is None or resy is None:
                log.warning("Set resolution before dividing it")
                return
            newresx = max(round(resx*ratio), MIN_RESOLUTION_X)
            newresy = max(round(resy*ratio), MIN_RESOLUTION_Y)
            self.resx.setText(str(newresx))
            self.resy.setText(str(newresy))
        else:
            x, y = item.split(" ")
            self.resx.setText(str(x))
            self.resy.setText(str(y))

    def setMenuItemFrameRange(self):
        item = self.sender().text()
        start,end = self.native_ranges[item].split()

        self.framestart.setText(start)
        self.frameend.setText(end)

    def ramUsage(self):
        """Returns approximate RAM usage in MB or None if fields can't be evaluated"""
        resx = helpers.toInt(self.resx.text())
        resy = helpers.toInt(self.resy.text())
        frame_start = helpers.evalFrame(self.framestart.text())
        frame_end = helpers.evalFrame(self.frameend.text())
        if None in (resx, resy, frame_start, frame_end):
            return None

        pixels_count = resx * resy
        image_in_bytes = pixels_count * 4
        image_in_mbytes = image_in_bytes / BYTES_TOLERANCE / BYTES_TOLERANCE
        frame_range = max(int(frame_end - frame_start) + 1,1)
        mbytes = image_in_mbytes * frame_range
        return mbytes
    
    def diskUsage(self):
        """(estimated flipbook size, free space) in bytes; size is None if fields can't be evaluated.

        Peak while recording, before the EXR pass compresses the frames (DWAA makes them several times smaller).
        """
        resx, resy = helpers.toInt(self.resx.text()), helpers.toInt(self.resy.text())
        frame_start, frame_end = helpers.evalFrame(self.framestart.text()), helpers.evalFrame(self.frameend.text())
        free = helpers.freeSpace(self.flipbooksRoot(self.filename.text()))
        if None in (resx, resy, frame_start, frame_end):
            return None, free
        frames = max(int(frame_end - frame_start) + 1, 1)
        per_pixel = DISK_BYTES_PER_PIXEL.get(self.fileFormat(), DISK_BYTES_PER_PIXEL["exr"])
        return resx * resy * per_pixel * frames, free

    def updateRamUsage(self):
        """Memory line: RAM for MPlay, disk for the frames and the free space where they go"""
        ram = self.ramUsage()
        ramtext = "RAM -" if ram is None else f"RAM {helpers.formatBytes(ram * BYTES_TOLERANCE * BYTES_TOLERANCE)}"
        size, free = self.diskUsage()
        disk = "Disk -" if size is None else f"Disk ~{helpers.formatBytes(size)}"
        if free is not None:
            disk += f" · {helpers.formatBytes(free)} free"
        color, tip = "#ffffff", ""
        if size is not None and free is not None and size > free * DISK_WARNING_SHARE:
            color = COLORS_PALLETE["crimson"] if size > free else COLORS_PALLETE["orange"]
            tip = "The flipbook may not fit on the disk: free some space or record fewer frames / smaller"
        self.ramusage.setStyleSheet(f"background-color: transparent; color: {color};")
        self.setInfoWarning("disk", tip, color)
        self.ramusage.setExtraToolTip(tip)
        animation.setTextAnimated(self.ramusage, f"Memory: {ramtext} · {disk}")

    def flipbooksRoot(self, name: str = "") -> Path:
        """Folder that holds all flipbooks: parent of 'paths.fb_folder' for this name"""
        fb_folder = hou.text.expandString(self.paths.get("fb_folder")).format(name=name or FILENAME_DEFAULT)
        return Path(fb_folder).resolve().parent

    def flipbooks_menu(self):
        """Existing flipbook names; empty while the flipbooks folder doesn't exist yet (asked on WRITE)"""
        pfolder = self.flipbooksRoot(self.data.get("name"))
        if not pfolder.is_dir():
            return []
        return [x.name for x in pfolder.iterdir() if x.is_dir()]

    def confirmFlipbooksRoot(self) -> bool:
        """Ask to create the flipbooks folder when writing for the first time.

        No -> window stays open, so the path can be changed in settings.
        """
        pfolder = self.flipbooksRoot(self.filename.text())
        if pfolder.is_dir():
            return True
        answer = hou.ui.displayMessage(
            f"Flipbooks folder doesn't exist:\n{pfolder.as_posix()}\n\n"
            "Create it? (you can change the path in Settings, gear button)",
            buttons=("Create", "Cancel"), default_choice=0, close_choice=1, title="DinoWrite")
        if answer != 0:
            log.info("Flipbooks folder not created, nothing written")
            return False
        pfolder.mkdir(parents=True, exist_ok=True)
        return True

    def main(self):
        if getattr(self, "_writing", False):
            return 0  # already fading out to record

        # Check lineedits validness
        check_lines = [self.filename,self.resx,self.resy,self.framestart,self.frameend]
        empty_array = []
        string_of_empty = ""
        for line in check_lines:
            if len(line.text().strip())==0:
                empty_array.append(line.placeholderText())
        if len(empty_array)>0:
            for i,element in enumerate(empty_array):
                string_of_empty += f"{str(i+1)}.{element}\n"
            hmsg(f"Empty line detected!\nPlease check values in:\n{string_of_empty}")
            return 0

        problem = helpers.nameProblem(self.filename.text())
        if problem:
            hmsg(problem)
            return 0

        self.updateResolutions()
        if None in (helpers.toInt(self.resx.text()), helpers.toInt(self.resy.text())):
            hmsg(f"Resolution should be numbers: {self.resx.text()} x {self.resy.text()}")
            return 0

        if not self.confirmFlipbooksRoot():
            return 0

        data = self.saveState()

        # WRITE grows and fades out together with the window (HotBox style), then recording starts
        self._writing = True
        self.writebutton.playPress()
        self.fadeOut(lambda: self.startRecording(data), duration=animation.PRESS_MS)

    def startRecording(self, data: dict):
        self.close()
        hou.hipFile.saveAndBackup()
        flipbook.start(data,self.kwargs)

    def collectData(self) -> dict:
        return {
            "name": self.filename.text(),
            "resx": self.resx.text(),
            "resy": self.resy.text(),
            "aspect": self.hou_viewport.cameraPixelAspect(),
            "framestart": self.framestart.text(),
            "frameend": self.frameend.text(),
            "fileformat": self.fileFormat(),
            "convertvideo": self.convertvideo.isChecked(),
            "blackbg": self.blackbackground.isChecked(),
            "bgimage": self.offbackgroundimage.isChecked(),
            "openfolder": self.openwritefolder.isChecked(),
            "infoexpanded": self.info_expanded,
            **self.solaris_kept,  # Solaris: unchecked here, OBJ/SOP keep the user's choice
        }

    def saveState(self) -> dict:
        """Remember current field values for the next time the window opens"""
        data = self.collectData()
        data_file = config.lastUsedPath()
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return data

    def openSettings(self):
        dialog = SettingsDialog(self)  # centered over DinoWrite, same look
        if execDialog(dialog) == QDialog.Accepted:
            # Rebuild the window with new settings, keeping current field values
            self.saveState()
            self.close()
            from . import show
            show(self.kwargs)

    def load_json(self, file):
        try:
            with open(file, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:  # broken file (crash while writing): start with defaults
            log.warning("Can't read last used values %s: %s", file, e)
            return {}

    def read_data(self, key, value):
        return self.data.get(key) if self.data.get(key) != None else value