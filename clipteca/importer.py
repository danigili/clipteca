"""Importación: escanea un directorio y añade/actualiza vídeos en el catálogo."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .catalog import VIDEO_COLUMNS, Catalog, now_iso
from .media import is_video, probe


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    moved: int = 0
    unchanged: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    new_ids: list[int] = field(default_factory=list)


def find_videos(root: Path, recursive: bool = True) -> list[Path]:
    out: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.endswith(" Previews")]
            out += [Path(dirpath, f) for f in filenames if is_video(Path(f))]
    else:
        out = [p for p in root.iterdir() if p.is_file() and is_video(p)]
    return sorted(out)


def import_folder(
    catalog_path: Path,
    root: Path,
    recursive: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    workers: int = 4,
) -> ImportResult:
    conn = Catalog.connect(catalog_path)  # conexión propia: se ejecuta en otro hilo
    res = ImportResult()
    try:
        files = find_videos(root, recursive)
        known = {r["path"]: (r["size"], r["mtime"]) for r in conn.execute("SELECT path, size, mtime FROM videos")}
        todo: list[Path] = []
        for p in files:
            k = known.get(str(p))
            if k is not None:
                st = p.stat()
                if k[0] == st.st_size and abs((k[1] or 0) - st.st_mtime) < 1:
                    res.unchanged += 1
                    conn.execute("UPDATE videos SET missing=0 WHERE path=?", (str(p),))
                    continue
            todo.append(p)
        total = len(todo)
        if progress:
            progress(0, total, "")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(probe, p): p for p in todo}
            for fut in as_completed(futs):
                p = futs[fut]
                if cancelled and cancelled():
                    for f in futs:
                        f.cancel()
                    break
                done += 1
                try:
                    meta = fut.result()
                    _store(conn, meta, res)
                except Exception as e:  # noqa: BLE001
                    res.errors.append((str(p), str(e)))
                if progress:
                    progress(done, total, p.name)
                if done % 50 == 0:
                    conn.commit()
        conn.commit()
    finally:
        conn.close()
    return res


def _store(conn, meta: dict, res: ImportResult) -> None:
    existing = conn.execute("SELECT id FROM videos WHERE path=?", (meta["path"],)).fetchone()
    if existing:
        sets = ", ".join(f"{c}=?" for c in VIDEO_COLUMNS)
        # lat/lon/geo_src se refrescan desde los metadatos salvo que el usuario
        # haya puesto la ubicación a mano (geo_src='manual'): esa no se pisa nunca.
        conn.execute(
            f"UPDATE videos SET {sets}, missing=0, "
            "lat=CASE WHEN geo_src IS NOT 'manual' THEN ? ELSE lat END, "
            "lon=CASE WHEN geo_src IS NOT 'manual' THEN ? ELSE lon END, "
            "geo_src=CASE WHEN geo_src IS NOT 'manual' THEN ? ELSE geo_src END "
            "WHERE id=?",
            [meta[c] for c in VIDEO_COLUMNS] + [meta["lat"], meta["lon"], meta["geo_src"], existing["id"]],
        )
        res.updated += 1
        res.new_ids.append(existing["id"])  # regenerar miniatura
        return
    # ¿Es un vídeo del catálogo que ha cambiado de sitio? (mismo hash y tamaño, ruta vieja inexistente)
    for cand in conn.execute("SELECT id, path FROM videos WHERE quick_hash=? AND size=?",
                             (meta["quick_hash"], meta["size"])):
        if not Path(cand["path"]).exists():
            conn.execute("UPDATE videos SET path=?, folder=?, filename=?, mtime=?, missing=0 WHERE id=?",
                         (meta["path"], meta["folder"], meta["filename"], meta["mtime"], cand["id"]))
            res.moved += 1
            return
    cols = VIDEO_COLUMNS + ["lat", "lon", "geo_src", "imported_at"]
    cur = conn.execute(
        f"INSERT INTO videos({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
        [meta[c] for c in VIDEO_COLUMNS] + [meta["lat"], meta["lon"], meta["geo_src"], now_iso()],
    )
    res.added += 1
    res.new_ids.append(cur.lastrowid)
