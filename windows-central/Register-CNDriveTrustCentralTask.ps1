param([string]$Root = 'C:\CNDriveTrust\Central')
$ErrorActionPreference = 'Stop'
$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
$script = Join-Path $Root 'scripts\Start-CNDriveTrustCentral.ps1'
$action = New-ScheduledTaskAction -Execute $pwsh -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Root `"$Root`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'CNDriveTrust Central Collector' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force

