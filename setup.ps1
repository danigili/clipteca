# Prepara el entorno en Windows: venv + dependencias + ffmpeg, exiftool y libmpv en .\bin
# Uso:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Set-Location $PSScriptRoot
$bin = Join-Path $PSScriptRoot "bin"
$tmp = Join-Path $env:TEMP "clipteca-setup"
New-Item -ItemType Directory -Force $bin, $tmp | Out-Null

Write-Host "== Python y dependencias"
if (-not (Test-Path .venv)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
    else { throw "No se encuentra Python. Instálalo con: winget install -e --id Python.Python.3.12 (y abre una PowerShell nueva)" }
    if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw "No se pudo crear .venv (¿Python de la Microsoft Store?). Instala Python desde python.org o winget." }
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias de Python" }

Write-Host "== ffmpeg / ffprobe (gyan.dev, release essentials)"
if (-not (Test-Path "$bin\ffmpeg.exe") -or -not (Test-Path "$bin\ffprobe.exe")) {
    $zip = "$tmp\ffmpeg.zip"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip -UseBasicParsing
    Remove-Item "$tmp\ffmpeg" -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip "$tmp\ffmpeg" -Force
    Get-ChildItem "$tmp\ffmpeg" -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $bin
}

Write-Host "== exiftool"
if (-not (Test-Path "$bin\exiftool.exe")) {
    $html = (Invoke-WebRequest "https://exiftool.org/" -UseBasicParsing).Content
    $name = [regex]::Match($html, 'exiftool-[\d.]+_64\.zip').Value
    if (-not $name) { throw "No se encontró el zip de exiftool en exiftool.org" }
    $zip = "$tmp\exiftool.zip"
    try {
        Invoke-WebRequest "https://exiftool.org/$name" -OutFile $zip -UseBasicParsing
    } catch {
        Write-Host "   exiftool.org falló, probando SourceForge…"
        Invoke-WebRequest "https://sourceforge.net/projects/exiftool/files/$name/download" -OutFile $zip -UserAgent "Wget" -UseBasicParsing
    }
    Remove-Item "$tmp\exiftool" -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $zip "$tmp\exiftool" -Force
    $exe = Get-ChildItem "$tmp\exiftool" -Recurse -Filter "exiftool*.exe" | Select-Object -First 1
    if (-not $exe) { throw "El zip de exiftool no contiene el .exe esperado" }
    Copy-Item $exe.FullName "$bin\exiftool.exe"
    Copy-Item (Join-Path $exe.DirectoryName "exiftool_files") $bin -Recurse -Force
}

Write-Host "== libmpv (shinchiro/mpv-winbuild-cmake)"
if (-not (Test-Path "$bin\libmpv-2.dll")) {
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest" -UseBasicParsing
        $asset = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d+-git-.*\.7z$' } | Select-Object -First 1
        if (-not $asset) { throw "no se encontró el paquete mpv-dev-x86_64 en la última release" }
        $arc = "$tmp\$($asset.name)"
        Invoke-WebRequest $asset.browser_download_url -OutFile $arc -UseBasicParsing
        Remove-Item "$tmp\mpv" -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force "$tmp\mpv" | Out-Null
        $ErrorActionPreference = "Continue"
        tar -xf $arc -C "$tmp\mpv" 2>$null
        if (-not (Get-ChildItem "$tmp\mpv" -Recurse -Filter "libmpv-2.dll")) {
            $7z = @("7z", "$env:ProgramFiles\7-Zip\7z.exe") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
            if ($7z) { & $7z x $arc "-o$tmp\mpv" -y | Out-Null }
        }
        $ErrorActionPreference = "Stop"
        $dll = Get-ChildItem "$tmp\mpv" -Recurse -Filter "libmpv-2.dll" | Select-Object -First 1
        if ($dll) { Copy-Item $dll.FullName $bin }
        else { throw "no se pudo extraer $($asset.name) (instala 7-Zip o descomprímelo a mano)" }
    } catch {
        $ErrorActionPreference = "Stop"
        Write-Warning "libmpv: $($_.Exception.Message). Copia libmpv-2.dll a $bin. Sin ella se usa QtMultimedia (sin tone mapping HDR)."
    }
}

Write-Host "`nHerramientas en ${bin}:"
foreach ($f in "ffmpeg.exe", "ffprobe.exe", "exiftool.exe", "libmpv-2.dll") {
    $ok = Test-Path (Join-Path $bin $f)
    Write-Host ("  {0,-14} {1}" -f $f, $(if ($ok) { "OK" } else { "FALTA" }))
}
Write-Host "`nEjecuta:  .\.venv\Scripts\python.exe run.py"
