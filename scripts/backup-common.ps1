Set-StrictMode -Version Latest

function Get-BackupSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-BackupPathProhibited {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = $RelativePath.Replace('\', '/').TrimStart('/')
    $segments = $normalized -split '/'
    $name = if ($segments.Count -gt 0) { $segments[-1] } else { $normalized }
    $blockedDirectories = @('.git', '.codex', 'node_modules', 'logs', 'secrets', 'temp', 'tmp', 'staging')
    foreach ($segment in $segments) {
        if ($blockedDirectories -contains $segment) {
            if ($segment -eq 'logs' -and $name -eq '.gitkeep') { continue }
            return $true
        }
        if ($segment -like '*.staging') { return $true }
    }

    if (($segments -contains 'backups') -and $name -ne '.gitkeep') { return $true }
    $blockedFilePatterns = @(
        '.env', '.env.*',
        'auth.json', '*auth*.json',
        '*token*', '*credential*', '*password*', '*secret*',
        '*.key', '*.pem', '*.p12', '*.pfx', '*.jks', '*.keystore',
        'id_rsa*', 'id_ed25519*',
        '*.log', '*.log.*', '*.tmp', '*.temp', '*.bak', '*.cache'
    )
    foreach ($pattern in $blockedFilePatterns) {
        if ($name -like $pattern) { return $true }
    }
    return $false
}

function Copy-BackupTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [switch]$FailOnProhibited
    )

    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\', '/')
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null

    Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force | ForEach-Object {
        $relativePath = $_.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
        if (Test-BackupPathProhibited -RelativePath $relativePath) {
            if ($FailOnProhibited) { throw "Prohibited path in required backup tree: $relativePath" }
            return
        }
        if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not allowed in backup sources: $($_.FullName)"
        }

        $targetPath = Join-Path $Destination $relativePath
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $targetPath
        }
    }
}

function Get-BackupFileInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$PathPrefix = ''
    )

    $rootPath = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\', '/')
    $items = @()
    Get-ChildItem -LiteralPath $rootPath -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        $relativePath = $_.FullName.Substring($rootPath.Length).TrimStart('\', '/').Replace('\', '/')
        if ($PathPrefix) { $relativePath = "$($PathPrefix.TrimEnd('/'))/$relativePath" }
        $items += [ordered]@{
            path = $relativePath
            size = [long]$_.Length
            sha256 = Get-BackupSha256 -Path $_.FullName
        }
    }
    return @($items)
}

function Test-BackupBytesContainSecret {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    if ($Bytes.Length -eq 0) { return $false }
    $patterns = @(
        '-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
        '\bAKIA[0-9A-Z]{16}\b',
        '\bgh[pousr]_[A-Za-z0-9]{20,}\b',
        '\bsk-[A-Za-z0-9_-]{20,}\b',
        '\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
        '(?im)^\s*(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|pwd)\s*[:=]\s*["'']?[^\s"'']{8,}'
    )
    $encodings = @(
        [Text.Encoding]::UTF8,
        [Text.Encoding]::Unicode,
        [Text.Encoding]::BigEndianUnicode
    )
    foreach ($encoding in $encodings) {
        $content = $encoding.GetString($Bytes).TrimStart([char]0xFEFF)
        foreach ($pattern in $patterns) {
            if ($content -match $pattern) { return $true }
        }
    }
    return $false
}

function Test-BackupFileContainsSecret {
    param([Parameter(Mandatory = $true)][string]$Path)

    $bytes = [IO.File]::ReadAllBytes((Get-Item -LiteralPath $Path -ErrorAction Stop).FullName)
    return Test-BackupBytesOrArchiveContainSecret -Bytes $bytes -Label $Path
}

function Test-BackupBytesOrArchiveContainSecret {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [int]$Depth = 0
    )

    if (Test-BackupBytesContainSecret -Bytes $Bytes) { return $true }

    if ($Bytes.Length -ge 4 -and $Bytes[0] -eq 0x50 -and $Bytes[1] -eq 0x4B) {
        if ($Depth -ge 4) { throw "Nested ZIP depth limit exceeded while scanning: $Label" }
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $stream = [IO.MemoryStream]::new($Bytes, $false)
        try {
            $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read, $false)
            try {
                $totalExpandedBytes = [long]0
                foreach ($entry in $archive.Entries) {
                    if ($entry.Length -eq 0) { continue }
                    if ($entry.Length -gt 256MB) { throw "ZIP entry is too large for safe secret scanning: $Label::$($entry.FullName)" }
                    $totalExpandedBytes += [long]$entry.Length
                    if ($totalExpandedBytes -gt 512MB) { throw "ZIP expanded-size limit exceeded while scanning: $Label" }
                    $entryStream = $entry.Open()
                    try {
                        $memory = [IO.MemoryStream]::new()
                        try {
                            $entryStream.CopyTo($memory)
                            if (Test-BackupBytesOrArchiveContainSecret -Bytes $memory.ToArray() -Label "$Label::$($entry.FullName)" -Depth ($Depth + 1)) { return $true }
                        } finally { $memory.Dispose() }
                    } finally { $entryStream.Dispose() }
                }
            } finally { $archive.Dispose() }
        } catch {
            throw "Unable to inspect ZIP-compatible content for secrets: $Label. $($_.Exception.Message)"
        } finally { $stream.Dispose() }
    }
    return $false
}

function Assert-BackupTreeHasNoSecretContent {
    param([Parameter(Mandatory = $true)][string]$Root)

    Get-ChildItem -LiteralPath $Root -Recurse -File -Force | ForEach-Object {
        if (Test-BackupFileContainsSecret -Path $_.FullName) {
            $rootPath = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\', '/')
            $relativePath = $_.FullName.Substring($rootPath.Length).TrimStart('\', '/')
            throw "Potential secret content in backup source: $relativePath"
        }
    }
}

function Assert-GitObjectsHaveNoSecretContent {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$RefObjectIds,
        [Parameter(Mandatory = $true)][string]$TemporaryDirectory
    )

    if ($RefObjectIds.Count -eq 0) { return }
    New-Item -ItemType Directory -Path $TemporaryDirectory -Force | Out-Null
    $objects = @(& git -C $RepositoryRoot rev-list --objects $RefObjectIds)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate reachable Git objects for secret scan.' }
    $objectIds = @($objects | ForEach-Object { ($_ -split '\s+', 2)[0] } | Sort-Object -Unique)
    foreach ($objectId in $objectIds) {
        $objectType = (& git -C $RepositoryRoot cat-file -t $objectId).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to inspect Git object type: $objectId" }
        if ($objectType -ne 'blob') { continue }
        $blobPath = Join-Path $TemporaryDirectory "$objectId.blob"
        $process = Start-Process -FilePath 'git.exe' -ArgumentList @('-C', $RepositoryRoot, 'cat-file', 'blob', $objectId) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $blobPath
        if ($process.ExitCode -ne 0) { throw "Unable to materialize Git blob for secret scan: $objectId" }
        try {
            if (Test-BackupFileContainsSecret -Path $blobPath) {
                throw "Potential secret content exists in reachable Git blob: $objectId"
            }
        } finally {
            Remove-Item -LiteralPath $blobPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-BackupInventoriesEqual {
    param(
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $expectedJson = ConvertTo-Json -InputObject @($Expected) -Depth 5 -Compress
    $actualJson = ConvertTo-Json -InputObject @($Actual) -Depth 5 -Compress
    if ($expectedJson -cne $actualJson) { throw "$Label inventory mismatch." }
}

function Assert-BackupZipEntrySafe {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][string]$SnapshotRootName
    )

    $name = $Entry.FullName.Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith('/') -or $name -match '^[A-Za-z]:/') {
        throw "Unsafe absolute ZIP entry: $name"
    }
    if (($name -split '/') -contains '..') { throw "Unsafe traversal ZIP entry: $name" }
    $mode = ($Entry.ExternalAttributes -shr 16) -band 0xF000
    if ($mode -eq 0xA000) { throw "Symbolic links are not allowed in backup ZIP: $name" }

    $rootPrefix = "$SnapshotRootName/"
    if ($name -ne $SnapshotRootName -and -not $name.StartsWith($rootPrefix, [StringComparison]::Ordinal)) {
        throw "ZIP entry is outside the declared snapshot root: $name"
    }
    $relativePath = if ($name.StartsWith($rootPrefix, [StringComparison]::Ordinal)) {
        $name.Substring($rootPrefix.Length)
    } else { '' }
    if ($relativePath -and (Test-BackupPathProhibited -RelativePath $relativePath)) {
        throw "Prohibited path found in backup ZIP: $relativePath"
    }
}
