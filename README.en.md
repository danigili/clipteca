# Clipteca

*[Leer en español](README.md)*

A Lightroom-style video catalog: a `.clipteca` file (SQLite) anywhere you like, you import folders, flag clips with **P**/**X**, trim them, tag keywords and people, and export. Originals are never modified.

## Installation

### Windows

Requirements: Python 3.11+ (the `py` launcher).

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # venv + ffmpeg + exiftool + libmpv into .\bin
.\.venv\Scripts\python.exe run.py
```

Portable executable: `.\build.ps1` → `dist\Clipteca\Clipteca.exe` (ships with `bin\` next to it).

If `setup.ps1` can't extract libmpv's `.7z`, unpack it with 7-Zip and copy `libmpv-2.dll` into `bin\`. Without libmpv the app falls back to QtMultimedia: it works, but without HDR tone mapping or exact frame stepping.

### Linux

Requirements: Python 3.11+ and your distro's package manager (apt/dnf/pacman).

```bash
./setup.sh   # venv + ffmpeg + exiftool + system libmpv (apt/dnf/pacman)
./.venv/bin/python run.py
```

Portable executable: `./build.sh` → `dist/Clipteca/Clipteca` (uses the tools found on the system `PATH`, no `bin\` folder needed).

## Usage

1. **File › New catalog** and pick a location. This creates `Name.clipteca` and a `Name Previews` folder for thumbnails.
2. **Import folder** (or drag a folder onto the window). Subfolders are scanned. Re-importing only reads what changed and detects moved files (partial hash).
3. Review in grid view (**G**) or viewer (**E** / double-click). **P** picks, **X** rejects, **U** clears the flag. *View › Advance on flag* jumps to the next clip.
4. In the viewer, **I** / **O** set in/out points (or drag the timeline handles). **Shift+Space** plays just the trimmed range.
5. Keywords and people go in the right-hand panel (press Enter to add; separate several with commas). With multiple clips selected, they apply to all of them.
6. **Export** (Ctrl+Shift+E): the picks from the current view, the picks from the whole catalog, or the current selection.

F1 shows every shortcut. Search is case- and accent-insensitive (`nuria` matches `Núria`).

## What export does

- **No trim**: an exact copy of the original, with tags added.
- **Lossless trim** (default): `ffmpeg -c copy`. Same codec, bitrate, 10-bit and HDR (HLG/PQ). Only video and audio streams are copied, dropping the phone's data tracks. The start snaps to the previous keyframe (≈1 s on a Pixel), so the clip may begin a bit earlier than requested.
- **Precise trim**: re-encodes the video with the same codec (HEVC→x265, H.264→x264), the same bit depth and the same color metadata. Audio is copied as-is. Quality is controlled via CRF.
- **Capture date**: `CreateDate`, track dates, `Keys:CreationDate` (with time zone) and the file date are all preserved. Optionally the date can be shifted to the start of the trimmed clip.
- **Tags**: written as embedded XMP in MP4/MOV (`dc:subject`, `lr:hierarchicalSubject` with `Personas|Name`, `Iptc4xmpExt:PersonInImage`). Lightroom, digiKam and ExifTool all read them. For MKV/AVI/MTS an `.xmp` sidecar file is created next to the video.
- Option to preserve the subfolder structure by date, relative to the common root.

## Structure

```
clipteca/
  catalog.py    SQLite schema, filters, tags, relocate
  importer.py   scanning + parallel ffprobe
  media.py      metadata, capture date, thumbnails (HDR tone mapping)
  exporter.py   ffmpeg + exiftool + file dates (incl. NTFS creation time)
  app.py        main window
  ui/           grid, viewer (mpv / QtMultimedia), timeline, inspector, dialogs
```

The capture date is looked up in this order: `com.apple.quicktime.creationdate` (with time zone), `creation_time`, the filename (`PXL_…` in UTC, `VID_…` in local time), and the modification date. The inspector shows which of these sources was used.
