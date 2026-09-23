"""Exportación: recorta (sin recodificar o preciso), conserva fecha de captura y escribe etiquetas."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from . import tools
from .catalog import Video
from .media import XMP_EMBED_EXTS

PEOPLE_ROOT = "Personas"
MP4_FAMILY = {".mp4", ".mov", ".m4v", ".3gp", ".insv"}

ENCODERS = {  # codec origen -> (encoder, args de calidad)
    "hevc": ("libx265", lambda crf: ["-crf", str(crf), "-preset", "medium"]),
    "h264": ("libx264", lambda crf: ["-crf", str(crf), "-preset", "medium"]),
    "vp9": ("libvpx-vp9", lambda crf: ["-crf", str(crf + 12), "-b:v", "0", "-row-mt", "1"]),
    "av1": ("libsvtav1", lambda crf: ["-crf", str(crf + 10), "-preset", "8"]),
}

# Modo "comprimir mucho": HEVC con CRF fijo (calidad constante) y tope de
# bitrate/bufsize (VBV) para que las escenas complicadas no se disparen de
# tamaño — el híbrido habitual en encoders de entrega. El bitrate tope escala
# con la resolución elegida (a más resolución, más bits o se ve fatal).
# resolución (lado corto) -> (lado largo, maxrate, bufsize)
COMPRESS_RESOLUTIONS = {
    2160: (3840, "16000k", "32000k"),
    1440: (2560, "8000k",  "16000k"),
    1080: (1920, "3600k",  "7200k"),
    720:  (1280, "2000k",  "4000k"),
    480:  (854,  "1200k",  "2400k"),
    0:    (0,    "5000k",  "10000k"),   # 0 = resolución original, sin reescalar
}
COMPRESS_AUDIO_BITRATE = "128k"


@dataclass
class ExportOptions:
    dest: Path
    precise: bool = False          # False = corte sin pérdida en keyframe; True = recodifica
    crf: int = 18
    compress: bool = False         # HEVC, tope de bitrate (ignora precise/crf)
    compress_crf: int = 28
    compress_keep_hdr: bool = False   # False = tonemapea a SDR (más compatible/ligero)
    compress_resolution: int = 1080   # lado corto en px; 0 = no reescalar
    date_shift: bool = False       # True = fecha de captura + inicio del recorte
    keep_structure: bool = True    # recrea subcarpetas relativas a la raíz común
    conflict: str = "rename"       # rename | skip | overwrite
    write_tags: bool = True


@dataclass
class ExportItem:
    video: Video
    keywords: list[str]
    people: list[str]


class Cancelled(Exception):
    pass


# --- utilidades --------------------------------------------------------

def trim_range(v: Video) -> tuple[float, float | None, bool]:
    """(inicio, duración o None, recortado?)."""
    dur = v.duration or 0
    tin = max(0.0, v.trim_in or 0.0)
    tout = v.trim_out if v.trim_out is not None else dur
    if dur and tout > dur:
        tout = dur
    trimmed = tin > 0.01 or (dur > 0 and tout < dur - 0.01)
    if not trimmed:
        return 0.0, None, False
    return tin, max(0.04, tout - tin), True


def output_capture_time(v: Video, opts: ExportOptions) -> datetime | None:
    if not v.capture_time:
        return None
    dt = datetime.fromisoformat(v.capture_time)
    if opts.date_shift and v.trim_in:
        dt += timedelta(seconds=v.trim_in)
    return dt.astimezone(timezone.utc)


def _tz(offset: str | None) -> timezone | None:
    if not offset:
        return None
    sign = 1 if offset[0] == "+" else -1
    hh, mm = offset[1:].split(":")
    return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while True:
        c = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not c.exists():
            return c
        i += 1


def set_file_times(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))
    if os.name == "nt":  # fecha de creación en NTFS
        import ctypes
        from ctypes import wintypes

        ft = int((ts + 11644473600) * 10_000_000)
        ftime = wintypes.FILETIME(ft & 0xFFFFFFFF, ft >> 32)
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        h = k32.CreateFileW(str(path), 0x100, 0x7, None, 3, 0x80, None)  # FILE_WRITE_ATTRIBUTES, OPEN_EXISTING
        if h and h != wintypes.HANDLE(-1).value:
            try:
                k32.SetFileTime(h, ctypes.byref(ftime), ctypes.byref(ftime), ctypes.byref(ftime))
            finally:
                k32.CloseHandle(h)


# --- ffmpeg ------------------------------------------------------------

def _compress_filter(v: Video, opts: ExportOptions) -> str | None:
    """Tonemapea HDR→SDR (salvo que se pida mantener HDR) y escala hacia abajo a la
    resolución elegida (sin ampliar, respeta la orientación); nunca reinterpreta
    píxeles HDR como BT.709 directamente, o sale lavado/oscuro."""
    is_hdr = (v.row.get("color_trc") or "") in ("arib-std-b67", "smpte2084")
    filters = []
    if is_hdr and not opts.compress_keep_hdr:
        filters.append(
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    long_edge, _, _ = COMPRESS_RESOLUTIONS.get(opts.compress_resolution, COMPRESS_RESOLUTIONS[1080])
    if long_edge:
        short_edge = opts.compress_resolution
        filters.append(
            f"scale='if(gt(a,1),{long_edge},{short_edge})':'if(gt(a,1),{short_edge},{long_edge})':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
    return ",".join(filters) if filters else None


def _rotate_filter(v: Video) -> str | None:
    """Filtro `transpose` para hornear la rotación manual del usuario en los píxeles."""
    n = (v.rot_offset // 90) % 4
    if n == 0:
        return None
    return ",".join(["transpose=1"] * n) if n <= 2 else "transpose=2"  # 270° = 90° CCW


def ffmpeg_args(v: Video, src: str, dst: str, start: float, dur: float, opts: ExportOptions) -> list[str]:
    ff = tools.find_tool("ffmpeg")
    if not ff:
        raise RuntimeError("No se encuentra ffmpeg")
    ext = Path(dst).suffix.lower()
    a = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
         "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
         "-map", "0:v:0", "-map", "0:a?",   # evita pistas de datos (giroscopio, etc.)
         "-map_metadata", "0", "-map_chapters", "-1"]
    rot_filter = _rotate_filter(v)
    out_is_hevc = False
    if opts.compress:
        is_hdr = (v.row.get("color_trc") or "") in ("arib-std-b67", "smpte2084")
        keep_hdr = is_hdr and opts.compress_keep_hdr
        _, maxrate, bufsize = COMPRESS_RESOLUTIONS.get(opts.compress_resolution, COMPRESS_RESOLUTIONS[1080])
        cf = _compress_filter(v, opts)
        vf = rot_filter + "," + cf if (rot_filter and cf) else (rot_filter or cf)
        if vf:
            a += ["-vf", vf]
        a += ["-c:v", "libx265", "-crf", str(opts.compress_crf), "-preset", "medium",
              "-maxrate", maxrate, "-bufsize", bufsize,
              "-pix_fmt", "yuv420p10le" if keep_hdr else "yuv420p"]
        if keep_hdr:
            for opt, key in (("-color_primaries", "color_primaries"), ("-color_trc", "color_trc"),
                             ("-colorspace", "color_space")):
                val = v.row.get(key)
                if val and val != "unknown":
                    a += [opt, val]
        a += ["-c:a", "aac", "-b:a", COMPRESS_AUDIO_BITRATE, "-ac", "2"]
        out_is_hevc = True
    elif opts.precise or rot_filter:
        vc = v.row.get("vcodec") or ""
        enc, q = ENCODERS.get(vc, ENCODERS["h264"])
        a += ["-c:v", enc, *q(opts.crf)]
        if rot_filter:
            a += ["-vf", rot_filter]
        pf = v.row.get("pix_fmt") or ""
        a += ["-pix_fmt", "yuv420p10le" if "10" in pf else "yuv420p"]
        for opt, key in (("-color_primaries", "color_primaries"), ("-color_trc", "color_trc"),
                         ("-colorspace", "color_space")):
            val = v.row.get(key)
            if val and val != "unknown":
                a += [opt, val]
        a += ["-c:a", "copy"]
        out_is_hevc = vc == "hevc"
    else:
        a += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    if ext in MP4_FAMILY:
        a += ["-movflags", "+faststart+use_metadata_tags"]
        if out_is_hevc:
            a += ["-tag:v", "hvc1"]
    a += ["-progress", "pipe:1", "-nostats", dst]
    return a


def run_ffmpeg(args: list[str], dur: float, on_progress: Callable[[float], None] | None,
               cancelled: Callable[[], bool] | None) -> None:
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errf,
                                creationflags=0x08000000 if os.name == "nt" else 0)
        assert proc.stdout
        for raw in proc.stdout:
            if cancelled and cancelled():
                proc.kill()
                proc.wait()
                raise Cancelled()
            line = raw.decode("ascii", "replace").strip()
            if line.startswith("out_time_us=") and on_progress and dur > 0:
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, us / 1e6 / dur))
                except ValueError:
                    pass
        rc = proc.wait()
        if rc != 0:
            errf.seek(0)
            tail = errf.read().decode("utf-8", "replace").strip().splitlines()[-8:]
            raise RuntimeError("ffmpeg falló:\n" + "\n".join(tail))


# --- metadatos ---------------------------------------------------------

def _exiftool(args: list[str]) -> None:
    et = tools.find_tool("exiftool")
    if not et:
        raise RuntimeError("No se encuentra exiftool")
    # Fichero de argumentos UTF-8: rutas y etiquetas con acentos en Windows
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        f.write("\n".join(["-charset", "filename=utf8", "-api", "LargeFileSupport=1",
                           "-api", "QuickTimeUTC=1", "-overwrite_original", "-m", *args]) + "\n")
        argfile = f.name
    try:
        tools.run([et, "-@", argfile], timeout=300)
    finally:
        os.unlink(argfile)


def _exif_date(dt: datetime, tz: timezone | None = None) -> str:
    d = dt.astimezone(tz or timezone.utc)
    off = d.strftime("%z")
    return d.strftime("%Y:%m:%d %H:%M:%S") + f"{off[:3]}:{off[3:]}"


def write_embedded(dst: Path, src: str, item: ExportItem, cap: datetime | None,
                   copy_from_src: bool, shifted: bool, opts: ExportOptions) -> None:
    v = item.video
    if copy_from_src:
        # ffmpeg no copia todo (p. ej. XMP, algunas claves de fabricante): se copia lo escribible
        _exiftool(["-TagsFromFile", src, "-all:all", "-unsafe", str(dst)])
    args: list[str] = []
    if cap and (shifted or copy_from_src):
        d = _exif_date(cap)
        for tag in ("QuickTime:CreateDate", "QuickTime:ModifyDate", "QuickTime:TrackCreateDate",
                    "QuickTime:TrackModifyDate", "QuickTime:MediaCreateDate", "QuickTime:MediaModifyDate"):
            args.append(f"-{tag}={d}")
        tz = _tz(v.row.get("tz_offset"))
        if tz is not None:
            args.append(f"-Keys:CreationDate={_exif_date(cap, tz)}")
        args.append(f"-XMP-xmp:CreateDate={_exif_date(cap, tz)}")
    lat, lon = v.row.get("lat"), v.row.get("lon")
    if lat is not None and lon is not None:
        args += [
            f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
        ]
    if opts.write_tags:
        for kw in item.keywords + item.people:
            args += [f"-XMP-dc:Subject-={kw}", f"-XMP-dc:Subject+={kw}"]
        for kw in item.keywords:
            args += [f"-XMP-lr:HierarchicalSubject-={kw}", f"-XMP-lr:HierarchicalSubject+={kw}"]
        for p in item.people:
            h = f"{PEOPLE_ROOT}|{p}"
            args += [f"-XMP-lr:HierarchicalSubject-={h}", f"-XMP-lr:HierarchicalSubject+={h}",
                     f"-XMP-iptcExt:PersonInImage-={p}", f"-XMP-iptcExt:PersonInImage+={p}"]
    if args:
        _exiftool(args + [str(dst)])


def write_sidecar(dst: Path, item: ExportItem, cap: datetime | None) -> Path:
    """Para contenedores sin XMP embebido (mkv, avi, mts...): fichero .xmp al lado."""
    def bag(tag: str, values: list[str]) -> str:
        if not values:
            return ""
        li = "".join(f"<rdf:li>{escape(x)}</rdf:li>" for x in values)
        return f"<{tag}><rdf:Bag>{li}</rdf:Bag></{tag}>"
    hier = item.keywords + [f"{PEOPLE_ROOT}|{p}" for p in item.people]
    date = ""
    if cap:
        tz = _tz(item.video.row.get("tz_offset")) or timezone.utc
        date = f"<xmp:CreateDate>{cap.astimezone(tz).isoformat(timespec='seconds')}</xmp:CreateDate>"
    xml = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/"
 xmlns:lr="http://ns.adobe.com/lightroom/1.0/" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
{date}{bag('dc:subject', item.keywords + item.people)}{bag('lr:hierarchicalSubject', hier)}{bag('Iptc4xmpExt:PersonInImage', item.people)}
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"""
    sc = dst.with_suffix(".xmp")
    sc.write_text(xml, encoding="utf-8")
    return sc


# --- exportación -------------------------------------------------------

def plan_destinations(items: list[ExportItem], opts: ExportOptions) -> list[Path]:
    folders = [i.video.folder for i in items]
    root = None
    if opts.keep_structure and folders:
        try:
            root = os.path.commonpath(folders)
        except ValueError:  # unidades distintas en Windows
            root = None
    out = []
    for it in items:
        rel = Path()
        if root is not None:
            rel = Path(os.path.relpath(it.video.folder, root))
            if str(rel) == ".":
                rel = Path()
        out.append(opts.dest / rel / it.video.filename)
    return out


def export_one(item: ExportItem, dst: Path, opts: ExportOptions,
               on_progress: Callable[[float], None] | None = None,
               cancelled: Callable[[], bool] | None = None) -> Path | None:
    v = item.video
    src = v.path
    if not Path(src).exists():
        raise FileNotFoundError(f"No existe el original: {src}")
    if dst.exists():
        if opts.conflict == "skip":
            return None
        if opts.conflict == "rename":
            dst = unique_path(dst)
    if Path(src).resolve() == dst.resolve():
        raise RuntimeError("El destino coincide con el original")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.stem}.clipteca-part{dst.suffix}")
    tmp.unlink(missing_ok=True)

    start, dur, trimmed = trim_range(v)
    cap = output_capture_time(v, opts)
    shifted = trimmed and opts.date_shift and bool(v.trim_in)
    reencode = trimmed or opts.precise or opts.compress or v.rot_offset != 0
    try:
        if reencode:
            if dur is None:
                start, dur = 0.0, v.duration or 0.0
            run_ffmpeg(ffmpeg_args(v, src, str(tmp), start, dur, opts), dur, on_progress, cancelled)
        else:
            shutil.copy2(src, tmp)  # sin recorte: copia exacta del original
        if on_progress:
            on_progress(1.0)
        embed = dst.suffix.lower() in XMP_EMBED_EXTS
        if embed:
            write_embedded(tmp, src, item, cap, copy_from_src=reencode, shifted=shifted, opts=opts)
        os.replace(tmp, dst)
        if not embed and opts.write_tags and (item.keywords or item.people or cap):
            write_sidecar(dst, item, cap)
        if cap:
            set_file_times(dst, cap)
        return dst
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
