param(
    [string]$TaskName = "MedPaperFlow-DualDaily",
    [string]$StartTime = "05:30",
    [string]$ProjectRoot = "",
    [switch]$DryRun = $false,
    [switch]$SkipPreflight = $false,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$runner = Join-Path $ProjectRoot "scripts\run_daily_dual_domains.ps1"
if (-not (Test-Path $runner)) {
    throw "Runner script not found: $runner"
}

$parts = $StartTime.Split(':')
if ($parts.Count -ne 2) {
    throw "StartTime must be HH:mm, for example 08:30"
}
$hour = [int]$parts[0]
$minute = [int]$parts[1]
$triggerTime = (Get-Date).Date.AddHours($hour).AddMinutes($minute)

$argList = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"' + $runner + '"')
)
if ($DryRun) {
    $argList += '-DryRun'
}
if ($SkipPreflight) {
    $argList += '-SkipPreflight'
}
$taskArgs = $argList -join ' '

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArgs -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if ($Force) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Run medical and CQED/Plasmonics daily paper pipelines sequentially.' -Force:$Force | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "Start time: $StartTime"
Write-Host "Runner: $runner"
Write-Host "Command: powershell.exe $taskArgs"
