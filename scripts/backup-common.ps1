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

function Test-BackupTransientFileLock {
    param([Parameter(Mandatory = $true)]$ErrorRecord)

    $current = $ErrorRecord.Exception
    while ($null -ne $current) {
        $win32Code = ([int64]$current.HResult -band 0xFFFF)
        if ($current -is [UnauthorizedAccessException] -or $win32Code -in 5, 32, 33) { return $true }
        if ($current.Message -match '(?i)(access (is )?denied|being used by another process|sharing violation|lock violation)') { return $true }
        $current = $current.InnerException
    }
    return $false
}

function Remove-BackupIncompleteArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [int]$MaxAttempts = 3,
        [int]$InitialDelayMilliseconds = 250,
        [scriptblock]$RemoveAction = { param($archive) Remove-Item -LiteralPath $archive -Force -ErrorAction Stop }
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        if (-not (Test-Path -LiteralPath $ArchivePath)) { return }
        try {
            & $RemoveAction $ArchivePath
            if (-not (Test-Path -LiteralPath $ArchivePath)) { return }
            throw "Incomplete ZIP remains after removal: $ArchivePath"
        } catch {
            if (-not (Test-BackupTransientFileLock -ErrorRecord $_) -or $attempt -eq $MaxAttempts) {
                throw "Unable to remove incomplete ZIP after $attempt attempt(s): $ArchivePath. $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds ($InitialDelayMilliseconds * $attempt)
        }
    }
}

function Invoke-BackupArchiveWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [int]$MaxAttempts = 8,
        [int]$InitialDelayMilliseconds = 250,
        [scriptblock]$ArchiveAction = { param($source, $archive) Compress-Archive -LiteralPath $source -DestinationPath $archive -CompressionLevel Optimal -ErrorAction Stop },
        [scriptblock]$ArchiveRemoveAction = { param($archive) Remove-Item -LiteralPath $archive -Force -ErrorAction Stop }
    )

    if ($MaxAttempts -lt 1) { throw 'MaxAttempts must be at least 1.' }
    if ($InitialDelayMilliseconds -lt 0) { throw 'InitialDelayMilliseconds must not be negative.' }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $ArchiveAction $SourcePath $ArchivePath
            if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
                throw "Archive action did not produce ZIP: $ArchivePath"
            }
            return $attempt
        } catch {
            $archiveError = $_
            $isTransient = Test-BackupTransientFileLock -ErrorRecord $_
            try {
                Remove-BackupIncompleteArchive -ArchivePath $ArchivePath -MaxAttempts $MaxAttempts -InitialDelayMilliseconds $InitialDelayMilliseconds -RemoveAction $ArchiveRemoveAction
            } catch {
                throw "Workspace archive attempt $attempt failed: $($archiveError.Exception.Message) Cleanup failed: $($_.Exception.Message)"
            }
            if (-not $isTransient) { throw $archiveError }
            if ($attempt -eq $MaxAttempts) {
                throw "Workspace archive failed after $MaxAttempts attempts due to transient file lock: $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds ($InitialDelayMilliseconds * $attempt)
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
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Bytes)

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
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Bytes,
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

function Read-GitBatchLine {
    param(
        [Parameter(Mandatory = $true)][IO.Stream]$Stream,
        [int]$MaximumBytes = 4096
    )

    $bytes = [Collections.Generic.List[byte]]::new()
    while ($true) {
        $value = $Stream.ReadByte()
        if ($value -lt 0) { throw 'Git batch protocol ended before a complete header was received.' }
        if ($value -eq 10) { break }
        if ($bytes.Count -ge $MaximumBytes) { throw 'Git batch protocol header exceeds the safety limit.' }
        $bytes.Add([byte]$value)
    }
    return [Text.Encoding]::ASCII.GetString($bytes.ToArray()).TrimEnd("`r")
}

function ConvertFrom-BackupJsonArray {
    param([Parameter(Mandatory = $true)][string]$Json)

    $trimmed = $Json.Trim()
    if (-not $trimmed.StartsWith('[') -or -not $trimmed.EndsWith(']')) {
        throw 'Backup JSON inventory must be an array.'
    }
    try {
        # Windows PowerShell 5.1 misreads a top-level [] as a synthetic
        # { value = []; Count = 0 } object. An object envelope preserves zero,
        # one, and many inventory entries consistently across PowerShell versions.
        $envelope = ('{"inventory":' + $trimmed + '}') | ConvertFrom-Json -ErrorAction Stop
        return @($envelope.inventory)
    } catch {
        throw "Invalid backup JSON inventory: $($_.Exception.Message)"
    }
}

function Read-GitBatchBytes {
    param(
        [Parameter(Mandatory = $true)][IO.Stream]$Stream,
        [Parameter(Mandatory = $true)][long]$Length,
        [switch]$Discard
    )

    if ($Length -lt 0) { throw 'Git batch protocol declared a negative object size.' }
    if (-not $Discard -and $Length -gt 512MB) { throw 'Git blob exceeds the 512 MB secret-scan safety limit.' }
    $buffer = New-Object byte[] ([Math]::Min([long]65536, [Math]::Max([long]1, $Length)))
    $memory = if ($Discard) { $null } else { [IO.MemoryStream]::new([int]$Length) }
    try {
        $remaining = $Length
        while ($remaining -gt 0) {
            $requested = [int][Math]::Min([long]$buffer.Length, $remaining)
            $read = $Stream.Read($buffer, 0, $requested)
            if ($read -le 0) { throw 'Git batch protocol ended before the declared object size was received.' }
            if (-not $Discard) { $memory.Write($buffer, 0, $read) }
            $remaining -= $read
        }
        $separator = $Stream.ReadByte()
        if ($separator -ne 10) { throw 'Git batch protocol object is missing its trailing newline.' }
        if ($Discard) { return $null }
        return ,([byte[]]$memory.ToArray())
    } finally {
        if ($null -ne $memory) { $memory.Dispose() }
    }
}

function Assert-GitObjectsHaveNoSecretContent {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$RefObjectIds,
        [Parameter(Mandatory = $true)][string]$TemporaryDirectory
    )

    if ($RefObjectIds.Count -eq 0) {
        return [pscustomobject]@{ objectCount = 0; blobCount = 0; blobBytes = [long]0; elapsedMilliseconds = [long]0 }
    }
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $objects = @(& git -C $RepositoryRoot rev-list --objects $RefObjectIds)
    if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate reachable Git objects for secret scan.' }
    $objectIds = @($objects | ForEach-Object { ($_ -split '\s+', 2)[0] } | Sort-Object -Unique)

    New-Item -ItemType Directory -Path $TemporaryDirectory -Force | Out-Null
    $requestPath = Join-Path $TemporaryDirectory 'objects.request'
    $responsePath = Join-Path $TemporaryDirectory 'objects.batch'
    $errorPath = Join-Path $TemporaryDirectory 'objects.error'
    [IO.File]::WriteAllLines($requestPath, $objectIds, [Text.UTF8Encoding]::new($false))
    $blobCount = 0
    $blobBytes = [long]0
    try {
        $process = Start-Process -FilePath 'git.exe' -ArgumentList @('cat-file', '--batch') -WorkingDirectory $RepositoryRoot -NoNewWindow -Wait -PassThru -RedirectStandardInput $requestPath -RedirectStandardOutput $responsePath -RedirectStandardError $errorPath
        if ($process.ExitCode -ne 0) {
            $stderr = if (Test-Path -LiteralPath $errorPath) { Get-Content -LiteralPath $errorPath -Raw } else { '' }
            throw "Git batch object reader failed: $stderr"
        }
        $response = [IO.File]::OpenRead($responsePath)
        try {
            foreach ($requestedObjectId in $objectIds) {
                $header = Read-GitBatchLine -Stream $response
                if ($header -match ' missing$') { throw "Git batch reader reported a missing reachable object: $requestedObjectId" }
                if ($header -notmatch '^([0-9a-f]{40,64}) ([a-z]+) ([0-9]+)$') {
                    throw "Malformed Git batch protocol header for $requestedObjectId"
                }
                $actualObjectId = $Matches[1]
                $objectType = $Matches[2]
                $objectSize = [long]$Matches[3]
                if ($actualObjectId -cne $requestedObjectId) {
                    throw "Git batch protocol returned an unexpected object: $actualObjectId"
                }
                if ($objectType -eq 'blob') {
                    $bytes = Read-GitBatchBytes -Stream $response -Length $objectSize
                    $blobCount++
                    $blobBytes += $objectSize
                    if (Test-BackupBytesOrArchiveContainSecret -Bytes $bytes -Label "Git blob $requestedObjectId") {
                        throw "Potential secret content exists in reachable Git blob: $requestedObjectId"
                    }
                } else {
                    Read-GitBatchBytes -Stream $response -Length $objectSize -Discard | Out-Null
                }
            }
            if ($response.Position -ne $response.Length) { throw 'Git batch protocol contains unexpected trailing bytes.' }
        } finally {
            $response.Dispose()
        }
    } finally {
        if (Test-Path -LiteralPath $TemporaryDirectory) {
            Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
        }
    }
    $stopwatch.Stop()
    return [pscustomobject]@{
        objectCount = $objectIds.Count
        blobCount = $blobCount
        blobBytes = $blobBytes
        elapsedMilliseconds = [long]$stopwatch.ElapsedMilliseconds
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
