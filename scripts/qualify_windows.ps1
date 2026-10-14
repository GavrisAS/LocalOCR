param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Sha
)
$ErrorActionPreference = 'Stop'
$rule = "LocalOCR-qualification-$([Guid]::NewGuid().ToString('N'))"
$profiles = Get-NetFirewallProfile | Select-Object Name, Enabled
try {
    # Runner-only isolation. Allow IPv4 loopback, deny all other outbound destinations.
    # Windows rejects zero-length IPv6 prefixes. Split IPv6 into two /1 subnets.
    # IPv4 0/8 is reserved/non-routable; positive ranges exclude loopback 127/8.
    New-NetFirewallRule -DisplayName "$rule-v4" -Direction Outbound -Action Block -Profile Any -RemoteAddress '1.0.0.0-126.255.255.255','128.0.0.0-255.255.255.254' | Out-Null
    New-NetFirewallRule -DisplayName "$rule-v6" -Direction Outbound -Action Block -Profile Any -RemoteAddress '::/1','8000::/1' | Out-Null
    Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True
    uv run --offline python scripts/qualify_embedded.py --root $Root --output $Output --sha $Sha --network-isolated
    if ($LASTEXITCODE -ne 0) { throw 'Real Windows F16 vision qualification failed' }
} finally {
    Remove-NetFirewallRule -DisplayName "$rule-v4" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "$rule-v6" -ErrorAction SilentlyContinue
    foreach ($profile in $profiles) {
        Set-NetFirewallProfile -Profile $profile.Name -Enabled $profile.Enabled
    }
}
