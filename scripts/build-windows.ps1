$ErrorActionPreference = 'Stop'

Push-Location -LiteralPath (Join-Path $PSScriptRoot '..')
try {
    $python = '.\.venv\Scripts\python.exe'
    $version = & $python -B -c 'from s1cover import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Install the project and its desktop dependencies first.' }
    $isWindowsX64 = & $python -B -c 'import platform, sys; print(sys.platform == "win32" and platform.machine().upper() == "AMD64" and sys.maxsize > 2**32)'
    if ($LASTEXITCODE -ne 0 -or $isWindowsX64 -ne 'True') { throw 'This build requires 64-bit x86 Windows Python.' }
    $name = "s1cover-$version-windows-x64"
    if (Test-Path -LiteralPath "dist/$name.exe") { throw "dist/$name.exe already exists. Move the previous build before rebuilding." }
    New-Item -ItemType Directory -Path 'build/pyinstaller' -Force | Out-Null
    & $python -m PyInstaller --noconfirm --onefile --windowed --noupx --name $name `
        --paths src --specpath build/pyinstaller --workpath build/pyinstaller --distpath dist `
        --recursive-copy-metadata asf-search --copy-metadata pyproj --copy-metadata pyshp `
        --copy-metadata shapely --copy-metadata defusedxml scripts/s1cover_desktop.py
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath "dist/$name.exe")) { throw 'Windows packaging failed.' }
    Get-FileHash -LiteralPath "dist/$name.exe" -Algorithm SHA256
}
finally {
    Pop-Location
}
