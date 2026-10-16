param([Parameter(Mandatory=$true)][string]$BuildVersion)
$ErrorActionPreference = 'Stop'
if ($BuildVersion -notmatch '^\d+\.\d+$') { throw 'Expected MAJOR.MINOR' }
function Checked([string]$step) { if ($LASTEXITCODE -ne 0) { throw "$step failed" } }
$tagCommit = git rev-list -n 1 "v$BuildVersion"
Checked 'reserved tag lookup'
$headCommit = git rev-parse HEAD
if ($tagCommit -ne $headCommit) { throw 'Reserved tag does not identify HEAD' }
uv sync --locked
Checked 'sync'
$commit = git rev-parse HEAD
$versionModule = 'src/localocr/_build_version.py'
try {
    "BUILD_VERSION = `"$BuildVersion`"`nBUILD_COMMIT = `"$commit`"" | Set-Content $versionModule -Encoding utf8NoBOM
    uv run pyinstaller --noconfirm --clean --onedir --windowed --name LocalOCR --paths src --hidden-import localocr._build_version scripts/gui_launcher.py
    Checked 'GUI build'
    uv run pyinstaller --noconfirm --clean --onedir --console --name LocalOCR-CLI --paths src --hidden-import localocr._build_version scripts/cli_launcher.py
    Checked 'CLI build'
    # Bundle the standard C++ runtime under the CLI's DLL search directory too.
    Copy-Item dist/LocalOCR/_internal/PySide6/MSVCP140*.dll dist/LocalOCR-CLI/_internal/ -Force
    Copy-Item dist/LocalOCR/_internal/PySide6/VCRUNTIME140*.dll dist/LocalOCR-CLI/_internal/ -Force
    $gui = Start-Process -FilePath 'dist/LocalOCR/LocalOCR.exe' -ArgumentList '--smoke-test','--expected-version',$BuildVersion,'--expected-commit',$commit -PassThru
    if (-not $gui.WaitForExit(30000)) { $gui.Kill(); throw 'GUI smoke timeout' }
    if ($gui.ExitCode -ne 0) { throw 'GUI smoke failed' }
    $gui = Start-Process -FilePath 'dist/LocalOCR/LocalOCR.exe' -WorkingDirectory $env:TEMP -ArgumentList '--full-gui','--smoke-test','--expected-version',$BuildVersion,'--expected-commit',$commit -PassThru
    if (-not $gui.WaitForExit(30000)) { $gui.Kill(); throw 'Full GUI smoke timeout' }
    if ($gui.ExitCode -ne 0) { throw 'Full GUI smoke failed' }
    if (-not (Test-Path 'dist/LocalOCR/config.json')) { throw 'Portable config missing' }
    if (-not (Test-Path 'dist/LocalOCR/localocr.log')) { throw 'Portable log missing' }
    # Runtime settings/logs from smoke must never enter release assets.
    Remove-Item dist/LocalOCR/config.json,dist/LocalOCR/localocr.log -ErrorAction SilentlyContinue
    Copy-Item README.md dist/LocalOCR/README.md
    Copy-Item -Recurse dist/LocalOCR-CLI dist/LocalOCR/LocalOCR-CLI
    uv run python scripts/frozen_smoke.py --exe dist/LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe --version $BuildVersion --commit $commit
    Checked 'CLI frozen smoke'
    uv run python scripts/portable_smoke.py --root dist/LocalOCR --version $BuildVersion --commit $commit
    Checked 'Portable paths frozen smoke'
    $zip = "dist/LocalOCR-v$BuildVersion-windows-x64.zip"
    Compress-Archive -Path dist/LocalOCR -DestinationPath $zip -Force
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    "$hash  LocalOCR-v$BuildVersion-windows-x64.zip" | Set-Content "$zip.sha256" -Encoding ascii
} finally {
    Remove-Item $versionModule -ErrorAction SilentlyContinue
}
