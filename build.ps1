# Genera dist\Clipteca\Clipteca.exe (carpeta portable con .\bin incluido)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name Clipteca `
    --collect-submodules clipteca `
    --add-data "clipteca\ui\webres;clipteca\ui\webres" `
    run.py
Copy-Item .\bin .\dist\Clipteca\bin -Recurse -Force
Write-Host "Listo: dist\Clipteca\Clipteca.exe"
