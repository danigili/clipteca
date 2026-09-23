"""Cuadrícula de miniaturas (modelo + delegado)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap, QPixmapCache
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..catalog import Catalog, Video
from ..media import fmt_duration
from . import theme

VideoRole = Qt.UserRole + 1


class VideoModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.videos: list[Video] = []
        self.row_of: dict[int, int] = {}
        self.catalog: Catalog | None = None
        self.thumbs = None  # ThumbnailManager

    def set_videos(self, videos: list[Video]):
        self.beginResetModel()
        self.videos = videos
        self.row_of = {v.id: i for i, v in enumerate(videos)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.videos)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        v = self.videos[index.row()]
        if role == VideoRole:
            return v
        if role == Qt.DisplayRole:
            return v.filename
        if role == Qt.ToolTipRole:
            return v.path
        return None

    def pixmap(self, v: Video) -> QPixmap | None:
        if not self.catalog:
            return None
        key = f"clip-{v.id}"
        pm = QPixmapCache.find(key)
        if pm is not None and not pm.isNull():
            return pm
        tp = self.catalog.thumb_path(v.id)
        if tp.exists():
            pm = QPixmap(str(tp))
            if not pm.isNull():
                QPixmapCache.insert(key, pm)
                return pm
        if self.thumbs is not None:
            self.thumbs.request(v, tp)
        return None

    def refresh_ids(self, ids):
        if not self.catalog:
            return
        for vid in ids:
            r = self.row_of.get(vid)
            if r is None:
                continue
            nv = self.catalog.get(vid)
            if nv:
                self.videos[r] = nv
            idx = self.index(r)
            self.dataChanged.emit(idx, idx)

    def thumb_ready(self, vid):
        QPixmapCache.remove(f"clip-{vid}")
        r = self.row_of.get(vid)
        if r is not None:
            idx = self.index(r)
            self.dataChanged.emit(idx, idx)


class VideoDelegate(QStyledItemDelegate):
    def __init__(self, model: VideoModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.thumb_w = 240

    def sizeHint(self, option, index):
        return QSize(self.thumb_w + 12, int(self.thumb_w * 9 / 16) + 52)

    def paint(self, p: QPainter, opt, index):
        v: Video = index.data(VideoRole)
        if v is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRect(opt.rect).adjusted(3, 3, -3, -3)
        selected = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        bg = QColor(theme.CARD_HOVER if (hover or selected) else theme.CARD)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 6, 6)
        p.fillPath(path, bg)
        if selected:
            p.setPen(QColor(theme.SELECT))
            p.drawPath(path)

        # miniatura 16:9
        tr = QRect(r.x() + 3, r.y() + 3, r.width() - 6, int((r.width() - 6) * 9 / 16))
        p.fillRect(tr, QColor(theme.BG))
        pm = self.model.pixmap(v)
        if pm is not None:
            s = pm.size().scaled(tr.size(), Qt.KeepAspectRatio)
            target = QRect(0, 0, s.width(), s.height())
            target.moveCenter(tr.center())
            if v.flag == -1:
                p.setOpacity(0.35)
            p.drawPixmap(target, pm)
            p.setOpacity(1.0)
        elif v.missing:
            p.setPen(QColor(theme.REJECT))
            p.drawText(tr, Qt.AlignCenter, "No encontrado")
        else:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(tr, Qt.AlignCenter, "…")

        small = QFont(opt.font)
        small.setPointSizeF(max(7.0, opt.font.pointSizeF() - 1))
        bold = QFont(small)
        bold.setBold(True)

        # insignias
        x = tr.x() + 6
        if v.flag != 0:
            color = theme.PICK if v.flag == 1 else theme.REJECT
            self._badge(p, QRect(x, tr.y() + 6, 22, 18), "P" if v.flag == 1 else "X", color, "#111", bold)
            x += 26
        if v.is_hdr:
            self._badge(p, QRect(x, tr.y() + 6, 34, 18), "HDR", theme.HDR, "#111", bold)
        if v.missing and pm is not None:
            self._badge(p, QRect(tr.right() - 28, tr.bottom() - 24, 22, 18), "!", theme.REJECT, "#111", bold)
        if v.trimmed:
            dur = (v.trim_out if v.trim_out is not None else (v.duration or 0)) - (v.trim_in or 0)
            txt = f"✂ {fmt_duration(dur)}"
            w = p.fontMetrics().horizontalAdvance(txt) + 14
            self._badge(p, QRect(tr.right() - w - 6, tr.y() + 6, w, 18), txt, "#cc000000", theme.TRIM, small)

        # textos
        p.setFont(small)
        y = tr.bottom() + 6
        text_r = QRect(r.x() + 8, y, r.width() - 16, 18)
        dur_txt = fmt_duration(v.duration)
        dw = p.fontMetrics().horizontalAdvance(dur_txt)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(text_r, Qt.AlignRight | Qt.AlignVCenter, dur_txt)
        p.setPen(QColor(theme.TEXT if v.flag != -1 else theme.TEXT_DIM))
        name = p.fontMetrics().elidedText(v.filename, Qt.ElideMiddle, text_r.width() - dw - 8)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter, name)
        if v.capture_time:
            dt = datetime.fromisoformat(v.capture_time).astimezone()
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(text_r.translated(0, 18), Qt.AlignLeft | Qt.AlignVCenter, dt.strftime("%d/%m/%Y %H:%M"))
        p.restore()

    @staticmethod
    def _badge(p, rect, text, bg, fg, font):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        p.fillPath(path, QColor(bg))
        p.setPen(QColor(fg))
        p.setFont(font)
        p.drawText(rect, Qt.AlignCenter, text)


class GridView(QListView):
    activated_video = Signal(int)

    def __init__(self, model: VideoModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.delegate = VideoDelegate(model, self)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(200)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.doubleClicked.connect(lambda idx: self.activated_video.emit(idx.row()))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self.activated_video.emit(self.currentIndex().row())
            return
        super().keyPressEvent(e)

    def set_thumb_width(self, w: int):
        self.delegate.thumb_w = w
        self.model().layoutChanged.emit()
