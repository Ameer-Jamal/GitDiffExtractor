from PyQt5.QtCore    import Qt, QPoint, QEvent, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QFrame, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout
)


class FilterableBranchSelector(QWidget):
    selectionChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Visible field
        self.line_edit = QLineEdit(self)
        self.line_edit.setReadOnly(True)
        # increase minimum width
        self.line_edit.setMinimumWidth(500)
        self.line_edit.installEventFilter(self)

        # Layout for this widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit)
        self.setLayout(layout)

        # Popup container
        self.popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)

        # Filter input
        self.filter_edit = QLineEdit(self.popup)
        self.filter_edit.setPlaceholderText("Type to filter…")
        popup_layout.addWidget(self.filter_edit)

        # Branch list
        self.list_widget = QListWidget(self.popup)
        popup_layout.addWidget(self.list_widget)

        # Signal connections
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.list_widget.itemClicked.connect(self._select_item)


    def eventFilter(self, source, event):
        if source is self.line_edit and event.type() == QEvent.MouseButtonPress:
            self._show_popup()
            return True
        return super().eventFilter(source, event)


    def _show_popup(self):
        # Position and show popup; ensure popup width matches or exceeds the field
        width = max(self.line_edit.width(), self.line_edit.minimumWidth())
        p = self.line_edit.mapToGlobal(QPoint(0, self.line_edit.height()))
        self.popup.move(p)
        self.popup.resize(width, 200)
        self.popup.show()
        self.filter_edit.clear()
        self.filter_edit.setFocus()
        self._apply_filter("")


    def set_items(self, branches):
        """Populate the list of branches."""
        self.list_widget.clear()
        for b in branches:
            QListWidgetItem(b, self.list_widget)


    def _apply_filter(self, text):
        """Hide non-matching items."""
        t = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            hidden = bool(t and t not in item.text().lower())
            item.setHidden(hidden)


    def _select_item(self, item):
        """Select branch and close popup."""
        self.line_edit.setText(item.text())
        self.popup.hide()
        self.selectionChanged.emit(item.text())


    def current_text(self):
        return self.line_edit.text()

    def set_current_text(self, text):
        self.line_edit.setText(text)
