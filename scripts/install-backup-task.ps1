[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

try {
    $taskName = 'MetricHit-Daily-Backup'
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $backupScript = Join-Path $repoRoot 'scripts\backup-metrichit.ps1'
    if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) { throw "Backup script not found: $backupScript" }

    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existing -and -not $Force) {
        throw "Scheduled Task '$taskName' already exists. Re-run with -Force to replace it."
    }
    if ($null -ne $existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backupScript`""
    $trigger = New-ScheduledTaskTrigger -Daily -At 3:30AM
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType S4U -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Creates the daily local MetricHit backup.' | Out-Null

    Write-Output "Scheduled Task '$taskName' registered for 03:30 local server time as $currentUser."
    exit 0
} catch {
    Write-Error $_
    exit 1
}
