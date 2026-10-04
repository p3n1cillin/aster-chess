param([switch]$Publish)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    dotnet build Aster.sln -c Release
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    dotnet run --project tests/Engine.Tests -c Release --no-build
    if ($LASTEXITCODE -ne 0) { throw 'Engine tests failed' }
    $taskPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $taskPython) {
        & $taskPython scripts/verify.py
        if ($LASTEXITCODE -ne 0) { throw 'Independent verification failed' }
    } else {
        Write-Host 'Independent verification needs the development environment described in README.md.'
    }
    if ($Publish) {
        dotnet publish src/Engine/Engine.csproj -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o artifacts/publish/win-x64
        if ($LASTEXITCODE -ne 0) { throw 'Publish failed' }
    }
} finally { Pop-Location }
