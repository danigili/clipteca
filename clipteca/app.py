"""Ventana principal de Clipteca."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmapCache
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton,
                               QSlider, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import APP_NAME, __version__, tools
from .catalog import Catalog, Filter, Video
from .exporter import ExportItem
from .media import fmt_duration
from .ui import theme
from .ui.dialogs import ExportDialog, WelcomeDialog, ask_new_catalog, ask_open_catalog, shortcuts_html
from .ui.grid import GridView, VideoModel, VideoRole
from .ui.inspector import Inspector
from .ui.player import create_player
from .ui.timeline import Timeline
from .ui.workers import ExportWorker, ImportWorker, ThumbnailManager

PathRole = Qt.UserRole + 10
TagRole = Qt.UserRole + 11


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.catalog: Catalog | None = None
        self.filter = Filter(flag="all")
        self.loaded_id: int | None = None
        self.range_end: float | None = None
        self.worker = None
        self.setAcceptDrops(True)

        self.model = VideoModel(self)
        self.thumbs = ThumbnailManager(self)
        self.model.thumbs = self.thumbs
        self.thumbs.ready.connect(self.model.thumb_ready)

        self._build_ui()
        self._build_actions()
        self._restore_state()
        self._update_title()

    # ================================================================ UI
    def _build_ui(self):
        # --- izquierda: carpetas y etiquetas
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Carpetas")
        self.folder_tree.itemClicked.connect(self._folder_clicked)
        self.tag_tree = QTreeWidget()
        self.tag_tree.setHeaderLabel("Etiquetas")
        self.tag_tree.itemClicked.connect(self._tag_clicked)
        self.tag_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_tree.customContextMenuRequested.connect(self._tag_menu)
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.folder_tree)
        left.addWidget(self.tag_tree)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)

        # --- centro: barra de filtro + cuadrícula / visor
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self.flag_combo = QComboBox()
        for text, key in (("Todos", "all"), ("Seleccionados (P)", "picked"), ("Sin marcar", "unflagged"),
                          ("Rechazados (X)", "rejected"), ("Ocultar rechazados", "not_rejected")):
            self.flag_combo.addItem(text, key)
        self.flag_combo.currentIndexChanged.connect(self._filter_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre, palabra clave o persona")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(self._filter_changed)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Fecha de captura", "capture_time")
        self.sort_combo.addItem("Nombre", "filename")
        self.sort_combo.currentIndexChanged.connect(self._filter_changed)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(140, 420)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip("Tamaño de miniatura")
        self.count_label = QLabel()
        bar.addWidget(self.flag_combo)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.sort_combo)
        bar.addWidget(self.size_slider)
        bar.addWidget(self.count_label)

        self.grid = GridView(self.model)
        self.grid.activated_video.connect(lambda _: self.show_loupe())
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())
        self.grid.selectionModel().currentChanged.connect(lambda *_: self._current_changed())
        self.size_slider.valueChanged.connect(self.grid.set_thumb_width)

        loupe = QWidget()
        ll = QVBoxLayout(loupe)
        ll.setContentsMargins(0, 0, 0, 0)
        self.player = create_player()
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_player_duration)
        self.player.playing_changed.connect(lambda p: self.btn_play.setText("❚❚" if p else "▶"))
        self.timeline = Timeline()
        self.timeline.seek_requested.connect(self.player.seek)
        self.timeline.trim_changed.connect(lambda a, z: self._trim_label(a, z))
        self.timeline.trim_committed.connect(self._commit_trim)
        ctr = QHBoxLayout()
        ctr.setContentsMargins(8, 0, 8, 6)
        self.btn_prev = QPushButton("⏮")
        self.btn_play = QPushButton("▶")
        self.btn_next = QPushButton("⏭")
        self.btn_in = QPushButton("[ Entrada (I)")
        self.btn_out = QPushButton("Salida (O) ]")
        self.btn_range = QPushButton("▶ Recorte")
        for b in (self.btn_in, self.btn_out, self.btn_range):
            b.setObjectName("trimBtn")
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_in, self.btn_out, self.btn_range):
            b.setFocusPolicy(Qt.NoFocus)
        self.btn_prev.clicked.connect(lambda: self.navigate(-1))
        self.btn_next.clicked.connect(lambda: self.navigate(1))
        self.btn_play.clicked.connect(self.player.play_pause)
        self.btn_in.clicked.connect(self.set_in)
        self.btn_out.clicked.connect(self.set_out)
        self.btn_range.clicked.connect(self.play_range)
        self.time_label = QLabel("0:00.0 / 0:00.0")
        self.trim_label = QLabel()
        self.trim_label.setStyleSheet(f"color:{theme.TRIM};")
        ctr.addWidget(self.btn_prev)
        ctr.addWidget(self.btn_play)
        ctr.addWidget(self.btn_next)
        ctr.addSpacing(10)
        ctr.addWidget(self.time_label)
        ctr.addStretch(1)
        ctr.addWidget(self.trim_label)
        ctr.addWidget(self.btn_in)
        ctr.addWidget(self.btn_out)
        ctr.addWidget(self.btn_range)
        ll.addWidget(self.player, 1)
        ll.addWidget(self.timeline)
        ll.addLayout(ctr)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(loupe)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addLayout(bar)
        cl.addWidget(self.stack, 1)

        # --- derecha
        self.inspector = Inspector()
        self.inspector.flag_requested.connect(self.set_flag)
        self.inspector.tags_added.connect(self.add_tags)
        self.inspector.tag_removed.connect(self.remove_tag)
        self.inspector.clear_trim_requested.connect(lambda: self._commit_trim(None, None))

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(center)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 900, 300])
        self.setCentralWidget(self.splitter)
        self.statusBar().showMessage(f"Reproductor: {self.player.backend}")

    def _act(self, menu: QMenu, text: str, slot, shortcut=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, list) else [shortcut])])
            a.setShortcutContext(Qt.WindowShortcut)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_actions(self):
        mb = self.menuBar()
        m = mb.addMenu("&Archivo")
        self._act(m, "Nuevo catálogo…", self.new_catalog, "Ctrl+Shift+N")
        self._act(m, "Abrir catálogo…", self.open_catalog, "Ctrl+O")
        self.recent_menu = m.addMenu("Catálogos recientes")
        m.addSeparator()
        self.a_import = self._act(m, "Importar carpeta…", self.import_folder, "Ctrl+Shift+I")
        self.a_export = self._act(m, "Exportar…", self.export, "Ctrl+Shift+E")
        m.addSeparator()
        self._act(m, "Salir", self.close, "Ctrl+Q")

        m = mb.addMenu("&Edición")
        self._act(m, "Seleccionar (P)", lambda: self.set_flag(1), "P")
        self._act(m, "Rechazar (X)", lambda: self.set_flag(-1), "X")
        self._act(m, "Quitar marca (U)", lambda: self.set_flag(0), "U")
        m.addSeparator()
        self._act(m, "Añadir palabra clave", lambda: self._focus_tag("keyword"), "Ctrl+K")
        self._act(m, "Añadir persona", lambda: self._focus_tag("person"), "Ctrl+Shift+K")
        m.addSeparator()
        self._act(m, "Marcar entrada", self.set_in, "I")
        self._act(m, "Marcar salida", self.set_out, "O")
        self._act(m, "Quitar entrada", lambda: self._clear_trim_side("in"), "Shift+I")
        self._act(m, "Quitar salida", lambda: self._clear_trim_side("out"), "Shift+O")
        m.addSeparator()
        self._act(m, "Seleccionar todos", self.grid.selectAll, "Ctrl+A")
        self._act(m, "Buscar", lambda: (self.search.setFocus(), self.search.selectAll()), "Ctrl+F")
        self._act(m, "Quitar del catálogo…", self.remove_selected, "Del")

        m = mb.addMenu("&Vista")
        self._act(m, "Cuadrícula", self.show_grid, "G")
        self._act(m, "Visor", self.show_loupe, "E")
        self._act(m, "Anterior", lambda: self.navigate(-1), "Left")
        self._act(m, "Siguiente", lambda: self.navigate(1), "Right")
        m.addSeparator()
        self._act(m, "Reproducir / pausa", self.play_pause, "Space")
        self._act(m, "Reproducir recorte", self.play_range, "Shift+Space")
        self._act(m, "Retroceder 5 s", lambda: self._jump(-5), "J")
        self._act(m, "Avanzar 5 s", lambda: self._jump(5), "L")
        self._act(m, "Fotograma anterior", lambda: self._step(-1), ",")
        self._act(m, "Fotograma siguiente", lambda: self._step(1), ".")
        m.addSeparator()
        self.a_advance = self._act(m, "Avanzar al marcar", lambda: None, checkable=True)

        m = mb.addMenu("&Catálogo")
        self._act(m, "Buscar vídeos no encontrados", self.check_missing)
        self._act(m, "Relocalizar carpeta…", self.relocate)
        self._act(m, "Regenerar miniaturas", self.regen_thumbs)
        self._act(m, "Mostrar catálogo en el explorador", self.reveal_catalog)

        m = mb.addMenu("A&yuda")
        self._act(m, "Atajos de teclado", lambda: QMessageBox.information(self, "Atajos", shortcuts_html()), "F1")
        self._act(m, "Herramientas externas", self.show_tools)
        self._act(m, f"Acerca de {APP_NAME}", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME}</b> {__version__}<br>Catálogo de vídeos con recorte sin pérdida."))

    # ============================================================ estado
    def _restore_state(self):
        g = self.settings.value("geometry")
        if g:
            self.restoreGeometry(g)
        s = self.settings.value("splitter")
        if s:
            self.splitter.restoreState(s)
        self.size_slider.setValue(int(self.settings.value("thumb", 240)))
        self.a_advance.setChecked(self.settings.value("advance", "false") == "true")
        self._rebuild_recent()

    def _recent(self) -> list[str]:
        r = self.settings.value("recent", [])
        return [r] if isinstance(r, str) else list(r or [])

    def _rebuild_recent(self):
        self.recent_menu.clear()
        for p in self._recent():
            a = self.recent_menu.addAction(p)
            a.triggered.connect(lambda _=False, p=p: self.load_catalog(Path(p)))
        self.recent_menu.setEnabled(bool(self._recent()))

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("thumb", self.size_slider.value())
        self.settings.setValue("advance", "true" if self.a_advance.isChecked() else "false")
        self.thumbs.clear()
        self.player.shutdown()
        if self.catalog:
            self.catalog.close()
        super().closeEvent(e)

    def _update_title(self):
        name = self.catalog.path.name if self.catalog else "sin catálogo"
        self.setWindowTitle(f"{APP_NAME} — {name}")
        has = self.catalog is not None
        self.a_import.setEnabled(has)
        self.a_export.setEnabled(has)

    # ========================================================== catálogo
    def startup(self):
        missing = tools.missing_tools()
        if missing:
            self.show_tools()
        last = self.settings.value("last_catalog")
        if last and Path(last).exists():
            self.load_catalog(Path(last))
            return
        self.welcome()

    def welcome(self):
        dlg = WelcomeDialog(self, self._recent())
        if dlg.exec() and dlg.recent_path:
            self.load_catalog(Path(dlg.recent_path))
        elif dlg.choice == WelcomeDialog.NEW:
            self.new_catalog()
        elif dlg.choice == WelcomeDialog.OPEN:
            self.open_catalog()
        if not self.catalog:
            QTimer.singleShot(0, self.close)

    def new_catalog(self):
        p = ask_new_catalog(self, self.settings.value("last_dir", str(Path.home())))
        if p:
            if p.exists():
                p.unlink()
            self.load_catalog(p)
            QTimer.singleShot(100, self.import_folder)

    def open_catalog(self):
        p = ask_open_catalog(self, self.settings.value("last_dir", str(Path.home())))
        if p:
            self.load_catalog(p)

    def load_catalog(self, path: Path):
        try:
            cat = Catalog(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"No se pudo abrir el catálogo:\n{e}")
            return
        self.player.unload()
        self.loaded_id = None
        self.thumbs.clear()
        QPixmapCache.clear()
        if self.catalog:
            self.catalog.close()
        self.catalog = cat
        self.model.catalog = cat
        self.filter = Filter()
        self.settings.setValue("last_catalog", str(path))
        self.settings.setValue("last_dir", str(path.parent))
        rec = [str(path)] + [r for r in self._recent() if r != str(path)]
        self.settings.setValue("recent", rec[:8])
        self._rebuild_recent()
        self._update_title()
        self.rebuild_trees()
        self.requery()
        self.show_grid()

    # ============================================================ árboles
    def rebuild_trees(self):
        self.folder_tree.clear()
        self.tag_tree.clear()
        if not self.catalog:
            return
        c = self.catalog.counts()
        root = QTreeWidgetItem([f"Todo el catálogo ({c['all']})"])
        root.setData(0, PathRole, None)
        self.folder_tree.addTopLevelItem(root)

        # árbol de carpetas con conteo acumulado
        nodes: dict[tuple, dict] = {}
        top: dict = {"children": {}, "count": 0}
        for folder, n in self.catalog.folders():
            parts = Path(folder).parts
            node = top
            for i, part in enumerate(parts):
                node = node["children"].setdefault(part, {"children": {}, "count": 0, "own": 0,
                                                          "path": str(Path(*parts[: i + 1]))})
                node["count"] += n
            node["own"] = n
        del nodes

        def collapse(name, node):
            # une cadenas de carpetas sin vídeos propios y con un solo hijo (C:\ › Users › dani › ...)
            while len(node["children"]) == 1 and not node.get("own"):
                (cname, child), = node["children"].items()
                name = str(Path(name) / cname)
                node = child
            return name, node

        def add(parent, name, node):
            name, node = collapse(name, node)
            it = QTreeWidgetItem([f"{name}  ({node['count']})"])
            it.setData(0, PathRole, node["path"])
            it.setToolTip(0, node["path"])
            parent.addChild(it)
            for cname in sorted(node["children"]):
                add(it, cname, node["children"][cname])
            return it

        for name in sorted(top["children"]):
            add(root, name, top["children"][name])
        root.setExpanded(True)
        for i in range(root.childCount()):
            root.child(i).setExpanded(True)
        self._select_tree_item(self.folder_tree, PathRole, self.filter.folder)

        tags = self.catalog.all_tags()
        roots = {}
        for kind, label in (("keyword", "Palabras clave"), ("person", "Personas")):
            r = QTreeWidgetItem([label])
            r.setData(0, TagRole, None)
            self.tag_tree.addTopLevelItem(r)
            r.setExpanded(True)
            roots[kind] = r
        names = {"keyword": [], "person": []}
        for tid, name, kind, n in tags:
            it = QTreeWidgetItem([f"{name}  ({n})"])
            it.setData(0, TagRole, tid)
            it.setData(0, TagRole + 1, name)
            roots[kind].addChild(it)
            names[kind].append(name)
        self.inspector.keywords.set_suggestions(names["keyword"])
        self.inspector.people.set_suggestions(names["person"])
        self._select_tree_item(self.tag_tree, TagRole, self.filter.tag_id)

    @staticmethod
    def _select_tree_item(tree, role, value):
        def walk(item):
            if item.data(0, role) == value:
                tree.setCurrentItem(item)
                return True
            return any(walk(item.child(i)) for i in range(item.childCount()))
        for i in range(tree.topLevelItemCount()):
            if walk(tree.topLevelItem(i)):
                return

    def _folder_clicked(self, item):
        self.filter.folder = item.data(0, PathRole)
        self.requery()

    def _tag_clicked(self, item):
        self.filter.tag_id = item.data(0, TagRole)
        self.requery()

    def _tag_menu(self, pos):
        item = self.tag_tree.itemAt(pos)
        if not item or item.data(0, TagRole) is None:
            return
        menu = QMenu(self)
        a = menu.addAction("Renombrar…")
        if menu.exec(self.tag_tree.viewport().mapToGlobal(pos)) == a:
            old = item.data(0, TagRole + 1)
            new, ok = QInputDialog.getText(self, "Renombrar etiqueta", "Nuevo nombre:", text=old)
            if ok and new.strip() and new.strip() != old:
                try:
                    self.catalog.rename_tag(item.data(0, TagRole), new)
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(self, APP_NAME, f"No se pudo renombrar: {e}")
                self.rebuild_trees()
                self._selection_changed()

    # =========================================================== consulta
    def _filter_changed(self):
        self.filter.flag = self.flag_combo.currentData()
        self.filter.text = self.search.text()
        self.filter.order = self.sort_combo.currentData()
        self.requery()

    def requery(self):
        if not self.catalog:
            return
        cur = self.current_video()
        cur_id = cur.id if cur else None
        videos = self.catalog.query(self.filter)
        self.model.set_videos(videos)
        row = self.model.row_of.get(cur_id, 0 if videos else None)
        if row is not None:
            idx = self.model.index(row)
            self.grid.selectionModel().setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
            self.grid.scrollTo(idx)
        self._update_counts()
        self._selection_changed()
        if self.stack.currentIndex() == 1:
            self._load_current()

    def _update_counts(self):
        if not self.catalog:
            self.count_label.setText("")
            return
        c = self.catalog.counts()
        self.count_label.setText(f"{self.model.rowCount()} de {c['all']}  ·  P {c['picked']}  ·  X {c['rejected']}")

    # ========================================================= selección
    def current_video(self) -> Video | None:
        idx = self.grid.currentIndex()
        return idx.data(VideoRole) if idx.isValid() else None

    def selected_videos(self) -> list[Video]:
        rows = sorted(i.row() for i in self.grid.selectionModel().selectedIndexes())
        vids = [self.model.videos[r] for r in rows]
        if not vids and (c := self.current_video()):
            vids = [c]
        return vids

    def _selection_changed(self):
        vids = self.selected_videos()
        if not self.catalog:
            return
        ids = [v.id for v in vids]
        tags = self.catalog.video_tags(ids[0]) if len(ids) == 1 else self.catalog.common_tags(ids)
        self.inspector.show_videos(vids, tags)

    def _current_changed(self):
        if self.stack.currentIndex() == 1:
            self._load_current()

    def navigate(self, delta: int):
        n = self.model.rowCount()
        if not n:
            return
        cur = self.grid.currentIndex().row()
        row = min(n - 1, max(0, (cur if cur >= 0 else 0) + delta))
        idx = self.model.index(row)
        self.grid.selectionModel().setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect)
        self.grid.scrollTo(idx)

    # ============================================================ visor
    def show_grid(self):
        self.player.pause()
        self.stack.setCurrentIndex(0)
        self.grid.setFocus()

    def show_loupe(self):
        if not self.current_video():
            return
        self.stack.setCurrentIndex(1)
        self._load_current()

    def _load_current(self):
        v = self.current_video()
        if not v:
            self.player.unload()
            self.loaded_id = None
            return
        self.timeline.set_duration(v.duration or 0)
        self.timeline.set_trim(v.trim_in, v.trim_out)
        self._trim_label(v.trim_in, v.trim_out)
        if v.id == self.loaded_id:
            return
        self.loaded_id = v.id
        self.range_end = None
        if hasattr(self.player, "set_fps"):
            self.player.set_fps(v.fps)
        if v.missing or not Path(v.path).exists():
            self.player.unload()
            self.statusBar().showMessage(f"No se encuentra {v.path}")
            return
        self.player.load(v.path, v.trim_in or 0.0)

    def _loupe_video(self) -> Video | None:
        v = self.current_video()
        return v if (v and self.stack.currentIndex() == 1 and v.id == self.loaded_id) else None

    def _on_position(self, t):
        self.timeline.set_position(t)
        v = self._loupe_video()
        dur = (v.duration if v else None) or self.timeline.duration
        self.time_label.setText(f"{fmt_duration(t)} / {fmt_duration(dur)}")
        if self.range_end is not None and t >= self.range_end - 0.02:
            self.player.pause()
            self.range_end = None

    def _on_player_duration(self, d):
        if not self.timeline.duration and d:
            self.timeline.set_duration(d)

    def play_pause(self):
        if self.stack.currentIndex() == 0:
            self.show_loupe()
        self.range_end = None
        self.player.play_pause()

    def play_range(self):
        v = self._loupe_video()
        if not v:
            self.show_loupe()
            v = self._loupe_video()
            if not v:
                return
        self.player.seek(v.trim_in or 0.0)
        self.range_end = v.trim_out if v.trim_out is not None else v.duration
        self.player.play()

    def _jump(self, s):
        if self._loupe_video():
            self.player.seek(self.player.position() + s)

    def _step(self, n):
        if self._loupe_video():
            self.player.step(n)

    # =========================================================== recorte
    def _trim_label(self, a, z):
        v = self.current_video()
        if a is None and z is None:
            self.trim_label.setText("")
            return
        zz = z if z is not None else (v.duration if v else 0) or 0
        self.trim_label.setText(f"✂ {fmt_duration(a or 0)} → {fmt_duration(zz)} ({fmt_duration(zz - (a or 0))})")

    def set_in(self):
        v = self._loupe_video()
        if not v:
            return
        t = self.player.position()
        tout = v.trim_out
        if tout is not None and t >= tout - 0.05:
            tout = None
        self._commit_trim(t if t > 0.01 else None, tout)

    def set_out(self):
        v = self._loupe_video()
        if not v:
            return
        t = self.player.position()
        tin = v.trim_in
        if tin is not None and t <= tin + 0.05:
            tin = None
        dur = v.duration or 0
        self._commit_trim(tin, t if (not dur or t < dur - 0.01) else None)

    def _clear_trim_side(self, side):
        v = self.current_video()
        if v:
            self._commit_trim(None if side == "in" else v.trim_in, None if side == "out" else v.trim_out)

    def _commit_trim(self, a, z):
        v = self.current_video()
        if not v or not self.catalog:
            return
        self.catalog.set_trim(v.id, a, z)
        self.model.refresh_ids([v.id])
        self.timeline.set_trim(a, z)
        self._trim_label(a, z)
        self._selection_changed()

    # ============================================================ marcas
    def set_flag(self, flag: int):
        vids = self.selected_videos()
        if not vids or not self.catalog:
            return
        ids = [v.id for v in vids]
        self.catalog.set_flag(ids, flag)
        self.model.refresh_ids(ids)
        self._update_counts()
        self._selection_changed()
        if self.a_advance.isChecked() and len(ids) == 1:
            self.navigate(1)

    def _focus_tag(self, kind):
        ed = self.inspector.keywords if kind == "keyword" else self.inspector.people
        ed.edit.setFocus()

    def add_tags(self, kind, names):
        ids = [v.id for v in self.selected_videos()]
        if not ids:
            return
        self.catalog.add_tags(ids, names, kind)
        self.rebuild_trees()
        self._selection_changed()

    def remove_tag(self, kind, name):
        ids = [v.id for v in self.selected_videos()]
        self.catalog.remove_tag(ids, name, kind)
        self.rebuild_trees()
        self._selection_changed()

    def remove_selected(self):
        vids = self.selected_videos()
        if not vids:
            return
        if QMessageBox.question(self, "Quitar del catálogo",
                                f"¿Quitar {len(vids)} vídeo(s) del catálogo?\nLos ficheros no se borran.") \
                != QMessageBox.Yes:
            return
        if self.loaded_id in {v.id for v in vids}:
            self.player.unload()
            self.loaded_id = None
        self.catalog.remove([v.id for v in vids])
        self.rebuild_trees()
        self.requery()

    # ========================================================== importar
    def import_folder(self, folder: str | None = None):
        if not self.catalog or self.worker:
            return
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Importar carpeta (incluye subcarpetas)",
                                                      self.settings.value("last_import", str(Path.home())))
        if not folder:
            return
        if tools.missing_tools():
            self.show_tools()
            return
        self.settings.setValue("last_import", folder)
        dlg = QProgressDialog("Buscando vídeos…", "Cancelar", 0, 0, self)
        dlg.setWindowTitle("Importar")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        w = ImportWorker(self.catalog.path, Path(folder))
        self.worker = w

        def prog(d, t, name):
            dlg.setMaximum(max(t, 1))
            dlg.setValue(d)
            dlg.setLabelText(f"Leyendo {d} de {t}\n{name}")

        def finished(res):
            dlg.close()
            self.worker = None
            for vid in res.new_ids:
                self.catalog.thumb_path(vid).unlink(missing_ok=True)
                QPixmapCache.remove(f"clip-{vid}")
            self.rebuild_trees()
            self.requery()
            msg = (f"{res.added} nuevos, {res.updated} actualizados, {res.moved} movidos, "
                   f"{res.unchanged} sin cambios")
            self.statusBar().showMessage("Importación: " + msg, 15000)
            if res.errors:
                detail = "\n".join(f"{Path(p).name}: {e.splitlines()[-1] if e else ''}" for p, e in res.errors[:30])
                QMessageBox.warning(self, "Importación", f"{msg}\n\n{len(res.errors)} con errores:\n{detail}")

        def failed(tb):
            dlg.close()
            self.worker = None
            QMessageBox.critical(self, "Importación", tb)

        w.progress.connect(prog)
        w.done.connect(finished)
        w.failed.connect(failed)
        dlg.canceled.connect(w.cancel)
        w.start()

    def dragEnterEvent(self, e):
        if self.catalog and e.mimeData().hasUrls() and any(Path(u.toLocalFile()).is_dir()
                                                           for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        dirs = [u.toLocalFile() for u in e.mimeData().urls() if Path(u.toLocalFile()).is_dir()]
        if dirs:
            self.import_folder(dirs[0])

    # ========================================================== exportar
    def export(self):
        if not self.catalog or self.worker:
            return
        if tools.missing_tools():
            self.show_tools()
            return
        view_picked = [v for v in self.model.videos if v.flag == 1]
        all_picked = self.catalog.query(Filter(flag="picked"))
        sel = self.selected_videos() if self.grid.selectionModel().hasSelection() else []
        dlg = ExportDialog(self, len(view_picked), len(all_picked), len(sel),
                           self.settings.value("last_export", ""))
        if not dlg.exec():
            return
        opts = dlg.options()
        self.settings.setValue("last_export", str(opts.dest))
        vids = {ExportDialog.SCOPE_VIEW: view_picked, ExportDialog.SCOPE_ALL: all_picked,
                ExportDialog.SCOPE_SELECTION: sel}[dlg.scope_id()]
        vids = [self.catalog.get(v.id) for v in vids]  # datos frescos
        items = []
        for v in vids:
            t = self.catalog.video_tags(v.id)
            items.append(ExportItem(v, t["keyword"], t["person"]))
        if not items:
            return

        pd = QProgressDialog("Preparando…", "Cancelar", 0, 1000, self)
        pd.setWindowTitle("Exportar")
        pd.setWindowModality(Qt.WindowModal)
        pd.setMinimumDuration(0)
        w = ExportWorker(items, opts)
        self.worker = w

        def prog(i, total, frac, name):
            pd.setValue(int((i + frac) / total * 1000))
            pd.setLabelText(f"{i + 1} de {total}: {name}")

        def finished(ok, errors, skipped):
            pd.close()
            self.worker = None
            text = f"Exportados: {len(ok)}"
            if skipped:
                text += f"\nOmitidos (ya existían): {skipped}"
            if errors:
                text += f"\nCon errores: {len(errors)}\n\n" + "\n\n".join(
                    f"{Path(p).name}:\n{e}" for p, e in errors[:10])
            box = QMessageBox(QMessageBox.Warning if errors else QMessageBox.Information, "Exportar", text,
                              parent=self)
            open_btn = box.addButton("Abrir carpeta", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(opts.dest)))

        def failed(tb):
            pd.close()
            self.worker = None
            QMessageBox.critical(self, "Exportar", tb)

        w.progress.connect(prog)
        w.done.connect(finished)
        w.failed.connect(failed)
        pd.canceled.connect(w.cancel)
        w.start()

    # =========================================================== catálogo
    def check_missing(self):
        n = self.catalog.refresh_missing()
        self.requery()
        QMessageBox.information(self, APP_NAME, f"Vídeos no encontrados: {n}" +
                                ("\n\nUsa Catálogo › Relocalizar carpeta si has movido el disco o la carpeta."
                                 if n else ""))

    def relocate(self):
        if not self.catalog:
            return
        start = self.filter.folder or (self.catalog.folders()[0][0] if self.catalog.folders() else "")
        old, ok = QInputDialog.getText(self, "Relocalizar", "Ruta antigua (prefijo):", text=start)
        if not ok or not old.strip():
            return
        new = QFileDialog.getExistingDirectory(self, "Nueva ubicación de esa carpeta")
        if not new:
            return
        n = self.catalog.relocate(old.strip(), os.path.normpath(new))
        self.filter.folder = None
        self.rebuild_trees()
        self.requery()
        QMessageBox.information(self, APP_NAME, f"Rutas actualizadas: {n}")

    def regen_thumbs(self):
        for f in self.catalog.previews_dir.glob("*.jpg"):
            f.unlink(missing_ok=True)
        self.thumbs.clear()
        QPixmapCache.clear()
        self.grid.viewport().update()

    def reveal_catalog(self):
        if self.catalog:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.catalog.path.parent)))

    def show_tools(self):
        rows = []
        for t in ("ffmpeg", "ffprobe", "exiftool"):
            p = tools.find_tool(t)
            rows.append(f"<b>{t}</b>: {p or '<span style=color:#d9534f>no encontrado</span>'}")
        rows.append(f"<b>reproductor</b>: {self.player.backend}")
        bin_dir = tools.app_dir() / "bin"
        QMessageBox.information(
            self, "Herramientas externas",
            "<br>".join(rows) +
            f"<p>Copia <i>ffmpeg.exe</i>, <i>ffprobe.exe</i>, <i>exiftool.exe</i> (con su carpeta "
            f"<i>exiftool_files</i>) y <i>libmpv-2.dll</i> en:<br><code>{bin_dir}</code></p>")


def main():
    tools.setup_dll_path()
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clipteca.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    import locale
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv lo exige
    except locale.Error:
        pass
    theme.apply(app)
    QPixmapCache.setCacheLimit(256 * 1024)
    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    QTimer.singleShot(0, win.startup)
    sys.exit(app.exec())
