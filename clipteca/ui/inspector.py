"""Panel derecho: información, marca P/X y etiquetas (palabras clave y personas)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCompleter, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..catalog import Video
from ..media import fmt_duration, fmt_local
from .flowlayout import FlowLayout


class TagEditor(QWidget):
    added = Signal(list)
    removed = Signal(str)

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.edit.setCompleter(self.completer)
        self.edit.returnPressed.connect(self._commit)
        self.chips = QWidget()
        self.flow = FlowLayout(self.chips)
        lay.addWidget(self.edit)
        lay.addWidget(self.chips)

    def _commit(self):
        names = [n.strip() for n in self.edit.text().split(",") if n.strip()]
        if names:
            self.added.emit(names)
        self.edit.clear()

    def set_suggestions(self, names: list[str]):
        self.completer.model().setStringList(names)

    def set_tags(self, names: list[str], partial: bool = False):
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for n in names:
            b = QPushButton(f"{n}  ✕")
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("Quitar" + (" de todos los seleccionados" if partial else ""))
            b.clicked.connect(lambda _=False, n=n: self.removed.emit(n))
            self.flow.addWidget(b)
        self.flow.invalidate()
        self.chips.updateGeometry()


class Inspector(QScrollArea):
    flag_requested = Signal(int)
    tags_added = Signal(str, list)       # kind, names
    tag_removed = Signal(str, str)       # kind, name
    clear_trim_requested = Signal()
    clear_location_requested = Signal()
    rotate_requested = Signal(int)       # -90 | +90

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(270)
        body = QWidget()
        self.setWidget(body)
        lay = QVBoxLayout(body)

        self.title = QLabel("Sin selección")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight:600; font-size:13px;")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)

        flags = QHBoxLayout()
        self.btn_pick = QPushButton("P  Seleccionar")
        self.btn_pick.setObjectName("flagPick")
        self.btn_reject = QPushButton("X  Rechazar")
        self.btn_reject.setObjectName("flagReject")
        for b, val in ((self.btn_pick, 1), (self.btn_reject, -1)):
            b.setCheckable(True)
            b.clicked.connect(lambda checked, val=val: self.flag_requested.emit(val if checked else 0))
            flags.addWidget(b)
        lay.addLayout(flags)

        rot = QHBoxLayout()
        self.btn_rot_left = QPushButton("↺ Rotar izq.")
        self.btn_rot_right = QPushButton("↻ Rotar der.")
        self.btn_rot_left.clicked.connect(lambda: self.rotate_requested.emit(-90))
        self.btn_rot_right.clicked.connect(lambda: self.rotate_requested.emit(90))
        rot.addWidget(self.btn_rot_left)
        rot.addWidget(self.btn_rot_right)
        lay.addLayout(rot)

        self.info = QFormLayout()
        self.info.setLabelAlignment(Qt.AlignRight)
        self.lbl = {}
        for key, label in (("date", "Captura"), ("date_src", "Origen fecha"), ("duration", "Duración"),
                           ("trim", "Recorte"), ("video", "Vídeo"), ("color", "Color"),
                           ("camera", "Cámara"), ("folder", "Carpeta"), ("location", "Ubicación")):
            w = QLabel("–")
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.lbl[key] = w
            self.info.addRow(label, w)
        lay.addLayout(self.info)
        self.btn_clear_trim = QPushButton("Quitar recorte")
        self.btn_clear_trim.setObjectName("trimBtn")
        self.btn_clear_trim.clicked.connect(self.clear_trim_requested)
        lay.addWidget(self.btn_clear_trim)
        self.btn_clear_location = QPushButton("Quitar ubicación")
        self.btn_clear_location.setObjectName("trimBtn")
        self.btn_clear_location.clicked.connect(self.clear_location_requested)
        lay.addWidget(self.btn_clear_location)

        t1 = QLabel("Palabras clave")
        t1.setObjectName("sectionTitle")
        lay.addWidget(t1)
        self.keywords = TagEditor("Añadir (separa con comas)…")
        self.keywords.added.connect(lambda n: self.tags_added.emit("keyword", n))
        self.keywords.removed.connect(lambda n: self.tag_removed.emit("keyword", n))
        lay.addWidget(self.keywords)

        t2 = QLabel("Personas")
        t2.setObjectName("sectionTitle")
        lay.addWidget(t2)
        self.people = TagEditor("Añadir persona…")
        self.people.added.connect(lambda n: self.tags_added.emit("person", n))
        self.people.removed.connect(lambda n: self.tag_removed.emit("person", n))
        lay.addWidget(self.people)
        lay.addStretch(1)
        self.show_videos([], {"keyword": [], "person": []})

    def show_videos(self, videos: list[Video], tags: dict[str, list[str]]):
        n = len(videos)
        enabled = n > 0
        for w in (self.btn_pick, self.btn_reject, self.keywords, self.people,
                  self.btn_rot_left, self.btn_rot_right):
            w.setEnabled(enabled)
        partial = n > 1
        self.keywords.set_tags(tags["keyword"], partial)
        self.people.set_tags(tags["person"], partial)
        if n == 0:
            self.title.setText("Sin selección")
        elif n > 1:
            self.title.setText(f"{n} vídeos seleccionados")
        flags = {v.flag for v in videos}
        self.btn_pick.setChecked(flags == {1})
        self.btn_reject.setChecked(flags == {-1})
        single = videos[0] if n == 1 else None
        self.btn_clear_trim.setVisible(bool(single and single.trimmed))
        self.btn_clear_location.setVisible(bool(single and single.has_gps))
        if not single:
            for w in self.lbl.values():
                w.setText("–")
            if n > 1:
                total = sum(v.duration or 0 for v in videos)
                self.lbl["duration"].setText(f"{fmt_duration(total)} en total")
            return
        v = single
        r = v.row
        self.title.setText(v.filename + ("  (no encontrado)" if v.missing else ""))
        self.lbl["date"].setText(fmt_local(v.capture_time, r.get("tz_offset")) +
                                 (f"  ({r['tz_offset']})" if r.get("tz_offset") else ""))
        src = {"quicktime.creationdate": "metadatos (con zona)", "creation_time": "metadatos (UTC)",
               "filename": "nombre del fichero", "mtime": "fecha del fichero"}
        self.lbl["date_src"].setText(src.get(r.get("capture_src"), "–"))
        self.lbl["duration"].setText(fmt_duration(v.duration))
        if v.trimmed:
            a = v.trim_in or 0.0
            z = v.trim_out if v.trim_out is not None else (v.duration or 0)
            self.lbl["trim"].setText(f"{fmt_duration(a)} → {fmt_duration(z)}  ({fmt_duration(z - a)})")
        else:
            self.lbl["trim"].setText("Sin recorte")
        fps = f" · {v.fps:g} fps" if v.fps else ""
        rot = f" · rot {r['rotation']}°" if r.get("rotation") else ""
        self.lbl["video"].setText(f"{v.width}×{v.height}{fps} · {v.vcodec or '?'}"
                                  f"{' / ' + r['acodec'] if r.get('acodec') else ''}{rot}")
        trc = r.get("color_trc") or "?"
        hdr = {"arib-std-b67": "HDR HLG", "smpte2084": "HDR PQ"}.get(trc, "SDR")
        self.lbl["color"].setText(f"{hdr} · {r.get('pix_fmt') or '?'} · {r.get('color_primaries') or '?'}")
        self.lbl["camera"].setText(r.get("camera_model") or "–")
        self.lbl["folder"].setText(v.folder)
        if v.has_gps:
            src = {"exif": "GPS", "manual": "manual"}.get(r.get("geo_src"), "?")
            self.lbl["location"].setText(f"{r['lat']:.5f}, {r['lon']:.5f}  ({src})")
        else:
            self.lbl["location"].setText("–")
