"""Línea de tiempo con puntos de entrada/salida arrastrables."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..media import fmt_duration
from . import theme


class Timeline(QWidget):
    seek_requested = Signal(float)
    trim_changed = Signal(object, object)       # mientras se arrastra
    trim_committed = Signal(object, object)     # al soltar

    HANDLE = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.duration = 0.0
        self.pos = 0.0
        self.tin: float | None = None
        self.tout: float | None = None
        self._drag: str | None = None

    # --- API ----------------------------------------------------------
    def set_duration(self, d):
        self.duration = max(0.0, d or 0.0)
        self.update()

    def set_position(self, t):
        self.pos = t
        self.update()

    def set_trim(self, tin, tout):
        self.tin, self.tout = tin, tout
        self.update()

    # --- geometría ----------------------------------------------------
    def _bar(self) -> QRectF:
        return QRectF(10, 14, self.width() - 20, 18)

    def _x(self, t):
        b = self._bar()
        return b.left() + (t / self.duration) * b.width() if self.duration else b.left()

    def _t(self, x):
        b = self._bar()
        if not self.duration:
            return 0.0
        return min(self.duration, max(0.0, (x - b.left()) / b.width() * self.duration))

    def _eff(self):
        return (self.tin or 0.0, self.tout if self.tout is not None else self.duration)

    # --- pintura ------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self._bar()
        path = QPainterPath()
        path.addRoundedRect(b, 4, 4)
        p.fillPath(path, QColor(theme.CARD))
        if self.duration:
            a, z = self._eff()
            sel = QRectF(self._x(a), b.top(), self._x(z) - self._x(a), b.height())
            col = QColor(theme.TRIM)
            col.setAlpha(70 if (self.tin is not None or self.tout is not None) else 25)
            p.fillRect(sel, col)
            p.setPen(QPen(QColor(theme.TRIM), 2))
            for t, left in ((a, True), (z, False)):
                x = self._x(t)
                p.drawLine(int(x), int(b.top() - 4), int(x), int(b.bottom() + 4))
                tri = QPainterPath()
                d = self.HANDLE if left else -self.HANDLE
                tri.moveTo(x, b.top() - 4)
                tri.lineTo(x + d, b.top() - 4)
                tri.lineTo(x, b.top() + 4)
                tri.closeSubpath()
                p.fillPath(tri, QColor(theme.TRIM))
            x = self._x(self.pos)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(int(x), int(b.top() - 6), int(x), int(b.bottom() + 6))
            p.setPen(QColor(theme.TEXT_DIM))
            f = p.font()
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            p.setFont(f)
            xa = min(max(self._x(a), b.left()), b.right() - 120)
            xz = max(min(self._x(z), b.right()), b.left() + 120)
            if xz - xa < 90:  # evita que se solapen
                xz = xa + 90
            p.drawText(QRectF(xa, b.bottom() + 2, 120, 14), Qt.AlignLeft, fmt_duration(a))
            p.drawText(QRectF(xz - 120, b.bottom() + 2, 120, 14), Qt.AlignRight, fmt_duration(z))

    # --- ratón ---------------------------------------------------------
    def _hit(self, x):
        if not self.duration:
            return None
        a, z = self._eff()
        if abs(x - self._x(a)) <= self.HANDLE + 2:
            return "in"
        if abs(x - self._x(z)) <= self.HANDLE + 2:
            return "out"
        return None

    def mousePressEvent(self, e):
        x = e.position().x()
        self._drag = self._hit(x) or "seek"
        if self._drag == "seek":
            self.seek_requested.emit(self._t(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if not self._drag:
            self.setCursor(Qt.SizeHorCursor if self._hit(x) else Qt.PointingHandCursor)
            return
        t = self._t(x)
        a, z = self._eff()
        if self._drag == "seek":
            self.seek_requested.emit(t)
        elif self._drag == "in":
            self.tin = min(t, z - 0.1) if t > 0.01 else None
            self.trim_changed.emit(self.tin, self.tout)
            self.seek_requested.emit(self.tin or 0.0)
        elif self._drag == "out":
            self.tout = max(t, a + 0.1) if t < self.duration - 0.01 else None
            self.trim_changed.emit(self.tin, self.tout)
            self.seek_requested.emit(self.tout if self.tout is not None else self.duration)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag in ("in", "out"):
            self.trim_committed.emit(self.tin, self.tout)
        self._drag = None
