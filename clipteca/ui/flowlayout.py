from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """Layout que reparte los widgets en líneas (para las etiquetas tipo chip)."""

    def __init__(self, parent=None, spacing: int = 4):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        w = self.geometry().width() or 240
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self._items:
            w = it.sizeHint()
            nx = x + w.width() + sp
            if nx - sp > rect.right() and line_h > 0:
                x, y = rect.x(), y + line_h + sp
                nx = x + w.width() + sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), w))
            x = nx
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()
