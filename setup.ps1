# Prepara el entorno en Windows: venv + dependencias + ffmpeg, exiftool y libmpv en .\bin
# Uso:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location $PSScriptRoot
$bin = Join-Path $PSScriptRoot "bin"
$tmp = Join-Path $env:TEMP "clipteca-setup"
New-Item -ItemType Directory -Force $bin, $tmp | Out-Null

Write-Host "== Python y dependencias"
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller

Write-Host "== ffmpeg / ffprobe (gyan.dev, release essentials)"
if (-not (Test-Path "$bin\ffmpeg.exe")) {
    $zip = "$tmp\ffmpeg.zip"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
    Expand-Archive $zip "$tmp\ffmpeg" -Force
    Get-ChildItem "$tmp\ffmpeg" -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $bin
}

Write-Host "== exiftool"
if (-not (Test-Path "$bin\exiftool.exe")) {
    $ver = (Invoke-WebRequest "https://exiftool.org/ver.txt" -UseBasicParsing).Content.Trim()
    $zip = "$tmp\exiftool.zip"
    Invoke-WebRequest "https://exiftool.org/exiftool-$($ver)_64.zip" -OutFile $zip
    Expand-Archive $zip "$tmp\exiftool" -Force
    $exe = Get-ChildItem "$tmp\exiftool" -Recurse -Filter "exiftool*.exe" | Select-Object -First 1
    Copy-Item $exe.FullName "$bin\exiftool.exe"
    Copy-Item (Join-Path $exe.DirectoryName "exiftool_files") $bin -Recurse -Force
}

Write-Host "== libmpv (shinchiro/mpv-winbuild-cmake)"
if (-not (Test-Path "$bin\libmpv-2.dll")) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
    $asset = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d+-git-.*\.7z$' } | Select-Object -First 1
    $arc = "$tmp\$($asset.name)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $arc
    New-Item -ItemType Directory -Force "$tmp\mpv" | Out-Null
    $ok = $false
    try { tar -xf $arc -C "$tmp\mpv"; $ok = $LASTEXITCODE -eq 0 } catch {}
    if (-not $ok -and (Get-Command 7z -ErrorAction SilentlyContinue)) { 7z x $arc "-o$tmp\mpv" -y | Out-Null; $ok = $true }
    $dll = Get-ChildItem "$tmp\mpv" -Recurse -Filter "libmpv-2.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($dll) { Copy-Item $dll.FullName $bin }
    else { Write-Warning "No se pudo extraer $($asset.name). Descomprímelo con 7-Zip y copia libmpv-2.dll a $bin. Sin ella se usa QtMultimedia (sin tone mapping HDR)." }
}

Write-Host "`nListo. Ejecuta:  .\.venv\Scripts\python.exe run.py"
