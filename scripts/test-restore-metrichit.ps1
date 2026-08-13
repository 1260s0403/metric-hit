[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

try {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $backupRoot = Join-Path (Split-Path -Parent $repoRoot) 'external-backups'
    $archive = Get-ChildItem -LiteralPath $backupRoot -File -Filter 'MetricHit-backup-*.zip' |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($null -eq $archive) { throw "No MetricHit backup archive found in $backupRoot" }

    $checksumPath = "$($archive.FullName).sha256"
    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) { throw "Checksum file not found: $checksumPath" }
    $expectedHash = (Get-Content -LiteralPath $checksumPath -Raw).Trim().Split(' ')[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) { throw 'SHA-256 verification failed before restore.' }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archive.FullName)
    try {
        if ($zip.Entries.Count -eq 0) { throw 'Backup archive is empty.' }
    } finally {
        $zip.Dispose()
    }

    $testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("MetricHitRestoreTest-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $success = $false
    try {
        Expand-Archive -LiteralPath $archive.FullName -DestinationPath $testRoot -Force
        $snapshotRoot = Join-Path $testRoot ([System.IO.Path]::GetFileNameWithoutExtension($archive.Name))
        $restoredDatabase = Join-Path $snapshotRoot 'data\database\metrichit.db'
        $restoredContext = Join-Path $snapshotRoot 'knowledge\approved\current-context.md'
        $restoredAgents = Join-Path $snapshotRoot 'AGENTS.md'
        if (-not (Test-Path -LiteralPath $restoredDatabase -PathType Leaf)) { throw 'Restored SQLite database is missing.' }
        if (-not (Test-Path -LiteralPath $restoredContext -PathType Leaf)) { throw 'Restored current-context.md is missing.' }
        if (-not (Test-Path -LiteralPath $restoredAgents -PathType Leaf)) { throw 'Restored AGENTS.md is missing.' }

        & node (Join-Path $snapshotRoot 'scripts\check-memory.mjs') $restoredDatabase
        if ($LASTEXITCODE -ne 0) { throw 'Restored database integrity or migration check failed.' }
        $success = $true
    } finally {
        if ($success -and (Test-Path -LiteralPath $testRoot)) {
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }

    Write-Output "Restore test passed: $($archive.Name)"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
