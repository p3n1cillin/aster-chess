param(
    [ValidateRange(1024,65535)][int]$Port = 5188,
    [switch]$SkipBuild,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'rust-paths.ps1')
$localDirectory = Join-Path $projectRoot '.aster-local'
$recordPath = Join-Path $localDirectory "rust-play-$Port.json"
$address = "http://127.0.0.1:$Port"
if (Test-Path -LiteralPath $recordPath) {
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.processId)" -ErrorAction SilentlyContinue
    if ($existing -and $existing.Name -eq 'aster.exe' -and $existing.CommandLine.Contains($record.binary) -and $existing.CommandLine.EndsWith("play $Port")) {
        if ($Stop) { Stop-Process -Id $record.processId; Write-Output 'Aster Rust Play stopped.' }
        else { Write-Output "Aster Rust Play is already running: $address" }
        exit 0
    }
}
if ($Stop) { Write-Output 'No owned Aster Rust host on this port.'; exit 0 }
if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Rust build failed.' }
}
$binary = Join-Path (Get-AsterTarget $projectRoot) 'release/aster.exe'
if (-not (Test-Path -LiteralPath $binary)) { throw 'Build the Rust executable first.' }
# Run an immutable local copy so a future build cannot overwrite an active game.
$digest = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
$runtimeDirectory = Join-Path $env:LOCALAPPDATA "Aster/play/$digest"
$runtimeBinary = Join-Path $runtimeDirectory 'aster.exe'
New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
if (-not (Test-Path -LiteralPath $runtimeBinary)) { Copy-Item -LiteralPath $binary -Destination $runtimeBinary }
if ((Get-FileHash -LiteralPath $runtimeBinary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'Frozen host checksum mismatch.' }
New-Item -ItemType Directory -Force -Path $localDirectory | Out-Null
$process = Start-Process -FilePath $runtimeBinary -ArgumentList @('play',"$Port") -WorkingDirectory $runtimeDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $localDirectory "rust-play-$Port.log") -RedirectStandardError (Join-Path $localDirectory "rust-play-$Port.error.log")
@{processId=$process.Id;address=$address;binary=$runtimeBinary;sha256=$digest} | ConvertTo-Json | Set-Content -LiteralPath $recordPath
for ($attempt=0;$attempt -lt 40;$attempt++) {
    if ($process.HasExited) { throw 'Rust host exited. Check .aster-local/rust-play error log.' }
    try {
        $state = Invoke-RestMethod "$address/api/state" -TimeoutSec 1
        if ($state.engine) { Write-Output "Play Aster Rust: $address"; exit 0 }
    } catch { Start-Sleep -Milliseconds 150 }
}
throw 'Rust host did not become ready.'
