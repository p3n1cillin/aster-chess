param(
    [ValidateRange(1024, 65535)][int]$Port = 5188,
    [switch]$SkipBuild,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$playDll = Join-Path $projectRoot 'src/Play/bin/Release/net8.0/Aster.Play.dll'
$localDirectory = Join-Path $projectRoot '.aster-local'
$recordPath = Join-Path $localDirectory "play-$Port.json"
$address = "http://127.0.0.1:$Port"
if (Test-Path -LiteralPath $recordPath) {
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.processId)" -ErrorAction SilentlyContinue
    if ($existing -and $existing.Name -eq 'dotnet.exe' -and $existing.CommandLine.Contains($playDll) -and $existing.CommandLine.Contains($address)) {
        if ($Stop) { Stop-Process -Id $record.processId; Write-Output 'Aster Play stopped.' }
        else { Write-Output "Aster Play is already running: $address" }
        exit 0
    }
}
if ($Stop) { Write-Output 'Aster Play is not running on this port.'; exit 0 }
if (-not $SkipBuild) {
    dotnet build (Join-Path $projectRoot 'Aster.sln') -c Release
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
}
if (-not (Test-Path -LiteralPath $playDll)) { throw 'Build Aster Play before using -SkipBuild.' }
New-Item -ItemType Directory -Path $localDirectory -Force | Out-Null
$process = Start-Process -FilePath 'dotnet' -ArgumentList @(('"' + $playDll + '"'), '--urls', $address) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $localDirectory "play-$Port.log") -RedirectStandardError (Join-Path $localDirectory "play-$Port.error.log")
@{ processId = $process.Id; address = $address; binary = $playDll } | ConvertTo-Json | Set-Content -LiteralPath $recordPath
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($process.HasExited) { throw "Aster Play exited. See .aster-local/play-$Port.error.log." }
    try {
        $state = Invoke-RestMethod "$address/api/state" -TimeoutSec 1
        if ($state.fen) { Write-Output "Play Aster: $address"; exit 0 }
    } catch { Start-Sleep -Milliseconds 200 }
}
throw "Aster Play did not become ready. See .aster-local/play-$Port.log."
