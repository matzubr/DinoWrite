from .qt import *  # noqa: F403
from .animation import AnimatedButton, AnimatedCheckBox, fadeMenus
from .resources import FONT_FILE, STYLESHEETS_FILE, Icons as _Icons, StyleSheet
from ..core.log import log

styles = StyleSheet(STYLESHEETS_FILE.as_posix())
Icons = _Icons()

#CONSTANTs
MAIN_FONT =   styles.get("main").get('font')
MAIN_SIZE =   max(styles.get("main").get('fontsize'),3)
TEXT_WEIGHT = {"normal": QFont.Medium,"bold": QFont.Bold}

if MAIN_FONT=="_custom_":
    font_id = QFontDatabase.addApplicationFont(FONT_FILE.as_posix())
    if font_id < 0:
        log.warning("No font found in 'misc/font.ttf'")
        MAIN_FONT = "Arial"
    else:
        MAIN_FONT = QFontDatabase.applicationFontFamilies(font_id)[0]

def Completer(array:list) -> QCompleter: 
    completer = QCompleter(array)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setCompletionMode(QCompleter.InlineCompletion)
    return completer

class Frame(QFrame):
    """
    Stylized Frame
    """
    def __init__(self,
                background_color:str="#2d2d2d",
                border_radius:int=5,
                margins:int=1,
                parent=None) -> QFrame:
        
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Sunken)
        self.setContentsMargins(margins,margins,margins,margins)
        self.setStyleSheet(f"background-color:{background_color};\
                            border-radius: {border_radius}px;")

class Label(QLabel):
    """
    Simple Label with font,size and weight settings
    """
    def __init__(self,
                label:str="",
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE-2,
                weight:str="normal",
                parent=None) -> QLabel:
        
        super().__init__(parent)
        self.setText(label)
        self.setFont(QFont(font,size,weight=TEXT_WEIGHT[weight]))
        self.setStyleSheet(styles.get("label"))

class HBLabel(Label):
    """
    Houdini bold , right-align style label for lineedits
    """
    def __init__(self,
                label:str="",
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                weight:str="bold",
                parent=None) -> QLabel:

        super().__init__(label=label,font=font,size=size-1,weight=weight,parent=parent)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

class ColorfulLabel(Label):
    """Colorful label for indicating user inputs. Text that doesn't fit ends with '…' (full text in the
    tooltip) instead of widening the layout: its size hint is the full text, its minimum is small.

    Args:
        Args should be in %2 to match type like {label} - {color}

    Returns:
        Label widget with colored strings
    """
    def __init__(self,
                labels_list:list=None,
                font=MAIN_FONT,
                size=MAIN_SIZE,
                parent=None) -> QLabel:

        self._parts = []
        super().__init__(font=font,size=size,parent=parent)
        self.setMinimumWidth(1)
        self.update(labels_list or [])

    def update(self,labels_list):
        if len(labels_list)%2!=0:
            log.warning("ColorfulLabel expects label, color pairs: %s", labels_list)
            return
        self._parts = list(zip(labels_list[0::2], labels_list[1::2]))
        self.updateGeometry()
        self._elide()

    def fullText(self) -> str:
        """Plain text of all the parts, not elided"""
        return "".join(str(label) for label, _ in self._parts)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        margins = self.contentsMargins()
        return QSize(self.fontMetrics().horizontalAdvance(self.fullText()) + margins.left() + margins.right() + 2,
                     hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(1, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        """The longest part (the flipbook name) gets shortened with '…': version, frames and extension stay"""
        import html

        metrics = self.fontMetrics()
        labels = [str(label) for label, _ in self._parts]
        overflow = metrics.horizontalAdvance(self.fullText()) - (self.contentsRect().width() - 2)
        elided = self.isVisible() and overflow > 0 and bool(labels)
        if elided:
            longest = max(range(len(labels)), key=lambda index: metrics.horizontalAdvance(labels[index]))
            label = labels[longest]
            target = metrics.horizontalAdvance(label) - overflow - metrics.horizontalAdvance("…")
            while label and metrics.horizontalAdvance(label) > target:
                label = label[:-1]
            labels[longest] = label + "…"
        QLabel.setText(self, "".join(f"<font color='{color}'>{html.escape(label)}</font>"
                                     for label, (_, color) in zip(labels, self._parts) if label))
        self.setToolTip(self.fullText() if elided else "")

class ElidedLabel(Label):
    """One line label that never widens its layout: text that doesn't fit ends with '…',
    the full text is shown in the tooltip. (A long QLabel sets its minimum width to the text
    width, which pushes everything in a fixed size window out of the window.)"""
    def __init__(self, label:str="", **kwargs) -> QLabel:
        self._full_text = ""
        self._extra_tooltip = ""
        super().__init__(**kwargs)  # calls setText()
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(1)
        self.setText(label)

    def setText(self, text: str):
        self._full_text = text
        self._elide()

    def text(self) -> str:
        return self._full_text

    def setExtraToolTip(self, tooltip: str):
        """Tooltip shown in addition to the full text (when it's elided)"""
        self._extra_tooltip = tooltip
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(self.width(), 1))
        super().setText(shown)
        tooltip = self._full_text if shown != self._full_text else ""
        self.setToolTip("\n\n".join(t for t in (tooltip, self._extra_tooltip) if t))

class LineEdit(QLineEdit):
    """
    Simple LineEdit with func of making bold like Houdini
    """
    def __init__(self,
                spawntext:str="",
                hint:str=None,
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                parent=None) -> QLineEdit:
        
        super().__init__(parent)
        self.setText(spawntext)
        self.setFont(QFont(font,size,))
        self.setStyleSheet(styles.get("lineedit"))

        if hint:
            self.setPlaceholderText(hint)

        self.editingFinished.connect(lambda: self.makeBold(spawntext,font,size))

    def makeBold(self,spawntext,font,size):
        if spawntext!=self.text():
            self.setFont(QFont(font,size-1,weight=TEXT_WEIGHT["bold"]))
        else:
            self.setFont(QFont(font,size,weight=TEXT_WEIGHT["normal"]))

class DropDownButton(AnimatedButton, QPushButton):
    """
    Button which dropdown context menu with a bunch of actions.

    Each action keeps its menu item in data() (callbacks read self.sender().data()), so the shown text
    can change: labeler(item) -> text is asked every time the menu opens (e.g. "1/2  (960×540)").
    icons: {item: icon file} shown at icon_size px.
    """
    def __init__(self,icon:str=None,
                title:str="",
                menu:list=[],
                callback:list=None,
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                icons:dict=None,
                icon_size:int=0,
                labeler=None,
                parent=None) -> QPushButton:

        super().__init__(parent)
        self.setupAnimation()

        self.setText(title if not icon else "")
        self.setFont(QFont(font,size))
        self.setStyleSheet(styles.get("button"))
        self.setFocusPolicy(Qt.ClickFocus)
        buttonsize = 25
        self.setFixedSize(QSize(buttonsize,buttonsize))

        self.setCheckable(True)
        self.setChecked(False)

        if icon:
            self.setIcon(Icons.get(icon))

        self.menu = QMenu()
        self.menu.setFont(QFont(font,size))
        style = styles.get("menu")
        if icon_size:
            style += f"QMenu{{icon-size:{int(icon_size)}px;}}"
        self.menu.setStyleSheet(style)
        self.menu.setLayoutDirection(Qt.RightToLeft)
        self.menu.setCursor(Qt.PointingHandCursor)
        fadeMenus(self.menu)
        self.setMenu(self.menu)
        self.labeler = labeler
        if labeler is not None:
            self.menu.aboutToShow.connect(self.relabel)

        icons = icons or {}
        menu = list(menu)
        if len(menu)==0:
            menu.append("No folders found")

        for action_name in menu:
            if action_name=="---":
                self.menu.addSeparator()
                continue
            action = QAction(action_name,self)
            action.setData(action_name)
            item_icon = Icons.get(icons[action_name]) if action_name in icons else None
            if item_icon is not None:
                action.setIcon(item_icon)
            if action_name!="No folders found":
                action.triggered.connect(callback)
            self.menu.addAction(action)

    def relabel(self):
        """Menu texts from the labeler (the item itself when it returns nothing or fails)"""
        for action in self.menu.actions():
            item = action.data()
            if not item:
                continue
            try:
                text = self.labeler(item)
            except Exception as e:  # noqa: BLE001 - a preview must never break the menu
                log.warning("Menu preview for '%s': %s", item, e)
                text = None
            action.setText(text or item)

class CheckBox(AnimatedCheckBox, QCheckBox):
    """
    CheckBox with an animated hover glow and a flash on toggle
    """
    def __init__(self,
                label:str="",
                default:bool=False,
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                parent=None) -> QCheckBox:
        
        super().__init__(parent)
        
        self.setText(label)
        self.setFont(QFont(font,size))
        self.setStyleSheet(styles.get("checkbox"))
        self.setChecked(default)
        self.setupAnimation()  # after the initial state: no flash on open
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.PointingHandCursor)

        self.clicked.connect(lambda: self.makeBold(default,font,size))

    def makeBold(self,state,font,size):
        if state!=self.isChecked():
            self.setFont(QFont(font,size,weight=TEXT_WEIGHT["bold"]))
        else:
            self.setFont(QFont(font,size,weight=TEXT_WEIGHT["normal"]))

class ComboBox(QComboBox):
    """
    Simple ComboBox
    """
    def __init__(self,
                items:list=[],
                item:str=None,
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                parent=None) -> QComboBox:
        
        super().__init__(parent)

        self.setFont(QFont(font,size))
        self.setStyleSheet(styles.get("combobox"))
        self.setFocusPolicy(Qt.ClickFocus)
        self.insertItems(0,items)

        if item:
            self.setCurrentText(item)
        state = self.currentIndex()

        self.currentIndexChanged.connect(lambda: self.makeBold(state,font,size))

    def makeBold(self,state,font,size):
        if state!=self.currentIndex():
            self.setFont(QFont(font,size,weight=TEXT_WEIGHT["bold"]))
        else:
            self.setFont(QFont(font,size,weight=TEXT_WEIGHT["normal"]))

class PushButton(AnimatedButton, QPushButton):
    """
    Button with HotBox style hover/press animation (gui/animation.py)
    """
    def __init__(self,
                label:str="",
                font:str=MAIN_FONT,
                size:int=MAIN_SIZE,
                default:bool=False,
                radius:float=5,
                parent=None) -> QPushButton:
        
        super().__init__(parent)
        self.setupAnimation(radius)

        self.setText(label)
        self.setFont(QFont(font,size))
        self.setStyleSheet(styles.get("mainbutton"))
        self.setFocusPolicy(Qt.ClickFocus)
        self.setDefault(default)

class HIcon(QLabel):

    def __init__(self,iconpath:str="photo.svg",size:int=30,parent=None) -> QLabel:
        super().__init__(parent)

        iconpixmap = QPixmap(iconpath)
        iconpixmap = iconpixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(iconpixmap)
        self.setFixedWidth(size)

class HLayout(QHBoxLayout):
    """
    Procedural layout which align all input widgets to the left
    """

    def __init__(self, widgets:list=[],align=Qt.AlignLeft,parent=None) -> QHBoxLayout:
        super().__init__(parent)

        if align:
            self.setAlignment(align)
        
        for w in widgets:
            self.addWidget(w)

class Reveal(QWidget):
    """Shows its content cut at its own height: animating the height slides the content out like a blind
    (a layout would squash the lines into the smaller height instead)"""

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.content = content
        content.setParent(self)

    def sizeHint(self) -> QSize:
        return self.content.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.content.setGeometry(0, 0, self.width(), self.content.sizeHint().height())
