[CmdletBinding()]
param(
    [string]$BackupSetPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'backup-common.ps1')

try {
    $repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
    $backupRoot = Join-Path (Split-Path -Parent $repoRoot) 'external-backups'
    if ($BackupSetPath) {
        $backupSet = Get-Item -LiteralPath $BackupSetPath -ErrorAction Stop
    } else {
        $backupSet = Get-ChildItem -LiteralPath $backupRoot -Directory | Where-Object {
            $_.Name -match '^MetricHit-backup-\d{8}T\d{6}Z$'
        } | Sort-Object Name -Descending | Select-Object -First 1
    }
    if ($null -eq $backupSet -or -not $backupSet.PSIsContainer) { throw 'No complete MetricHit backup set found.' }
    $backupId = $backupSet.Name
    if ($backupId -notmatch '^MetricHit-backup-\d{8}T\d{6}Z$') { throw "Invalid backup set name: $backupId" }

    $manifestPath = Join-Path $backupSet.FullName "$backupId-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Manifest not found: $manifestPath" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.formatVersion -ne 2) { throw "Unsupported backup format version: $($manifest.formatVersion)" }
    if ($manifest.backupId -cne $backupId) { throw 'Manifest backupId does not match the set directory.' }
    if ($manifest.snapshotRoot -notmatch '^MetricHit-backup-\d{8}T\d{6}Z-workspace$') { throw 'Unsafe snapshotRoot in manifest.' }
    if (@($manifest.components).Count -ne 2) { throw 'Manifest must describe exactly two backup components.' }

    $components = @{}
    foreach ($component in $manifest.components) {
        if ($component.name -notmatch '^[A-Za-z0-9._-]+$') { throw "Unsafe component name: $($component.name)" }
        $componentPath = Join-Path $backupSet.FullName $component.name
        if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) { throw "Backup component is missing: $($component.name)" }
        $actualSize = [long](Get-Item -LiteralPath $componentPath).Length
        if ($actualSize -ne [long]$component.size) { throw "Size mismatch for component: $($component.name)" }
        $actualHash = Get-BackupSha256 -Path $componentPath
        if ($actualHash -cne [string]$component.sha256) { throw "SHA-256 mismatch for component: $($component.name)" }
        if ($components.ContainsKey($component.role)) { throw "Duplicate component role: $($component.role)" }
        $components[$component.role] = $componentPath
    }
    if (-not $components.ContainsKey('workspace-archive') -or -not $components.ContainsKey('git-bundle')) {
        throw 'Manifest is missing the workspace archive or Git bundle.'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($components['workspace-archive'])
    try {
        if ($zip.Entries.Count -eq 0) { throw 'Backup ZIP is empty.' }
        foreach ($entry in $zip.Entries) {
            Assert-BackupZipEntrySafe -Entry $entry -SnapshotRootName $manifest.snapshotRoot
        }
    } finally { $zip.Dispose() }

    $workspaceHeadBefore = $null
    $workspaceStatusBefore = $null
    if (Test-Path -LiteralPath (Join-Path $repoRoot '.git')) {
        $workspaceHeadBefore = (& git -C $repoRoot rev-parse HEAD).Trim()
        $workspaceStatusBefore = (& git -C $repoRoot status --porcelain=v1 -uall) -join "`n"
    }

    $testRoot = Join-Path ([IO.Path]::GetTempPath()) ("MetricHitRestoreTest-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    try {
        Expand-Archive -LiteralPath $components['workspace-archive'] -DestinationPath $testRoot
        $snapshotRoot = Join-Path $testRoot $manifest.snapshotRoot
        if (-not (Test-Path -LiteralPath $snapshotRoot -PathType Container)) { throw 'Restored snapshot root is missing.' }

        Get-ChildItem -LiteralPath $snapshotRoot -Recurse -Force | ForEach-Object {
            $relativePath = $_.FullName.Substring($snapshotRoot.Length).TrimStart('\', '/')
            if ($relativePath -and (Test-BackupPathProhibited -RelativePath $relativePath)) {
                throw "Prohibited path restored from ZIP: $relativePath"
            }
        }
        if (Test-Path -LiteralPath (Join-Path $snapshotRoot '.git')) { throw '.git must not be stored as ordinary ZIP content.' }
        Assert-BackupTreeHasNoSecretContent -Root $snapshotRoot

        foreach ($requiredPath in @(
            'knowledge', 'documents', 'scripts', 'tests', 'data\database\migrations', 'work',
            'AGENTS.md', 'README.md', '.gitignore', '.gitattributes'
        )) {
            if (-not (Test-Path -LiteralPath (Join-Path $snapshotRoot $requiredPath))) {
                throw "Required restored path is missing: $requiredPath"
            }
        }

        $restoredDatabase = Join-Path $snapshotRoot 'data\database\metrichit.db'
        & node (Join-Path $repoRoot 'scripts\check-memory.mjs') $restoredDatabase
        if ($LASTEXITCODE -ne 0) { throw 'Restored SQLite integrity or migration validation failed.' }

        $restoredWork = Get-BackupFileInventory -Root (Join-Path $snapshotRoot 'work') -PathPrefix 'work'
        Assert-BackupInventoriesEqual -Expected @($manifest.work.inventory) -Actual $restoredWork -Label 'Restored work tree'
        if (@($restoredWork).Count -ne [int]$manifest.work.fileCount) { throw 'Restored work file count mismatch.' }
        $restoredWorkBytes = [long]0
        foreach ($workItem in @($restoredWork)) { $restoredWorkBytes += [long]$workItem['size'] }
        if ($restoredWorkBytes -ne [long]$manifest.work.totalBytes) { throw 'Restored work byte count mismatch.' }
        foreach ($requiredWorkFile in $manifest.requiredWorkFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $snapshotRoot $requiredWorkFile.Replace('/', '\')) -PathType Leaf)) {
                throw "Required imported work file is missing: $requiredWorkFile"
            }
        }

        $verifyRepo = Join-Path $testRoot 'bundle-verify.git'
        & git init --bare $verifyRepo | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to initialize isolated bundle verification repository.' }
        & git -C $verifyRepo bundle verify $components['git-bundle']
        if ($LASTEXITCODE -ne 0) { throw 'git bundle verify failed.' }
        $bundleHeads = @(& git -C $verifyRepo bundle list-heads $components['git-bundle'] | Where-Object { $_ -notmatch '\sHEAD$' } | ForEach-Object {
            $parts = $_ -split '\s+', 2
            "$($parts[1]) $($parts[0])"
        } | Sort-Object)
        if ($LASTEXITCODE -ne 0) { throw 'Unable to list restored Git bundle heads.' }
        if (Compare-Object @($manifest.repositoryRefs) $bundleHeads) { throw 'Git bundle refs do not match the manifest.' }

        $cloneRepo = Join-Path $testRoot 'bundle-clone'
        & git clone --no-local $components['git-bundle'] $cloneRepo | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to clone the Git bundle.' }
        & git -C $cloneRepo fsck --full --no-dangling
        if ($LASTEXITCODE -ne 0) { throw 'Cloned Git repository integrity check failed.' }
        foreach ($commit in $manifest.requiredCommits) {
            & git -C $cloneRepo cat-file -e "${commit}^{commit}"
            if ($LASTEXITCODE -ne 0) { throw "Required commit is missing from cloned bundle: $commit" }
        }
        $cloneHead = (& git -C $cloneRepo rev-parse HEAD).Trim()
        if ($cloneHead -cne [string]$manifest.repositoryHead) { throw 'Cloned repository HEAD does not match the manifest.' }
        $cloneSymbolicHead = (& git -C $cloneRepo symbolic-ref -q HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or $cloneSymbolicHead -cne [string]$manifest.symbolicHead) { throw 'Cloned symbolic HEAD does not match the manifest.' }

        if ($null -ne $workspaceHeadBefore) {
            $workspaceHeadAfter = (& git -C $repoRoot rev-parse HEAD).Trim()
            $workspaceStatusAfter = (& git -C $repoRoot status --porcelain=v1 -uall) -join "`n"
            if ($workspaceHeadAfter -cne $workspaceHeadBefore -or $workspaceStatusAfter -cne $workspaceStatusBefore) {
                throw 'Restore test modified the active workspace.'
            }
        }

        Write-Output "Component SHA-256 checks passed: $(@($manifest.components).Count)"
        Write-Output "SQLite restore validation passed: integrity ok; migrations confirmed"
        Write-Output "Work restore validation passed: $(@($restoredWork).Count) files; $restoredWorkBytes bytes"
        Write-Output "Git bundle verify and isolated clone passed; HEAD: $cloneHead"
        Write-Output "Required commits present: $($manifest.requiredCommits -join ', ')"
    } finally {
        if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
    }

    Write-Output "Restore test passed and temporary directory removed: $backupId"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
