"""Lectura de metadatos (ffprobe), fechas de captura y miniaturas."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import tools

VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".3gp", ".mkv", ".avi", ".mts", ".m2ts", ".ts",
    ".webm", ".wmv", ".mpg", ".mpeg", ".insv", ".lrv",
}
# Contenedores donde exiftool puede escribir XMP embebido
XMP_EMBED_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".insv"}
HDR_TRC = {"arib-std-b67", "smpte2084"}


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("._")


def quick_hash(path: str, size: int) -> str:
    """Hash de 1 MB inicial + 1 MB final + tamaño: suficiente para detectar duplicados/movidos."""
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return h.hexdigest()


# --- fechas -------------------------------------------------------------

_ISO_TZ = re.compile(r"([+-]\d{2}):?(\d{2})$")
_FILENAME_PATTERNS = [
    # PXL_20240512_183022123.mp4 (Pixel, UTC)
    (re.compile(r"PXL_(\d{8})_(\d{6})"), True),
    # VID_20240512_183022.mp4 / 20240512_183022.mp4 (hora local)
    (re.compile(r"(?:VID|MVIMG|video)?[_-]?(\d{8})[_-](\d{6})"), False),
]


def parse_iso(s: str) -> tuple[datetime, str | None] | None:
    """Devuelve (datetime UTC, offset original '+02:00' o None)."""
    s = s.strip()
    if not s or s.startswith("0000"):
        return None
    offset = None
    m = _ISO_TZ.search(s)
    if m:
        offset = f"{m.group(1)}:{m.group(2)}"
        s = s[: m.start()] + offset
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.year < 1971:
        return None
    return dt.astimezone(timezone.utc), offset


def capture_time(info: dict, path: Path) -> tuple[str, str, str | None]:
    """(iso_utc, fuente, tz_offset)."""
    fmt_tags = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
    # 1) Apple/Android con zona horaria
    v = fmt_tags.get("com.apple.quicktime.creationdate")
    if v and (r := parse_iso(v)):
        return r[0].isoformat(), "quicktime.creationdate", r[1]
    # 2) creation_time del contenedor (UTC)
    for src in [fmt_tags] + [
        {k.lower(): v for k, v in (s.get("tags") or {}).items()} for s in info.get("streams", [])
    ]:
        v = src.get("creation_time")
        if v and (r := parse_iso(v)):
            return r[0].isoformat(), "creation_time", None
    # 3) nombre de fichero
    for rx, is_utc in _FILENAME_PATTERNS:
        m = rx.search(path.name)
        if m:
            try:
                dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            if is_utc:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone()  # hora local del equipo
            return dt.astimezone(timezone.utc).isoformat(), "filename", None
    # 4) fecha de modificación
    dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return dt.isoformat(), "mtime", None


def _fps(s: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        v = s.get(key) or ""
        if "/" in v:
            n, d = v.split("/")
            try:
                if float(d):
                    return round(float(n) / float(d), 3)
            except ValueError:
                pass
    return None


def _rotation(s: dict) -> int:
    tags = s.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(tags["rotate"]) % 360
        except ValueError:
            pass
    for sd in s.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(sd["rotation"]) % 360
            except (TypeError, ValueError):
                pass
    return 0


def probe(path: Path) -> dict:
    """Metadatos listos para guardar en el catálogo."""
    info = tools.ffprobe(str(path))
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise ValueError("sin pista de vídeo")
    fmt = info.get("format", {})
    try:
        duration = float(fmt.get("duration") or v.get("duration") or 0) or None
    except ValueError:
        duration = None
    cap, src, tz = capture_time(info, path)
    st = path.stat()
    return {
        "path": str(path),
        "folder": str(path.parent),
        "filename": path.name,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "quick_hash": quick_hash(str(path), st.st_size),
        "capture_time": cap,
        "capture_src": src,
        "tz_offset": tz,
        "duration": duration,
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": _fps(v),
        "vcodec": v.get("codec_name"),
        "acodec": a.get("codec_name") if a else None,
        "pix_fmt": v.get("pix_fmt"),
        "color_primaries": v.get("color_primaries"),
        "color_trc": v.get("color_transfer"),
        "color_space": v.get("color_space"),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "rotation": _rotation(v),
    }


# --- miniaturas ---------------------------------------------------------

_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")


def make_thumbnail(src: str, dst: Path, duration: float | None, hdr: bool, width: int = 360) -> None:
    ff = tools.find_tool("ffmpeg")
    if not ff:
        raise RuntimeError("No se encuentra ffmpeg")
    t = max(0.0, min((duration or 0) * 0.25, 5.0))
    tmp = dst.with_suffix(".tmp.jpg")
    scale = f"scale={width}:-2"
    filters = [(_TONEMAP + scale) if hdr else scale]
    if hdr:
        filters.append(scale)  # por si el ffmpeg no tiene zscale
    last_err: Exception | None = None
    for vf in filters:
        try:
            tools.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", src,
                       "-frames:v", "1", "-vf", vf, "-q:v", "4", "-update", "1", str(tmp)], timeout=120)
            if tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, dst)
                return
        except Exception as e:  # noqa: BLE001
            last_err = e
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"No se pudo generar la miniatura: {last_err}")


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "–"
    sec = max(0.0, sec)
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def fmt_local(iso: str | None, tz_offset: str | None = None) -> str:
    if not iso:
        return "–"
    dt = datetime.fromisoformat(iso)
    if tz_offset:
        sign = 1 if tz_offset[0] == "+" else -1
        hh, mm = tz_offset[1:].split(":")
        dt = dt.astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    else:
        dt = dt.astimezone()
    return dt.strftime("%d/%m/%Y %H:%M:%S")
