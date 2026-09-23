#!/usr/bin/env bash
# Prepara el entorno en Linux: venv + dependencias + ffmpeg, exiftool y libmpv del sistema.
# Uso: ./setup.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== Paquetes del sistema (ffmpeg, exiftool, libmpv)"
if command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y ffmpeg libimage-exiftool-perl libmpv2 python3-venv
elif command -v dnf >/dev/null; then
    sudo dnf install -y ffmpeg perl-Image-ExifTool mpv-libs python3
elif command -v pacman >/dev/null; then
    sudo pacman -S --needed ffmpeg perl-image-exiftool mpv python
else
    echo "Distro no reconocida: instala manualmente ffmpeg, exiftool y libmpv (paquete 'mpv' o 'libmpv')." >&2
fi

echo "== Python y dependencias"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt pyinstaller

echo
echo "Herramientas encontradas:"
for t in ffmpeg ffprobe exiftool; do
    if command -v "$t" >/dev/null; then echo "  $t   OK ($(command -v "$t"))"; else echo "  $t   FALTA"; fi
done
if ldconfig -p 2>/dev/null | grep -q libmpv; then echo "  libmpv OK"; else echo "  libmpv FALTA (instala 'libmpv2'/'mpv-libs'/'mpv')"; fi

echo
echo "Ejecuta:  ./.venv/bin/python run.py"
