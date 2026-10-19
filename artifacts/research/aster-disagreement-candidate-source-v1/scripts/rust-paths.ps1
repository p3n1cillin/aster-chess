function Get-AsterCargo {
    $command = Get-Command cargo -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = Join-Path $env:USERPROFILE '.cargo/bin/cargo.exe'
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    throw 'Install Rust with rustup, then restart the terminal.'
}
function Get-AsterTarget([string]$Root) {
    if ($env:CARGO_TARGET_DIR) { return [IO.Path]::GetFullPath($env:CARGO_TARGET_DIR, $Root) }
    if ($Root.StartsWith('\\')) { return Join-Path $env:LOCALAPPDATA 'Aster/cargo-target' }
    return Join-Path $Root 'target'
}
