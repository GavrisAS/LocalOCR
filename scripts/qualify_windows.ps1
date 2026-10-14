param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Sha
)
$ErrorActionPreference = 'Stop'
$rule = "LocalOCR-qualification-$([Guid]::NewGuid().ToString('N'))"
try {
    # Runner-only isolation. Allow IPv4 loopback, deny all other outbound destinations.
    New-NetFirewallRule -DisplayName $rule -Direction Outbound -Action Block -Profile Any -RemoteAddress '0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255','::/0' | Out-Null
    uv run --offline python scripts/qualify_embedded.py --root $Root --output $Output --sha $Sha --network-isolated
    if ($LASTEXITCODE -ne 0) { throw 'Real Windows F16 vision qualification failed' }
} finally {
    Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
}
