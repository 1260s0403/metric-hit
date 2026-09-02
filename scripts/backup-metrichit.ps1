[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'backup-common.ps1')

try {
    $backupStopwatch = [Diagnostics.Stopwatch]::StartNew()
    $repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
    $databasePath = Join-Path $repoRoot 'data\database\metrichit.db'
    $backupRoot = Join-Path (Split-Path -Parent $repoRoot) 'external-backups'
    $timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $backupId = "MetricHit-backup-$timestamp"
    $setPath = Join-Path $backupRoot $backupId
    $stagingPath = Join-Path $backupRoot "$backupId.staging"
    $snapshotRootName = "$backupId-workspace"
    $snapshotRoot = Join-Path $stagingPath $snapshotRootName
    $archiveName = "$backupId-workspace.zip"
    $bundleName = "$backupId-git.bundle"
    $manifestName = "$backupId-manifest.json"
    $archivePath = Join-Path $stagingPath $archiveName
    $bundlePath = Join-Path $stagingPath $bundleName
    $manifestPath = Join-Path $stagingPath $manifestName
    $requiredImportCommit = '966f9518046550d13b81c3ca503c7c8e338c47dc'

    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) { throw "Database not found: $databasePath" }
    if (Test-Path -LiteralPath $setPath) { throw "Refusing to overwrite existing backup set: $setPath" }
    if (Test-Path -LiteralPath $stagingPath) { throw "Refusing to overwrite existing backup staging path: $stagingPath" }

    & node (Join-Path $repoRoot 'scripts\check-memory.mjs')
    if ($LASTEXITCODE -ne 0) { throw 'check-memory failed before backup.' }

    $gitRoot = (& git -C $repoRoot rev-parse --show-toplevel 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $gitRoot) { throw 'The workspace is not a readable Git repository.' }
    if ((Resolve-Path -LiteralPath $gitRoot).Path -ne $repoRoot) { throw "Unexpected Git repository root: $gitRoot" }
    & git -C $repoRoot cat-file -e "${requiredImportCommit}^{commit}"
    if ($LASTEXITCODE -ne 0) { throw "Required import commit is missing: $requiredImportCommit" }
    & git -C $repoRoot fsck --full --no-dangling
    if ($LASTEXITCODE -ne 0) { throw 'Git repository integrity check failed.' }

    $repositoryHeadBefore = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve repository HEAD before backup.' }
    $symbolicHead = (& git -C $repoRoot symbolic-ref -q HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $symbolicHead) { throw 'Detached HEAD is not allowed for a complete backup set.' }
    $repositoryRefsBefore = @(& git -C $repoRoot for-each-ref --format='%(refname) %(objectname)' | Sort-Object)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate Git refs before backup.' }
    $repositoryRefNames = @($repositoryRefsBefore | ForEach-Object { ($_ -split '\s+', 2)[0] })
    if ($repositoryRefNames.Count -eq 0) { throw 'No canonical Git refs are available for backup.' }
    $refObjectIds = @($repositoryRefsBefore | ForEach-Object { ($_ -split '\s+', 2)[1] } | Sort-Object -Unique)
    $headRefLine = @($repositoryRefsBefore | Where-Object { $_.StartsWith("$symbolicHead ", [StringComparison]::Ordinal) })
    if ($headRefLine.Count -ne 1 -or ($headRefLine[0] -split '\s+', 2)[1] -cne $repositoryHeadBefore) {
        throw 'Symbolic HEAD does not match its captured Git ref.'
    }

    $historicalPaths = & git -C $repoRoot log --name-only --format= $refObjectIds
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect paths reachable from captured Git refs.' }
    foreach ($historicalPath in ($historicalPaths | Where-Object { $_ })) {
        if (Test-BackupPathProhibited -RelativePath $historicalPath) {
            throw "Prohibited path exists in captured Git history and would enter the bundle: $historicalPath"
        }
    }

    function Get-RequiredSourceInventory {
        $inventory = @()
        foreach ($directory in @('knowledge', 'documents', 'scripts', 'tests', 'data\database\migrations', 'data\project-migrations', 'work')) {
            $sourcePath = Join-Path $repoRoot $directory
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw "Required source directory is missing: $directory" }
            $inventory += Get-BackupFileInventory -Root $sourcePath -PathPrefix $directory.Replace('\', '/')
        }
        foreach ($file in @('AGENTS.md', 'README.md', '.gitignore', '.gitattributes', 'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock')) {
            $sourcePath = Join-Path $repoRoot $file
            if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
                $item = Get-Item -LiteralPath $sourcePath
                $inventory += [ordered]@{ path = $file; size = [long]$item.Length; sha256 = Get-BackupSha256 -Path $sourcePath }
            }
        }
        return @($inventory | Sort-Object { $_['path'] })
    }

    $globalSourceBefore = Get-RequiredSourceInventory

    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stagingPath | Out-Null
    $completed = $false
    try {
        New-Item -ItemType Directory -Path $snapshotRoot | Out-Null

        $gitSecretScan = Assert-GitObjectsHaveNoSecretContent -RepositoryRoot $repoRoot -RefObjectIds $refObjectIds -TemporaryDirectory (Join-Path $stagingPath 'git-secret-scan')
        Write-Output "Git secret scan passed: $($gitSecretScan.objectCount) objects; $($gitSecretScan.blobCount) blobs; $($gitSecretScan.blobBytes) bytes; $($gitSecretScan.elapsedMilliseconds) ms."

        $databaseSourceShaBefore = Get-BackupSha256 -Path $databasePath
        $databaseDestination = Join-Path $snapshotRoot 'data\database\metrichit.db'
        & node (Join-Path $repoRoot 'scripts\sqlite-backup.mjs') $databasePath $databaseDestination
        if ($LASTEXITCODE -ne 0) { throw 'SQLite online backup failed.' }
        $databaseSourceShaAfter = Get-BackupSha256 -Path $databasePath
        if ($databaseSourceShaBefore -cne $databaseSourceShaAfter) { throw 'Central SQLite source changed during online backup.' }
        & node (Join-Path $repoRoot 'scripts\check-memory.mjs') $databaseDestination
        if ($LASTEXITCODE -ne 0) { throw 'Central SQLite backup integrity or migration validation failed.' }

        $projectStorageSource = Join-Path $repoRoot 'data\projects'
        $projectStorageDestination = Join-Path $snapshotRoot 'data\projects'
        $projectInventoryJson = (& node (Join-Path $repoRoot 'scripts\project-storage-snapshot.mjs') snapshot $projectStorageSource $projectStorageDestination | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $projectInventoryJson) { throw 'Project storage online backup failed.' }
        $projectStorageInventory = @(ConvertFrom-BackupJsonArray -Json $projectInventoryJson)

        $requiredDirectories = @('knowledge', 'documents', 'scripts', 'tests', 'data\database\migrations', 'data\project-migrations')
        foreach ($directory in $requiredDirectories) {
            $sourcePath = Join-Path $repoRoot $directory
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw "Required source directory is missing: $directory" }
            $sourceBefore = Get-BackupFileInventory -Root $sourcePath -PathPrefix $directory.Replace('\', '/')
            Copy-BackupTree -Source $sourcePath -Destination (Join-Path $snapshotRoot $directory) -FailOnProhibited
            $sourceAfter = Get-BackupFileInventory -Root $sourcePath -PathPrefix $directory.Replace('\', '/')
            $snapshotInventory = Get-BackupFileInventory -Root (Join-Path $snapshotRoot $directory) -PathPrefix $directory.Replace('\', '/')
            Assert-BackupInventoriesEqual -Expected $sourceBefore -Actual $sourceAfter -Label "$directory source tree changed during backup"
            Assert-BackupInventoriesEqual -Expected $sourceAfter -Actual $snapshotInventory -Label "$directory copied tree"
        }

        $workSource = Join-Path $repoRoot 'work'
        $workBefore = Get-BackupFileInventory -Root $workSource -PathPrefix 'work'
        Copy-BackupTree -Source $workSource -Destination (Join-Path $snapshotRoot 'work')
        $workAfter = Get-BackupFileInventory -Root $workSource -PathPrefix 'work'
        $workSnapshot = Get-BackupFileInventory -Root (Join-Path $snapshotRoot 'work') -PathPrefix 'work'
        Assert-BackupInventoriesEqual -Expected $workBefore -Actual $workAfter -Label 'Source work tree changed during backup'
        Assert-BackupInventoriesEqual -Expected $workAfter -Actual $workSnapshot -Label 'Copied work tree'

        $requiredRootFiles = @('AGENTS.md', 'README.md', '.gitignore', '.gitattributes')
        $optionalRootFiles = @('package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock')
        foreach ($file in $requiredRootFiles) {
            $sourcePath = Join-Path $repoRoot $file
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Required root file is missing: $file" }
            $sourceHashBefore = Get-BackupSha256 -Path $sourcePath
            Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $snapshotRoot $file)
            $sourceHashAfter = Get-BackupSha256 -Path $sourcePath
            $copiedHash = Get-BackupSha256 -Path (Join-Path $snapshotRoot $file)
            if ($sourceHashBefore -cne $sourceHashAfter -or $sourceHashAfter -cne $copiedHash) { throw "Root file changed or copied incorrectly: $file" }
        }
        foreach ($file in $optionalRootFiles) {
            $sourcePath = Join-Path $repoRoot $file
            if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
                $sourceHashBefore = Get-BackupSha256 -Path $sourcePath
                Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $snapshotRoot $file)
                $sourceHashAfter = Get-BackupSha256 -Path $sourcePath
                $copiedHash = Get-BackupSha256 -Path (Join-Path $snapshotRoot $file)
                if ($sourceHashBefore -cne $sourceHashAfter -or $sourceHashAfter -cne $copiedHash) { throw "Optional root file changed or copied incorrectly: $file" }
            }
        }

        Assert-BackupTreeHasNoSecretContent -Root $snapshotRoot

        $globalSourceBeforeArchive = Get-RequiredSourceInventory
        Assert-BackupInventoriesEqual -Expected $globalSourceBefore -Actual $globalSourceBeforeArchive -Label 'Global backup source before archive creation'

        $archiveAttempts = Invoke-BackupArchiveWithRetry -SourcePath $snapshotRoot -ArchivePath $archivePath
        Write-Output "Workspace ZIP created after $archiveAttempts attempt(s)."

        $globalSourceAfterArchive = Get-RequiredSourceInventory
        Assert-BackupInventoriesEqual -Expected $globalSourceBefore -Actual $globalSourceAfterArchive -Label 'Global backup source after archive creation'

        & git -C $repoRoot bundle create $bundlePath HEAD @repositoryRefNames
        if ($LASTEXITCODE -ne 0) { throw 'Git bundle creation failed.' }
        & git -C $repoRoot bundle verify $bundlePath
        if ($LASTEXITCODE -ne 0) { throw 'Git bundle verification failed after creation.' }

        $repositoryHeadAfter = (& git -C $repoRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve repository HEAD after bundle creation.' }
        $symbolicHeadAfter = (& git -C $repoRoot symbolic-ref -q HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or $symbolicHeadAfter -cne $symbolicHead) { throw 'Symbolic HEAD changed during bundle creation.' }
        $repositoryRefsAfter = @(& git -C $repoRoot for-each-ref --format='%(refname) %(objectname)' | Sort-Object)
        if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate Git refs after bundle creation.' }
        if ($repositoryHeadBefore -cne $repositoryHeadAfter -or (Compare-Object $repositoryRefsBefore $repositoryRefsAfter)) {
            throw 'Git HEAD or refs changed during bundle creation.'
        }
        $bundleHeads = @(& git -C $repoRoot bundle list-heads $bundlePath | Where-Object { $_ -notmatch '\sHEAD$' } | ForEach-Object {
            $parts = $_ -split '\s+', 2
            "$($parts[1]) $($parts[0])"
        } | Sort-Object)
        if ($LASTEXITCODE -ne 0) { throw 'Unable to list Git bundle heads.' }
        if (Compare-Object $repositoryRefsBefore $bundleHeads) { throw 'Git bundle refs do not match repository refs.' }
        $requiredCommits = @($requiredImportCommit, $repositoryHeadBefore | Select-Object -Unique)
        $workBytes = [long]0
        foreach ($workItem in @($workSnapshot)) { $workBytes += [long]$workItem['size'] }
        $manifest = [ordered]@{
            formatVersion = 4
            backupId = $backupId
            createdAtUtc = [DateTime]::UtcNow.ToString('o')
            snapshotRoot = $snapshotRootName
            repositoryHead = $repositoryHeadBefore
            symbolicHead = $symbolicHead
            repositoryRefs = @($repositoryRefsBefore)
            requiredCommits = $requiredCommits
            components = @(
                [ordered]@{
                    role = 'workspace-archive'
                    name = $archiveName
                    size = [long](Get-Item -LiteralPath $archivePath).Length
                    sha256 = Get-BackupSha256 -Path $archivePath
                },
                [ordered]@{
                    role = 'git-bundle'
                    name = $bundleName
                    size = [long](Get-Item -LiteralPath $bundlePath).Length
                    sha256 = Get-BackupSha256 -Path $bundlePath
                }
            )
            centralDatabase = [ordered]@{
                path = 'data/database/metrichit.db'
                size = [long](Get-Item -LiteralPath $databaseDestination).Length
                sha256 = Get-BackupSha256 -Path $databaseDestination
                sourceSha256 = $databaseSourceShaBefore
                integrity = 'ok'
                method = 'sqlite-online-backup'
            }
            work = [ordered]@{
                fileCount = @($workSnapshot).Count
                totalBytes = $workBytes
                inventory = @($workSnapshot)
            }
            projectStorages = [ordered]@{
                root = 'data/projects'
                count = @($projectStorageInventory).Count
                inventory = @($projectStorageInventory)
                method = 'sqlite-online-backup'
            }
            performance = [ordered]@{
                gitSecretScanMilliseconds = [long]$gitSecretScan.elapsedMilliseconds
                gitReachableObjectCount = [int]$gitSecretScan.objectCount
                gitReachableBlobCount = [int]$gitSecretScan.blobCount
                gitReachableBlobBytes = [long]$gitSecretScan.blobBytes
            }
            requiredWorkFiles = @(
                'work/landing/index.html',
                'work/articles/research/MANIFEST.md',
                'work/social/telegram/published/06-who-we-are.md',
                'work/archive/migration-packages/2026-08-13/metrichit-landing-migration-2026-08-13.zip',
                'work/archive/migration-packages/2026-08-13/metrichit-articles-migration-2026-08-13.zip',
                'work/archive/migration-packages/2026-08-13/metrichit-social-migration-2026-08-13.zip'
            )
            exclusions = @('.git as files', '.codex', 'node_modules', 'logs', 'secrets', 'temp', 'tmp', 'staging', 'backups', '.env and .env.*', 'auth files', 'tokens', 'credentials', 'passwords', 'private keys')
        }
        $manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

        $repositoryHeadFinal = (& git -C $repoRoot rev-parse HEAD).Trim()
        $symbolicHeadFinal = (& git -C $repoRoot symbolic-ref -q HEAD).Trim()
        $repositoryRefsFinal = @(& git -C $repoRoot for-each-ref --format='%(refname) %(objectname)' | Sort-Object)
        if ($LASTEXITCODE -ne 0 -or $symbolicHeadFinal -cne $symbolicHead -or $repositoryHeadFinal -cne $repositoryHeadBefore -or (Compare-Object $repositoryRefsBefore $repositoryRefsFinal)) {
            throw 'Git HEAD or refs changed before backup set promotion.'
        }
        $globalSourceFinal = Get-RequiredSourceInventory
        Assert-BackupInventoriesEqual -Expected $globalSourceBefore -Actual $globalSourceFinal -Label 'Global backup source before set promotion'

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            if ($zip.Entries.Count -eq 0) { throw 'Created ZIP archive is empty.' }
            foreach ($entry in $zip.Entries) {
                Assert-BackupZipEntrySafe -Entry $entry -SnapshotRootName $snapshotRootName
            }
        } finally { $zip.Dispose() }

        Remove-Item -LiteralPath $snapshotRoot -Recurse -Force
        Move-Item -LiteralPath $stagingPath -Destination $setPath
        $completed = $true
    } finally {
        if (-not $completed -and (Test-Path -LiteralPath $stagingPath)) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force
        }
    }

    $cutoff = (Get-Date).ToUniversalTime().AddDays(-14)
    Get-ChildItem -LiteralPath $backupRoot -Directory | Where-Object {
        $_.Name -match '^MetricHit-backup-\d{8}T\d{6}Z$' -and $_.LastWriteTimeUtc -lt $cutoff
    } | Remove-Item -Recurse -Force

    $legacyFiles = Get-ChildItem -LiteralPath $backupRoot -File | Where-Object {
        $_.Name -match '^(MetricHit-backup-\d{8}T\d{6}Z)\.zip(?:\.sha256)?$'
    }
    $legacyFiles | Group-Object { [regex]::Match($_.Name, '^(MetricHit-backup-\d{8}T\d{6}Z)').Groups[1].Value } | Where-Object {
        ($_.Group | Measure-Object LastWriteTimeUtc -Maximum).Maximum -lt $cutoff
    } | ForEach-Object { $_.Group | Remove-Item -Force }

    $finalArchive = Join-Path $setPath $archiveName
    $finalBundle = Join-Path $setPath $bundleName
    $finalManifest = Join-Path $setPath $manifestName
    Write-Output "Backup set created: $setPath"
    Write-Output "Workspace ZIP: $archiveName; bytes: $((Get-Item $finalArchive).Length); SHA-256: $(Get-BackupSha256 $finalArchive)"
    Write-Output "Git bundle: $bundleName; bytes: $((Get-Item $finalBundle).Length); SHA-256: $(Get-BackupSha256 $finalBundle)"
    Write-Output "Manifest: $manifestName; bytes: $((Get-Item $finalManifest).Length); SHA-256: $(Get-BackupSha256 $finalManifest)"
    Write-Output "Work files: $(@($workSnapshot).Count); bytes: $workBytes"
    Write-Output "Project storages: $(@($projectStorageInventory).Count); online SQLite snapshots verified"
    $backupStopwatch.Stop()
    Write-Output "Total backup time: $([long]$backupStopwatch.ElapsedMilliseconds) ms"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
