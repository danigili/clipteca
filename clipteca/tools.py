"""Localización y ejecución de las herramientas externas (ffmpeg, ffprobe, exiftool, libmpv)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def app_dir() -> Path:
    """Carpeta de la app (junto al .exe si está empaquetada con PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bin_dirs() -> list[Path]:
    dirs = [app_dir() / "bin"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "bin")
    return [d for d in dirs if d.is_dir()]


def setup_dll_path() -> None:
    """Añade ./bin al PATH para que python-mpv encuentre libmpv-2.dll."""
    for d in bin_dirs():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass


@lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    for d in bin_dirs():
        p = d / exe
        if p.is_file():
            return str(p)
    return shutil.which(name)


def missing_tools() -> list[str]:
    return [t for t in ("ffmpeg", "ffprobe", "exiftool") if not find_tool(t)]


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def run(args: list[str], timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = "\n".join(err[-8:])
        raise RuntimeError(f"{Path(args[0]).name} falló ({proc.returncode}):\n{tail}")
    return proc


def ffprobe(path: str) -> dict:
    tool = find_tool("ffprobe")
    if not tool:
        raise RuntimeError("No se encuentra ffprobe")
    proc = run(
        [tool, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        timeout=60,
    )
    return json.loads(proc.stdout.decode("utf-8", "replace"))
