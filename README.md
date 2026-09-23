# Clipteca

Catálogo de vídeos al estilo Lightroom: un fichero `.clipteca` (SQLite) donde tú quieras, importas carpetas, marcas **P**/**X**, recortas, etiquetas palabras clave y personas, y exportas. Los originales nunca se modifican.

## Instalación (Windows)

Requisitos: Python 3.11+ (`py` launcher).

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # venv + ffmpeg + exiftool + libmpv en .\bin
.\.venv\Scripts\python.exe run.py
```

Ejecutable portable: `.\build.ps1` → `dist\Clipteca\Clipteca.exe` (lleva `bin\` al lado).

Si `setup.ps1` no puede extraer el `.7z` de libmpv, descomprímelo con 7-Zip y copia `libmpv-2.dll` a `bin\`. Sin libmpv la app usa QtMultimedia: funciona, pero sin tone mapping HDR ni paso exacto de fotogramas.

## Uso

1. **Archivo › Nuevo catálogo** y elige ubicación. Se crea `Nombre.clipteca` y la carpeta `Nombre Previews` con las miniaturas.
2. **Importar carpeta** (o arrastra una carpeta a la ventana). Escanea subcarpetas. Reimportar solo lee lo que ha cambiado y detecta ficheros movidos (hash parcial).
3. Revisa en cuadrícula (**G**) o visor (**E** / doble clic). **P** selecciona, **X** rechaza, **U** quita la marca. *Vista › Avanzar al marcar* salta al siguiente.
4. En el visor, **I** / **O** marcan entrada y salida (o arrastra los tiradores de la línea de tiempo). **Mayús+Espacio** reproduce solo el recorte.
5. Palabras clave y personas en el panel derecho (Intro para añadir, varias separadas por comas). Con varios vídeos seleccionados se aplican a todos.
6. **Exportar** (Ctrl+Mayús+E): los P de la vista, los P de todo el catálogo o la selección.

F1 muestra todos los atajos. La búsqueda ignora mayúsculas y acentos (`nuria` encuentra `Núria`).

## Qué hace la exportación

- **Sin recorte**: copia exacta del original y se añaden las etiquetas.
- **Recorte sin pérdida** (por defecto): `ffmpeg -c copy`. Mismo códec, bitrate, 10 bits y HDR (HLG/PQ). Solo copia vídeo y audio, descartando las pistas de datos del móvil. El inicio cae en el fotograma clave anterior (≈1 s en un Pixel), así que el clip puede empezar un poco antes.
- **Recorte preciso**: recodifica el vídeo con el mismo códec (HEVC→x265, H.264→x264), la misma profundidad de bits y los mismos metadatos de color. El audio se copia. La calidad se controla con el CRF.
- **Fecha de captura**: se conservan `CreateDate`, las fechas de pista, `Keys:CreationDate` (con zona horaria) y la fecha del fichero. Opcionalmente se puede desplazar la fecha al inicio del recorte.
- **Etiquetas**: se escriben en XMP embebido en MP4/MOV (`dc:subject`, `lr:hierarchicalSubject` con `Personas|Nombre`, `Iptc4xmpExt:PersonInImage`). Lightroom, digiKam y ExifTool las leen. En MKV/AVI/MTS se crea un `.xmp` al lado del vídeo.
- Opción de mantener la estructura de subcarpetas por fecha relativa a la raíz común.

## Estructura

```
clipteca/
  catalog.py    esquema SQLite, filtros, etiquetas, relocalizar
  importer.py   escaneo + ffprobe en paralelo
  media.py      metadatos, fecha de captura, miniaturas (tone mapping HDR)
  exporter.py   ffmpeg + exiftool + fechas de fichero (incl. creación NTFS)
  app.py        ventana principal
  ui/           cuadrícula, visor (mpv / QtMultimedia), timeline, inspector, diálogos
```

La fecha de captura se busca en este orden: `com.apple.quicktime.creationdate` (con zona), `creation_time`, el nombre del fichero (`PXL_…` en UTC, `VID_…` en hora local) y la fecha de modificación. El inspector muestra de cuál de estas fuentes salió.
