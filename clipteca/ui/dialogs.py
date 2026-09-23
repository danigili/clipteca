"""Diálogos: bienvenida, exportación y atajos."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSpinBox, QVBoxLayout)

from .. import APP_NAME, CATALOG_EXT
from ..exporter import ExportOptions


class WelcomeDialog(QDialog):
    NEW, OPEN = 1, 2

    def __init__(self, parent=None, recent: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.choice = 0
        self.recent_path: str | None = None
        lay = QVBoxLayout(self)
        t = QLabel(f"<h2>{APP_NAME}</h2><p>Un catálogo guarda marcas, recortes y etiquetas de tus vídeos. "
                   "Los originales nunca se modifican.</p>")
        t.setWordWrap(True)
        lay.addWidget(t)
        b1 = QPushButton("Crear catálogo nuevo…")
        b2 = QPushButton("Abrir catálogo…")
        b1.clicked.connect(lambda: self._done(self.NEW))
        b2.clicked.connect(lambda: self._done(self.OPEN))
        lay.addWidget(b1)
        lay.addWidget(b2)
        for p in (recent or [])[:5]:
            if Path(p).exists():
                b = QPushButton(Path(p).name)
                b.setToolTip(p)
                b.setFlat(True)
                b.clicked.connect(lambda _=False, p=p: self._recent(p))
                lay.addWidget(b)
        self.resize(380, 0)

    def _done(self, c):
        self.choice = c
        self.accept()

    def _recent(self, p):
        self.recent_path = p
        self.accept()


def ask_new_catalog(parent, start_dir: str = "") -> Path | None:
    fn, _ = QFileDialog.getSaveFileName(parent, "Crear catálogo", str(Path(start_dir) / f"Vídeos{CATALOG_EXT}"),
                                        f"Catálogo {APP_NAME} (*{CATALOG_EXT})")
    if not fn:
        return None
    p = Path(fn)
    if p.suffix.lower() != CATALOG_EXT:
        p = p.with_suffix(CATALOG_EXT)
    return p


def ask_open_catalog(parent, start_dir: str = "") -> Path | None:
    fn, _ = QFileDialog.getOpenFileName(parent, "Abrir catálogo", start_dir,
                                        f"Catálogo {APP_NAME} (*{CATALOG_EXT})")
    return Path(fn) if fn else None


class ExportDialog(QDialog):
    SCOPE_VIEW, SCOPE_ALL, SCOPE_SELECTION = 0, 1, 2

    def __init__(self, parent, n_view: int, n_all: int, n_sel: int, last_dest: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Exportar vídeos")
        lay = QVBoxLayout(self)

        g = QGroupBox("Qué exportar")
        gl = QVBoxLayout(g)
        self.scope = QButtonGroup(self)
        opts = [(self.SCOPE_VIEW, f"Seleccionados (P) de la vista actual: {n_view}", n_view),
                (self.SCOPE_ALL, f"Seleccionados (P) de todo el catálogo: {n_all}", n_all),
                (self.SCOPE_SELECTION, f"Vídeos elegidos en la cuadrícula: {n_sel}", n_sel)]
        first = True
        for sid, text, n in opts:
            rb = QRadioButton(text)
            rb.setEnabled(n > 0)
            if n > 0 and first:
                rb.setChecked(True)
                first = False
            self.scope.addButton(rb, sid)
            gl.addWidget(rb)
        lay.addWidget(g)

        form = QFormLayout()
        row = QHBoxLayout()
        self.dest = QLineEdit(last_dest)
        pick = QPushButton("Elegir…")
        pick.clicked.connect(self._pick)
        row.addWidget(self.dest, 1)
        row.addWidget(pick)
        form.addRow("Destino", row)

        self.mode = QComboBox()
        self.mode.addItem("Sin pérdida (rápido, corta en fotograma clave)", False)
        self.mode.addItem("Preciso (recodifica con la misma calidad aproximada)", True)
        form.addRow("Recorte", self.mode)
        self.crf = QSpinBox()
        self.crf.setRange(10, 30)
        self.crf.setValue(18)
        self.crf.setToolTip("Calidad al recodificar (CRF). Menor = más calidad y más tamaño.")
        form.addRow("Calidad (CRF)", self.crf)
        self.mode.currentIndexChanged.connect(lambda _: self._update_mode_enabled())

        self.conflict = QComboBox()
        self.conflict.addItem("Renombrar (añadir _1, _2…)", "rename")
        self.conflict.addItem("Omitir", "skip")
        self.conflict.addItem("Sobrescribir", "overwrite")
        form.addRow("Si ya existe", self.conflict)
        lay.addLayout(form)

        self.compress = QCheckBox("Comprimir mucho: HEVC, máx. 1080p, ~1.8 Mbps")
        self.compress.setToolTip(
            "Ignora el modo de recorte y la calidad de arriba: siempre recodifica a HEVC, "
            "reescala hacia abajo a 1080p y limita el bitrate (CRF con tope de tamaño)."
        )
        self.compress.toggled.connect(lambda _: self._update_mode_enabled())
        lay.addWidget(self.compress)

        self.keep = QCheckBox("Mantener la estructura de subcarpetas (fechas)")
        self.keep.setChecked(True)
        self.tags = QCheckBox("Escribir palabras clave y personas (XMP)")
        self.tags.setChecked(True)
        self.shift = QCheckBox("Ajustar la fecha de captura al inicio del recorte")
        self.shift.setToolTip("Desactivado: el vídeo exportado conserva exactamente la fecha del original.")
        for w in (self.keep, self.tags, self.shift):
            lay.addWidget(w)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8b8e95;")
        lay.addWidget(self.note)
        self._update_mode_enabled()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Exportar")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 0)

    def _update_mode_enabled(self):
        compressing = self.compress.isChecked()
        self.mode.setEnabled(not compressing)
        self.crf.setEnabled(not compressing and bool(self.mode.currentData()))
        if compressing:
            self.note.setText("Se recodifica siempre a HEVC 1080p con bitrate limitado (~1.8 Mbps vídeo + "
                              "128 kbps audio AAC). El HDR se convierte a SDR. Pensado para compartir, no "
                              "para conservar calidad original.")
        else:
            self.note.setText("En modo sin pérdida el inicio real puede adelantarse hasta el fotograma clave "
                              "anterior (≈1 s en móviles). Formato, códec y HDR se mantienen.")

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.dest.text())
        if d:
            self.dest.setText(d)

    def _accept(self):
        if not self.dest.text().strip():
            self._pick()
            if not self.dest.text().strip():
                return
        if self.scope.checkedId() < 0:
            return
        self.accept()

    def scope_id(self) -> int:
        return self.scope.checkedId()

    def options(self) -> ExportOptions:
        return ExportOptions(
            dest=Path(self.dest.text().strip()),
            precise=bool(self.mode.currentData()),
            crf=self.crf.value(),
            compress=self.compress.isChecked(),
            date_shift=self.shift.isChecked(),
            keep_structure=self.keep.isChecked(),
            conflict=self.conflict.currentData(),
            write_tags=self.tags.isChecked(),
        )


SHORTCUTS = [
    ("P", "Seleccionar"), ("X", "Rechazar"), ("U", "Quitar marca"),
    ("G", "Cuadrícula"), ("E / Intro / doble clic", "Visor"), ("← / →", "Vídeo anterior / siguiente"),
    ("Espacio", "Reproducir / pausa"), ("Mayús+Espacio", "Reproducir solo el recorte"),
    ("J / L", "−5 s / +5 s"), (", / .", "Fotograma anterior / siguiente"),
    ("I / O", "Marcar entrada / salida"), ("Mayús+I / Mayús+O", "Quitar entrada / salida"),
    ("Ctrl+K", "Añadir palabra clave"), ("Ctrl+Mayús+K", "Añadir persona"),
    ("Ctrl+F", "Buscar"), ("Ctrl+Mayús+I", "Importar carpeta"), ("Ctrl+Mayús+E", "Exportar"),
    ("Supr", "Quitar del catálogo (no borra el fichero)"),
]


def shortcuts_html() -> str:
    rows = "".join(f"<tr><td style='padding:2px 14px 2px 0'><b>{k}</b></td><td>{v}</td></tr>" for k, v in SHORTCUTS)
    return f"<table>{rows}</table>"
