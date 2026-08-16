$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot '..\scripts\backup-common.ps1')

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    if ($Actual -ne $Expected) { throw "$Message Expected '$Expected', got '$Actual'." }
}

function Assert-True {
    param([bool]$Value, [string]$Message)
    if (-not $Value) { throw $Message }
}

$root = Join-Path ([IO.Path]::GetTempPath()) ("MetricHitBackupRetry-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $source = Join-Path $root 'source'
    New-Item -ItemType Directory -Path $source | Out-Null
    $archive = Join-Path $root 'current.zip'

    $global:backupRetryAttempts = 0
    $attempts = Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -InitialDelayMilliseconds 0 -ArchiveAction {
        param($unusedSource, $path)
        $global:backupRetryAttempts++
        Set-Content -LiteralPath $path -Value 'partial' -NoNewline
        if ($global:backupRetryAttempts -lt 5) { throw [IO.IOException]::new('The process cannot access the file because it is being used by another process.') }
        Set-Content -LiteralPath $path -Value 'complete' -NoNewline
    }
    Assert-Equal $attempts 5 'Transient lock must tolerate a longer Windows lock before succeeding.'
    Assert-Equal (Get-Content -LiteralPath $archive -Raw) 'complete' 'Partial archive must be replaced on retry.'

    Remove-Item -LiteralPath $archive -Force
    $global:backupRetryAttempts = 0
    $accessDeniedAttempts = Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -InitialDelayMilliseconds 0 -ArchiveAction {
        param($unusedSource, $path)
        $global:backupRetryAttempts++
        if ($global:backupRetryAttempts -eq 1) { throw [UnauthorizedAccessException]::new('Access is denied.') }
        Set-Content -LiteralPath $path -Value 'complete' -NoNewline
    }
    Assert-Equal $accessDeniedAttempts 2 'Transient access denial must retry.'
    Remove-Item -LiteralPath $archive -Force

    $global:backupRetryAttempts = 0
    $global:backupRetryRemovals = 0
    $cleanupAttempts = Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -InitialDelayMilliseconds 0 -ArchiveAction {
        param($unusedSource, $path)
        $global:backupRetryAttempts++
        if ($global:backupRetryAttempts -eq 1) {
            Set-Content -LiteralPath $path -Value 'partial' -NoNewline
            throw [IO.IOException]::new('The process cannot access the file because it is being used by another process.')
        }
        Set-Content -LiteralPath $path -Value 'complete' -NoNewline
    } -ArchiveRemoveAction {
        param($path)
        $global:backupRetryRemovals++
        if ($global:backupRetryRemovals -eq 1) { throw [IO.IOException]::new('The process cannot access the file because it is being used by another process.') }
        Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    }
    Assert-Equal $cleanupAttempts 2 'Transient cleanup lock must not prevent archive retry.'
    Assert-Equal $global:backupRetryRemovals 2 'Incomplete ZIP cleanup must retry only the current archive.'
    Assert-Equal (Get-Content -LiteralPath $archive -Raw) 'complete' 'Cleanup retry must not accept partial archive.'

    Remove-Item -LiteralPath $archive -Force
    $global:backupRetryAttempts = 0
    $persistent = $null
    try {
        Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -MaxAttempts 3 -InitialDelayMilliseconds 0 -ArchiveAction {
            param($unusedSource, $path)
            $global:backupRetryAttempts++
            Set-Content -LiteralPath $path -Value 'partial' -NoNewline
            throw [IO.IOException]::new('The process cannot access the file because it is being used by another process.')
        }
    } catch { $persistent = $_ }
    Assert-True ($null -ne $persistent) 'Persistent lock must fail.'
    Assert-Equal $global:backupRetryAttempts 3 'Persistent lock must stop at the retry limit.'
    Assert-True (-not (Test-Path -LiteralPath $archive)) 'Partial current ZIP must not remain accepted after failure.'

    $global:backupRetryAttempts = 0
    $other = $null
    try {
        Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -InitialDelayMilliseconds 0 -ArchiveAction {
            param($unusedSource, $path)
            $global:backupRetryAttempts++
            Set-Content -LiteralPath $path -Value 'partial' -NoNewline
            throw [ArgumentException]::new('permanent test failure')
        }
    } catch { $other = $_ }
    Assert-True ($null -ne $other) 'Non-lock error must fail.'
    Assert-Equal $global:backupRetryAttempts 1 'Non-lock error must not retry.'
    Assert-True (-not (Test-Path -LiteralPath $archive)) 'Non-lock failure must not leave a partial current ZIP.'

    $missing = $null
    try {
        Invoke-BackupArchiveWithRetry -SourcePath $source -ArchivePath $archive -InitialDelayMilliseconds 0 -ArchiveAction { param($unusedSource, $path) }
    } catch { $missing = $_ }
    Assert-True ($null -ne $missing) 'Archive action without a ZIP must fail.'
    Assert-True (-not (Test-Path -LiteralPath $archive)) 'Missing ZIP must never be accepted.'
    Write-Output 'backup retry focused tests passed'
} finally {
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
