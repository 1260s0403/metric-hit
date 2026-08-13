[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Copy-SafeTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $blockedDirectories = @('.git', '.codex', 'node_modules', 'logs', 'secrets', 'temp', 'tmp')
    $blockedFilePatterns = @('.env', '.env.*', '*.log', '*.tmp', '*.temp', 'auth.json', '*auth*.json', '*secret*')

    Get-ChildItem -LiteralPath $Source -Recurse -Force | ForEach-Object {
        $relativePath = $_.FullName.Substring($Source.Length).TrimStart('\', '/')
        $segments = $relativePath -split '[\\/]'
        if ($segments | Where-Object { $blockedDirectories -contains $_ }) { return }
        if (-not $_.PSIsContainer) {
            foreach ($pattern in $blockedFilePatterns) {
                if ($_.Name -like $pattern) { return }
            }
        }

        $targetPath = Join-Path $Destination $relativePath
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $targetPath -Force
        }
    }
}

try {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $databasePath = Join-Path $repoRoot 'data\database\metrichit.db'
    $backupRoot = Join-Path (Split-Path -Parent $repoRoot) 'external-backups'
    $timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $backupId = "MetricHit-backup-$timestamp"
    $stagingPath = Join-Path $backupRoot "$backupId.staging"
    $archivePath = Join-Path $backupRoot "$backupId.zip"
    $checksumPath = "$archivePath.sha256"

    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
        throw "Database not found: $databasePath"
    }
    if (Test-Path -LiteralPath $archivePath) {
        throw "Refusing to overwrite existing archive: $archivePath"
    }

    & node (Join-Path $repoRoot 'scripts\check-memory.mjs')
    if ($LASTEXITCODE -ne 0) { throw 'check-memory failed before backup.' }

    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
    try {
        $snapshotRoot = Join-Path $stagingPath $backupId
        New-Item -ItemType Directory -Path $snapshotRoot -Force | Out-Null

        $databaseDestination = Join-Path $snapshotRoot 'data\database\metrichit.db'
        & node (Join-Path $repoRoot 'scripts\sqlite-backup.mjs') $databasePath $databaseDestination
        if ($LASTEXITCODE -ne 0) { throw 'SQLite online backup failed.' }

        foreach ($directory in @('knowledge', 'documents', 'scripts', 'data\database\migrations')) {
            $sourcePath = Join-Path $repoRoot $directory
            if (Test-Path -LiteralPath $sourcePath -PathType Container) {
                Copy-SafeTree -Source $sourcePath -Destination (Join-Path $snapshotRoot $directory)
            }
        }
        foreach ($file in @('AGENTS.md', 'README.md', 'package.json')) {
            $sourcePath = Join-Path $repoRoot $file
            if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
                Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $snapshotRoot $file) -Force
            }
        }

        Compress-Archive -LiteralPath $snapshotRoot -DestinationPath $archivePath -CompressionLevel Optimal -ErrorAction Stop
    } finally {
        if (Test-Path -LiteralPath $stagingPath) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force
        }
    }

    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $checksumPath -Value "$hash  $(Split-Path -Leaf $archivePath)" -Encoding ascii -NoNewline

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        if ($zip.Entries.Count -eq 0) { throw 'Created ZIP archive is empty.' }
    } finally {
        $zip.Dispose()
    }
    $recordedHash = (Get-Content -LiteralPath $checksumPath -Raw).Trim().Split(' ')[0].ToLowerInvariant()
    if ($hash -ne $recordedHash) { throw 'SHA-256 verification failed.' }

    $cutoff = (Get-Date).ToUniversalTime().AddDays(-14)
    Get-ChildItem -LiteralPath $backupRoot -File -Filter 'MetricHit-backup-*.zip*' | Where-Object {
        $_.LastWriteTimeUtc -lt $cutoff -and ($_.Name -like 'MetricHit-backup-*.zip' -or $_.Name -like 'MetricHit-backup-*.zip.sha256')
    } | Remove-Item -Force

    Write-Output "Backup created: $archivePath"
    Write-Output "SHA-256: $hash"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
