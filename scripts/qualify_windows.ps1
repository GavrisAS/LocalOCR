param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Sha
)
$ErrorActionPreference = 'Stop'
$rule = "LocalOCR-qualification-$([Guid]::NewGuid().ToString('N'))"
$profiles = Get-NetFirewallProfile | Select-Object Name, Enabled
$temporary = Join-Path ([IO.Path]::GetTempPath()) $rule
$relocated = Join-Path $temporary 'LocalOCR'
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    Copy-Item -Path $Root -Destination $relocated -Recurse
    $programs = @((Join-Path $relocated 'LocalOCR-CLI/LocalOCR-CLI.exe'), (Join-Path $relocated 'embedded/engine/llama-server.exe'))
    $programs += @(Get-ChildItem (Join-Path $relocated 'embedded/engines') -Filter llama-server.exe -Recurse -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    for ($index = 0; $index -lt $programs.Count; $index++) {
        # Scope isolation to the relocated application and engine, preserving runner control.
        New-NetFirewallRule -DisplayName "$rule-$index-v4" -Program $programs[$index] -Direction Outbound -Action Block -Profile Any -RemoteAddress '1.0.0.0-126.255.255.255','128.0.0.0-255.255.255.254' | Out-Null
        New-NetFirewallRule -DisplayName "$rule-$index-v6" -Program $programs[$index] -Direction Outbound -Action Block -Profile Any -RemoteAddress '::/1','8000::/1' | Out-Null
    }
    Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True
    uv run --offline python scripts/qualify_embedded.py --root $relocated --output $Output --sha $Sha --network-isolated --relocated
    if ($LASTEXITCODE -ne 0) { throw 'Real Windows F16 vision qualification failed' }
} finally {
    Get-NetFirewallRule -DisplayName "$rule-*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
    foreach ($profile in $profiles) {
        Set-NetFirewallProfile -Profile $profile.Name -Enabled $profile.Enabled
    }
    Remove-Item $temporary -Recurse -Force -ErrorAction Continue
}
