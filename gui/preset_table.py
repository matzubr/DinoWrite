"""Presets as a table: a column per value, typing checked per column, an empty last row to add one."""
import re

from .qt import *
from .theme import COLORS, STATES

# A frame of a range: a number or one of the frame variables Houdini knows without an expression
FRAME_VARIABLES = ("$FSTART", "$F", "$FEND", "$RFSTART", "$RFEND")
FRAME = r"-?\d+|\$(?:FSTART|F|FEND|RFSTART|RFEND)"
SIZE = r"[1-9]\d{0,4}"  # a resolution side: a whole number above 0
NAME = r".*\S.*"

TABLE_STYLE = f"""
QTableWidget {{ background-color: {COLORS['grey-dark']}; color: #eee; border: 1px solid #343434; border-radius: 2px;
               gridline-color: #262626; selection-background-color: #2b3a4a; selection-color: #fff; outline: 0; }}
QTableWidget:hover {{ border: 1px solid #6e6e6e; }}
QTableWidget:focus {{ border: 1px solid {STATES['focus']}; }}
QTableWidget::item {{ padding-left: 5px; }}
QHeaderView::section {{ background-color: {COLORS['grey']}; color: #9a9a9a; border: none;
                       border-bottom: 1px solid #343434; padding: 2px 5px; }}
QTableWidget QLineEdit {{ border: 1px solid {STATES['focus']}; border-radius: 0; padding: 0 4px; }}
"""


class _Delegate(QStyledItemDelegate):
    """The cell editor only takes what can still become a valid value of its column"""

    def __init__(self, patterns, parent=None):
        super().__init__(parent)
        self.patterns = patterns

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        pattern = self.patterns[index.column()]
        if isinstance(editor, QLineEdit) and pattern:
            editor.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), editor))
        return editor


class PresetTable(QTableWidget):
    """rows() / setRows(): lists of cell texts, the empty last row left out. Cells that don't match their column
    pattern are red with the reason in the tooltip (invalidRows)."""

    changed = Signal()
    ROW_HEIGHT = 24

    def __init__(self, headers, patterns, tips, parent=None):
        super().__init__(0, len(headers), parent)
        self.patterns = [re.compile(p) for p in patterns]
        self.tips = tips
        self.setHorizontalHeaderLabels(headers)
        self.setItemDelegate(_Delegate(patterns, self))
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        self.horizontalHeader().setHighlightSections(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                             | QAbstractItemView.AnyKeyPressed | QAbstractItemView.EditKeyPressed)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setStyleSheet(TABLE_STYLE)
        self.setMinimumHeight(self.ROW_HEIGHT * 5 + 26)
        self._filling = False
        self.itemChanged.connect(self._itemChanged)
        self._addEmptyRow()

    # ---------- values ----------

    def setRows(self, rows):
        self._filling = True
        self.setRowCount(0)
        for values in rows:
            self._addRow(values)
        self._addEmptyRow()
        self._filling = False
        self._check()
        self.changed.emit()

    def rows(self) -> list:
        """Every row with some text, cells stripped"""
        found = []
        for row in range(self.rowCount()):
            values = [self._text(row, column) for column in range(self.columnCount())]
            if any(values):
                found.append(values)
        return found

    def invalidRows(self) -> list:
        """[(row values, [the tips of the wrong cells])]"""
        return [(values, [self.tips[c] for c, v in enumerate(values) if not self.patterns[c].fullmatch(v)])
                for values in self.rows()
                if not all(pattern.fullmatch(v) for pattern, v in zip(self.patterns, values))]

    # ---------- rows ----------

    def _text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text().strip() if item is not None else ""

    def _addRow(self, values=()):
        row = self.rowCount()
        self.insertRow(row)
        for column in range(self.columnCount()):
            text = values[column] if column < len(values) else ""
            self.setItem(row, column, QTableWidgetItem(text))

    def _addEmptyRow(self):
        was = self._filling
        self._filling = True
        self._addRow()
        self._filling = was

    def _isEmpty(self, row: int) -> bool:
        return not any(self._text(row, column) for column in range(self.columnCount()))

    def removeRows(self, rows):
        self._filling = True
        for row in sorted(set(rows), reverse=True):
            if row < self.rowCount() - 1:  # the empty last row stays
                self.removeRow(row)
        self._filling = False
        self.changed.emit()

    def _selectedRows(self) -> list:
        return sorted({index.row() for index in self.selectedIndexes()})

    def _menu(self, position):
        rows = [row for row in self._selectedRows() if row < self.rowCount() - 1]
        if not rows:
            return
        menu = QMenu(self)
        menu.addAction(f"Remove {'row' if len(rows) == 1 else f'{len(rows)} rows'}", lambda: self.removeRows(rows))
        run = getattr(menu, "exec_", None) or menu.exec
        run(self.viewport().mapToGlobal(position))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.state() != QAbstractItemView.EditingState:
            self.removeRows(self._selectedRows())
            return
        super().keyPressEvent(event)

    # ---------- checking ----------

    def _itemChanged(self, item):
        if self._filling:
            return
        if item.row() == self.rowCount() - 1 and not self._isEmpty(item.row()):
            self._addEmptyRow()
        self._check()
        self.changed.emit()

    def _check(self):
        """Wrong cells red with the reason; empty rows (the last one) stay neutral"""
        was = self._filling
        self._filling = True
        for row in range(self.rowCount()):
            empty = self._isEmpty(row)
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is None:
                    continue
                wrong = not empty and not self.patterns[column].fullmatch(item.text().strip())
                item.setForeground(QColor(STATES["error"] if wrong else "#eeeeee"))
                item.setBackground(QColor("#3a1418") if wrong else QColor(0, 0, 0, 0))
                item.setToolTip(self.tips[column] if wrong else "")
        self._filling = was


def resolutionTable() -> PresetTable:
    table = PresetTable(["Width", "Height"], [SIZE, SIZE],
                        ["Width: a whole number above 0", "Height: a whole number above 0"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return table


def frameRangeTable() -> PresetTable:
    frames = " ".join(FRAME_VARIABLES)
    table = PresetTable(["Name", "Start", "End"], [NAME, FRAME, FRAME],
                        ["Name: the menu item text", f"Start: a frame number or {frames}",
                         f"End: a frame number or {frames}"])
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.Stretch)
    for column in (1, 2):
        header.setSectionResizeMode(column, QHeaderView.Fixed)
        table.setColumnWidth(column, 84)
    return table
