#!/usr/bin/env bash
# Genera dist/Clipteca/Clipteca (binario portable para Linux).
# ffmpeg/exiftool/libmpv se buscan en el PATH del sistema (instalados por setup.sh),
# así que no hace falta empaquetar bin/ como en Windows.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

./.venv/bin/pyinstaller --noconfirm --clean --windowed --name Clipteca \
    --collect-submodules clipteca run.py

echo "Listo: dist/Clipteca/Clipteca"
