"""Tareas en segundo plano: importación, miniaturas y exportación."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from ..exporter import Cancelled, ExportItem, ExportOptions, export_one, plan_destinations
from ..importer import import_folder
from ..media import make_thumbnail


class ImportWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)       # ImportResult
    failed = Signal(str)

    def __init__(self, catalog_path: Path, root: Path, recursive: bool = True):
        super().__init__()
        self.catalog_path, self.root, self.recursive = catalog_path, root, recursive
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = import_folder(self.catalog_path, self.root, self.recursive,
                                progress=lambda d, t, n: self.progress.emit(d, t, n),
                                cancelled=lambda: self._cancel)
            self.done.emit(res)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc(limit=3))


class _ThumbSignals(QObject):
    ready = Signal(int)
    failed = Signal(int, str)


class _ThumbJob(QRunnable):
    def __init__(self, sig, vid, src, dst, duration, hdr):
        super().__init__()
        self.sig, self.vid, self.src, self.dst, self.duration, self.hdr = sig, vid, src, dst, duration, hdr

    def run(self):
        try:
            make_thumbnail(self.src, self.dst, self.duration, self.hdr)
            self.sig.ready.emit(self.vid)
        except Exception as e:  # noqa: BLE001
            self.sig.failed.emit(self.vid, str(e))


class ThumbnailManager(QObject):
    ready = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.sig = _ThumbSignals()
        self.sig.ready.connect(self._on_ready)
        self.sig.failed.connect(self._on_failed)
        self.pending: set[int] = set()
        self.failed: set[int] = set()

    def request(self, video, dst: Path, force: bool = False):
        if video.id in self.pending or (video.id in self.failed and not force) or video.missing:
            return
        self.pending.add(video.id)
        self.failed.discard(video.id)
        self.pool.start(_ThumbJob(self.sig, video.id, video.path, dst, video.duration, video.is_hdr))

    def clear(self):
        self.pool.clear()
        self.pending.clear()
        self.failed.clear()

    def _on_ready(self, vid):
        self.pending.discard(vid)
        self.ready.emit(vid)

    def _on_failed(self, vid, _msg):
        self.pending.discard(vid)
        self.failed.add(vid)


class ExportWorker(QThread):
    progress = Signal(int, int, float, str)     # índice, total, fracción del fichero, nombre
    done = Signal(list, list, int)              # exportados, errores, omitidos
    failed = Signal(str)

    def __init__(self, items: list[ExportItem], opts: ExportOptions):
        super().__init__()
        self.items, self.opts = items, opts
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok, errors, skipped = [], [], 0
        try:
            dests = plan_destinations(self.items, self.opts)
            total = len(self.items)
            for i, (item, dst) in enumerate(zip(self.items, dests)):
                if self._cancel:
                    break
                name = item.video.filename
                self.progress.emit(i, total, 0.0, name)
                try:
                    out = export_one(item, dst, self.opts,
                                     on_progress=lambda f, i=i, n=name: self.progress.emit(i, total, f, n),
                                     cancelled=lambda: self._cancel)
                    if out is None:
                        skipped += 1
                    else:
                        ok.append(str(out))
                except Cancelled:
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append((item.video.path, str(e)))
            self.done.emit(ok, errors, skipped)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc(limit=3))
