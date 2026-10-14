param([string]$Destination = (Join-Path $PSScriptRoot 'LocalOCR-Portable'))
$ErrorActionPreference = 'Stop'
$manifest = Get-Content (Join-Path $PSScriptRoot 'portable-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.precision -ne 'f16') { throw 'Invalid portable manifest' }
if (Test-Path $Destination) { throw 'Destination must not exist' }
$staging = "$Destination.assembling-$([Guid]::NewGuid().ToString('N'))"
$archive = Join-Path $PSScriptRoot "assembled-$([Guid]::NewGuid().ToString('N')).zip"
try {
    $out = [IO.File]::Create($archive)
    try {
        foreach ($part in $manifest.parts) {
            if ($part.name -ne [IO.Path]::GetFileName($part.name)) { throw 'Unsafe part name' }
            $path = Join-Path $PSScriptRoot $part.name
            if ((Get-Item $path).Length -ne $part.size -or (Get-FileHash $path -Algorithm SHA256).Hash.ToLower() -ne $part.sha256) { throw 'Part size/hash mismatch' }
            $input = [IO.File]::OpenRead($path)
            try { $input.CopyTo($out, 1048576) } finally { $input.Dispose() }
        }
    } finally { $out.Dispose() }
    if ((Get-Item $archive).Length -ne $manifest.archive_size -or (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower() -ne $manifest.archive_sha256) { throw 'Archive size/hash mismatch' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $staging)
    foreach ($property in $manifest.files.PSObject.Properties) {
        if ($property.Name.Contains('..') -or [IO.Path]::IsPathRooted($property.Name)) { throw 'Unsafe component path' }
        $file = Join-Path $staging ("LocalOCR/embedded/" + $property.Name)
        if ((Get-Item $file).Length -ne $property.Value.size -or (Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -ne $property.Value.sha256) { throw 'Component hash mismatch' }
    }
    Move-Item $staging $Destination
    Write-Output "Portable F16 assembled: $Destination/LocalOCR/LocalOCR.exe"
} finally {
    Remove-Item $archive -Force -ErrorAction SilentlyContinue
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
}
