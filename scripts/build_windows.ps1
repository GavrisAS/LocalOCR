param([Parameter(Mandatory=$true)][string]$BuildVersion, [switch]$Validation)
$ErrorActionPreference = 'Stop'
if ($BuildVersion -notmatch '^\d+\.\d+$') { throw 'Expected MAJOR.MINOR' }
function Checked([string]$step) { if ($LASTEXITCODE -ne 0) { throw "$step failed" } }
if ($Validation) {
    if ($env:GITHUB_EVENT_NAME -ne 'workflow_dispatch' -or $env:GITHUB_REF -eq 'refs/heads/main') {
        throw 'Validation is permitted only for a dispatched feature branch; no tag or release'
    }
} else {
    $tagCommit = git rev-list -n 1 "v$BuildVersion"
    Checked 'reserved tag lookup'
    $headCommit = git rev-parse HEAD
    if ($tagCommit -ne $headCommit) { throw 'Reserved tag does not identify HEAD' }
}
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
    Copy-Item docs/START_HERE_RU.md dist/LocalOCR/START_HERE_RU.md
    Copy-Item docs/START_HERE_RU.md dist/LocalOCR/README.md
    '@echo off', 'cd /d "%~dp0"', 'start "" "%~dp0LocalOCR.exe" --full-gui' | Set-Content dist/LocalOCR/LocalOCR-full-gui.cmd -Encoding ascii
    Copy-Item -Recurse dist/LocalOCR-CLI dist/LocalOCR/LocalOCR-CLI
    uv run python scripts/frozen_smoke.py --exe dist/LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe --version $BuildVersion --commit $commit
    Checked 'CLI frozen smoke'
    uv run python scripts/portable_smoke.py --root dist/LocalOCR --version $BuildVersion --commit $commit
    Checked 'Portable paths frozen smoke'
    # This is a fresh CI build; discard only its owned synthetic smoke state.
    foreach ($owned in @('work', 'diagnostics', 'cache')) {
        $path = Join-Path 'dist/LocalOCR' $owned
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
    }
    Remove-Item dist/LocalOCR/config.json -ErrorAction SilentlyContinue
    Get-ChildItem dist/LocalOCR -Filter 'localocr.log*' | Remove-Item -Force
    $zip = "dist/LocalOCR-v$BuildVersion-windows-x64.zip"
    Compress-Archive -Path dist/LocalOCR -DestinationPath $zip -Force
    uv run python scripts/evaluation_smoke.py --root dist/LocalOCR --version $BuildVersion --commit $commit --output dist/evaluation-gates.json --zip $zip
    Checked 'Mandatory extracted ZIP frozen evaluation, privacy and layout gates'
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    "$hash  LocalOCR-v$BuildVersion-windows-x64.zip" | Set-Content "$zip.sha256" -Encoding ascii
} finally {
    Remove-Item $versionModule -ErrorAction SilentlyContinue
}
