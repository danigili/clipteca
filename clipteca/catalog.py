"""Catálogo SQLite: un fichero .clipteca elegido por el usuario + carpeta de previsualizaciones al lado."""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS videos(
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    folder        TEXT NOT NULL,
    filename      TEXT NOT NULL,
    size          INTEGER,
    mtime         REAL,
    quick_hash    TEXT,
    capture_time  TEXT,          -- ISO 8601 UTC
    capture_src   TEXT,          -- de dónde salió la fecha
    tz_offset     TEXT,          -- offset original si se conoce (+02:00)
    duration      REAL,
    width         INTEGER,
    height        INTEGER,
    fps           REAL,
    vcodec        TEXT,
    acodec        TEXT,
    pix_fmt       TEXT,
    color_primaries TEXT,
    color_trc     TEXT,
    color_space   TEXT,
    bit_rate      INTEGER,
    rotation      INTEGER DEFAULT 0,
    camera_model  TEXT,
    flag          INTEGER NOT NULL DEFAULT 0,   -- 1 = P, -1 = X, 0 = sin marcar
    trim_in       REAL,
    trim_out      REAL,
    rot_offset    INTEGER NOT NULL DEFAULT 0,   -- rotación manual añadida por el usuario
    missing       INTEGER NOT NULL DEFAULT 0,
    lat           REAL,
    lon           REAL,
    geo_src       TEXT,          -- 'exif' | 'manual'
    imported_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_folder  ON videos(folder);
CREATE INDEX IF NOT EXISTS idx_videos_capture ON videos(capture_time);
CREATE INDEX IF NOT EXISTS idx_videos_hash    ON videos(quick_hash, size);

CREATE TABLE IF NOT EXISTS tags(
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL COLLATE NOCASE,
    kind  TEXT NOT NULL CHECK(kind IN ('keyword','person')),
    UNIQUE(name, kind)
);
CREATE TABLE IF NOT EXISTS video_tags(
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    PRIMARY KEY(video_id, tag_id)
);
"""

VIDEO_COLUMNS = (
    "path folder filename size mtime quick_hash capture_time capture_src tz_offset duration "
    "width height fps vcodec acodec pix_fmt color_primaries color_trc color_space bit_rate rotation "
    "camera_model"
).split()


def fold(s: str | None) -> str:
    """Minúsculas y sin acentos: 'Núria' == 'nuria'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Filter:
    folder: str | None = None          # carpeta (incluye subcarpetas)
    flag: str = "all"                  # all | picked | unflagged | rejected | not_rejected
    text: str = ""                     # nombre de fichero o etiqueta
    tag_id: int | None = None
    camera_model: str | None = None
    only_missing: bool = False
    order: str = "capture_time"        # capture_time | filename


@dataclass
class Video:
    id: int
    path: str
    folder: str
    filename: str
    capture_time: str | None
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    vcodec: str | None
    flag: int
    trim_in: float | None
    trim_out: float | None
    missing: bool
    row: dict = field(repr=False, default_factory=dict)

    @property
    def trimmed(self) -> bool:
        return self.trim_in is not None or self.trim_out is not None

    @property
    def is_hdr(self) -> bool:
        return (self.row.get("color_trc") or "") in ("arib-std-b67", "smpte2084")

    @property
    def has_gps(self) -> bool:
        return self.row.get("lat") is not None

    @property
    def rot_offset(self) -> int:
        return self.row.get("rot_offset") or 0

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Video":
        d = dict(r)
        return cls(
            id=d["id"], path=d["path"], folder=d["folder"], filename=d["filename"],
            capture_time=d["capture_time"], duration=d["duration"], width=d["width"],
            height=d["height"], fps=d["fps"], vcodec=d["vcodec"], flag=d["flag"],
            trim_in=d["trim_in"], trim_out=d["trim_out"], missing=bool(d["missing"]), row=d,
        )


class Catalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = self.connect(self.path)
        self._init_schema()

    # --- conexión -------------------------------------------------------
    @staticmethod
    def connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.create_function("fold", 1, fold, deterministic=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if ver == 0:
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.set_setting("created_at", now_iso())
        elif ver > SCHEMA_VERSION:
            raise RuntimeError("Este catálogo lo creó una versión más nueva de Clipteca")
        elif ver < SCHEMA_VERSION:
            self._migrate(ver)
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        # Columna ya garantizada (recién creada o migrada): el índice es seguro aquí.
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_camera ON videos(camera_model)")
        self.conn.commit()

    def _migrate(self, ver: int) -> None:
        """Añade columnas nuevas a catálogos creados con un esquema anterior."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(videos)")}
        for col, decl in (("lat", "REAL"), ("lon", "REAL"), ("geo_src", "TEXT"),
                          ("camera_model", "TEXT"),
                          ("rot_offset", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE videos ADD COLUMN {col} {decl}")

    def close(self) -> None:
        self.conn.close()

    @property
    def previews_dir(self) -> Path:
        d = self.path.with_name(self.path.stem + " Previews")
        d.mkdir(exist_ok=True)
        return d

    def thumb_path(self, video_id: int) -> Path:
        return self.previews_dir / f"{video_id}.jpg"

    # --- ajustes --------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # --- vídeos ---------------------------------------------------------
    def query(self, f: Filter) -> list[Video]:
        where, args = [], []
        if f.folder:
            folder = f.folder.rstrip("\\/")
            where.append("(folder = ? OR folder LIKE ? ESCAPE '!' OR folder LIKE ? ESCAPE '!')")
            esc = folder.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            args += [folder, esc + "/%", esc + "\\%"]
        if f.flag == "picked":
            where.append("flag = 1")
        elif f.flag == "rejected":
            where.append("flag = -1")
        elif f.flag == "unflagged":
            where.append("flag = 0")
        elif f.flag == "not_rejected":
            where.append("flag >= 0")
        if f.only_missing:
            where.append("missing = 1")
        if f.tag_id is not None:
            where.append("id IN (SELECT video_id FROM video_tags WHERE tag_id = ?)")
            args.append(f.tag_id)
        if f.camera_model is not None:
            where.append("camera_model = ?")
            args.append(f.camera_model)
        if f.text.strip():
            for word in f.text.split():
                like = "%" + fold(word).replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                where.append(
                    "(fold(filename) LIKE ? ESCAPE '!' OR id IN (SELECT vt.video_id FROM video_tags vt "
                    "JOIN tags t ON t.id = vt.tag_id WHERE fold(t.name) LIKE ? ESCAPE '!'))"
                )
                args += [like, like]
        order = "filename COLLATE NOCASE" if f.order == "filename" else "capture_time, filename"
        sql = "SELECT * FROM videos"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order}"
        return [Video.from_row(r) for r in self.conn.execute(sql, args)]

    def get(self, video_id: int) -> Video | None:
        r = self.conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return Video.from_row(r) if r else None

    def get_many(self, ids: list[int]) -> list[Video]:
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM videos WHERE id IN ({q}) ORDER BY capture_time, filename", ids
        )
        return [Video.from_row(r) for r in rows]

    def folders(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT folder, COUNT(*) FROM videos GROUP BY folder ORDER BY folder"
        )]

    def camera_models(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT camera_model, COUNT(*) FROM videos "
            "WHERE camera_model IS NOT NULL AND camera_model != '' "
            "GROUP BY camera_model ORDER BY camera_model COLLATE NOCASE"
        )]

    def counts(self) -> dict[str, int]:
        r = self.conn.execute(
            "SELECT COUNT(*), SUM(flag=1), SUM(flag=-1), SUM(flag=0), SUM(missing=1) FROM videos"
        ).fetchone()
        return {"all": r[0] or 0, "picked": r[1] or 0, "rejected": r[2] or 0,
                "unflagged": r[3] or 0, "missing": r[4] or 0}

    def set_flag(self, ids: list[int], flag: int) -> None:
        self.conn.executemany("UPDATE videos SET flag=? WHERE id=?", [(flag, i) for i in ids])
        self.conn.commit()

    def set_trim(self, video_id: int, trim_in: float | None, trim_out: float | None) -> None:
        self.conn.execute("UPDATE videos SET trim_in=?, trim_out=? WHERE id=?", (trim_in, trim_out, video_id))
        self.conn.commit()

    def rotate(self, ids: list[int], delta: int) -> None:
        """Añade `delta` grados (±90) a la rotación manual de cada vídeo."""
        for i in ids:
            r = self.conn.execute("SELECT rot_offset FROM videos WHERE id=?", (i,)).fetchone()
            if r is None:
                continue
            self.conn.execute("UPDATE videos SET rot_offset=? WHERE id=?", ((r[0] + delta) % 360, i))
        self.conn.commit()

    def set_location(self, video_id: int, lat: float, lon: float) -> None:
        self.conn.execute(
            "UPDATE videos SET lat=?, lon=?, geo_src='manual' WHERE id=?", (lat, lon, video_id)
        )
        self.conn.commit()

    def clear_location(self, video_id: int) -> None:
        self.conn.execute(
            "UPDATE videos SET lat=NULL, lon=NULL, geo_src=NULL WHERE id=?", (video_id,)
        )
        self.conn.commit()

    def remove(self, ids: list[int]) -> None:
        """Quita del catálogo (nunca borra el fichero)."""
        self.conn.executemany("DELETE FROM videos WHERE id=?", [(i,) for i in ids])
        self.conn.commit()
        for i in ids:
            self.thumb_path(i).unlink(missing_ok=True)

    def relocate(self, old_prefix: str, new_prefix: str) -> int:
        """Cambia la ruta base de los vídeos (disco movido, letra de unidad distinta...)."""
        old = old_prefix.rstrip("\\/")
        new = new_prefix.rstrip("\\/")
        rows = self.conn.execute("SELECT id, path, folder FROM videos").fetchall()
        n = 0
        for r in rows:
            p, fo = r["path"], r["folder"]
            if p == old or p.startswith(old + "/") or p.startswith(old + "\\"):
                np_ = new + p[len(old):]
                nf = new + fo[len(old):] if fo.startswith(old) else fo
                missing = 0 if Path(np_).exists() else 1
                self.conn.execute("UPDATE videos SET path=?, folder=?, missing=? WHERE id=?",
                                  (np_, nf, missing, r["id"]))
                n += 1
        self.conn.commit()
        return n

    def refresh_missing(self) -> int:
        rows = self.conn.execute("SELECT id, path FROM videos").fetchall()
        upd = [(0 if Path(r["path"]).exists() else 1, r["id"]) for r in rows]
        self.conn.executemany("UPDATE videos SET missing=? WHERE id=?", upd)
        self.conn.commit()
        return sum(m for m, _ in upd)

    # --- etiquetas -------------------------------------------------------
    def all_tags(self, kind: str | None = None) -> list[tuple[int, str, str, int]]:
        sql = ("SELECT t.id, t.name, t.kind, COUNT(vt.video_id) FROM tags t "
               "LEFT JOIN video_tags vt ON vt.tag_id = t.id")
        args: list = []
        if kind:
            sql += " WHERE t.kind=?"
            args.append(kind)
        sql += " GROUP BY t.id ORDER BY t.kind, t.name COLLATE NOCASE"
        return [tuple(r) for r in self.conn.execute(sql, args)]

    def tag_id(self, name: str, kind: str) -> int:
        name = name.strip()
        r = self.conn.execute("SELECT id FROM tags WHERE name=? AND kind=?", (name, kind)).fetchone()
        if r:
            return r[0]
        cur = self.conn.execute("INSERT INTO tags(name, kind) VALUES(?,?)", (name, kind))
        return cur.lastrowid

    def video_tags(self, video_id: int) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"keyword": [], "person": []}
        for r in self.conn.execute(
            "SELECT t.name, t.kind FROM tags t JOIN video_tags vt ON vt.tag_id=t.id "
            "WHERE vt.video_id=? ORDER BY t.name COLLATE NOCASE", (video_id,)
        ):
            out[r["kind"]].append(r["name"])
        return out

    def common_tags(self, ids: list[int]) -> dict[str, list[str]]:
        """Etiquetas presentes en todos los vídeos indicados."""
        if not ids:
            return {"keyword": [], "person": []}
        sets = [self.video_tags(i) for i in ids]
        out = {}
        for kind in ("keyword", "person"):
            common = set(sets[0][kind])
            for s in sets[1:]:
                common &= set(s[kind])
            out[kind] = sorted(common, key=str.casefold)
        return out

    def add_tags(self, ids: list[int], names: list[str], kind: str) -> None:
        for name in {n.strip() for n in names if n.strip()}:
            tid = self.tag_id(name, kind)
            self.conn.executemany("INSERT OR IGNORE INTO video_tags(video_id, tag_id) VALUES(?,?)",
                                  [(i, tid) for i in ids])
        self.conn.commit()

    def remove_tag(self, ids: list[int], name: str, kind: str) -> None:
        r = self.conn.execute("SELECT id FROM tags WHERE name=? AND kind=?", (name, kind)).fetchone()
        if not r:
            return
        self.conn.executemany("DELETE FROM video_tags WHERE video_id=? AND tag_id=?", [(i, r[0]) for i in ids])
        self.conn.execute("DELETE FROM tags WHERE id=? AND NOT EXISTS (SELECT 1 FROM video_tags WHERE tag_id=?)",
                          (r[0], r[0]))
        self.conn.commit()

    def rename_tag(self, tag_id: int, new_name: str) -> None:
        self.conn.execute("UPDATE tags SET name=? WHERE id=?", (new_name.strip(), tag_id))
        self.conn.commit()
