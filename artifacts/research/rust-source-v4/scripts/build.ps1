param([switch]$Publish)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).ProviderPath
. (Join-Path $PSScriptRoot 'rust-paths.ps1')
$cargo = Get-AsterCargo
$targetDirectory = Get-AsterTarget $projectRoot
Push-Location $projectRoot
try {
    python scripts/fetch_rust_network.py
    if ($LASTEXITCODE -ne 0) { throw 'Neural weight verification failed.' }
    & $cargo build --release --locked --target-dir $targetDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Rust build failed.' }
    & $cargo test --release --locked --target-dir $targetDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Rust tests failed.' }
    & $cargo test --locked --target-dir $targetDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Rust debug tests failed.' }
    if ($Publish) {
        $destination = Join-Path $projectRoot 'artifacts/publish/current-win-x64'
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -LiteralPath (Join-Path $targetDirectory 'release/aster.exe') -Destination $destination
    }
    Write-Output ("Rust executable: " + (Join-Path $targetDirectory 'release/aster.exe'))
} finally { Pop-Location }
