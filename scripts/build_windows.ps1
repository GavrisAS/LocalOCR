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
    $gui = Start-Process -FilePath 'dist/LocalOCR/LocalOCR.exe' -ArgumentList '--smoke-test','--expected-version',$BuildVersion,'--expected-commit',$commit -PassThru
    if (-not $gui.WaitForExit(30000)) { $gui.Kill(); throw 'GUI smoke timeout' }
    if ($gui.ExitCode -ne 0) { throw 'GUI smoke failed' }
    uv run python scripts/frozen_smoke.py --exe dist/LocalOCR-CLI/LocalOCR-CLI.exe --version $BuildVersion --commit $commit
    Checked 'CLI frozen smoke'
    Copy-Item README.md dist/LocalOCR/README.md
    Copy-Item -Recurse dist/LocalOCR-CLI dist/LocalOCR/LocalOCR-CLI
    $zip = "dist/LocalOCR-v$BuildVersion-windows-x64.zip"
    Compress-Archive -Path dist/LocalOCR -DestinationPath $zip -Force
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    "$hash  LocalOCR-v$BuildVersion-windows-x64.zip" | Set-Content "$zip.sha256" -Encoding ascii
} finally {
    Remove-Item $versionModule -ErrorAction SilentlyContinue
}
