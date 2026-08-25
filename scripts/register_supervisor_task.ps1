# Register the post-intake supervisor as a Windows scheduled task
# (every 5 minutes, runs whether or not a user is logged on is up to the
# operator — default: current user, logged-on only).
#
#   powershell -File scripts\register_supervisor_task.ps1
#   powershell -File scripts\register_supervisor_task.ps1 -Unregister

param(
  [switch]$Unregister,
  [int]$EveryMinutes = 5
)

$ErrorActionPreference = "Stop"
$taskName = "BusinessPlanApp-Supervisor"
$repo = Split-Path -Parent $PSScriptRoot
# pythonw + the quiet launcher: a console python fired by Task Scheduler flashes
# a terminal on the desktop every tick; the launcher keeps stdout in _logs\supervisor.log.
$python = Join-Path $repo ".venv\Scripts\pythonw.exe"
$script = Join-Path $repo "scripts\run_supervisor_quiet.py"

if ($Unregister) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Host "unregistered $taskName"
  exit 0
}

if (-not (Test-Path $python)) { throw "missing $python" }
if (-not (Test-Path $script)) { throw "missing $script" }

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable -Hidden

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $settings -Description "Reap dead planning runs, ladder reruns, dead-letter escalation." -Force
Write-Host "registered $taskName (every $EveryMinutes min): $python $script"
