[CmdletBinding()]
param(
  [int]$Port = 5050,
  [string]$BaseUrl = "http://127.0.0.1:5050",
  [switch]$ForceRestart,
  [int]$ProbeTimeoutSeconds = 3,
  [int]$StartupTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:PythonExe = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
$script:RunnerPath = Join-Path $script:RepoRoot "context\run_api_5050_single.py"
$script:RuntimeProbeUrl = ($BaseUrl.TrimEnd("/") + "/api/runtime-probe")

function Test-BackendHealth {
  param(
    [string]$Url,
    [int]$TimeoutSeconds
  )

  try {
    $probe = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSeconds
    if ($null -eq $probe) {
      return $null
    }
    return $probe
  } catch {
    return $null
  }
}

function Get-ListeningProcessIds {
  param(
    [int]$ListeningPort
  )

  $processIds = @()

  try {
    $connections = Get-NetTCPConnection -LocalPort $ListeningPort -State Listen -ErrorAction Stop
    $processIds = @(
      $connections |
      Select-Object -ExpandProperty OwningProcess -Unique |
      Where-Object { $_ -and $_ -gt 0 }
    )
  } catch {
    $netstatLines = netstat -ano | Select-String ":$ListeningPort"
    foreach ($line in $netstatLines) {
      $text = ($line.ToString()).Trim()
      if ($text -notmatch "LISTENING") {
        continue
      }
      $parts = $text -split "\s+"
      if ($parts.Length -lt 5) {
        continue
      }
      $candidatePid = 0
      if ([int]::TryParse($parts[-1], [ref]$candidatePid) -and $candidatePid -gt 0) {
        $processIds += $candidatePid
      }
    }
    $processIds = @($processIds | Select-Object -Unique)
  }

  return @($processIds)
}

function Stop-ListeningProcesses {
  param(
    [int]$ListeningPort
  )

  $stopped = @()
  foreach ($listenerPid in (Get-ListeningProcessIds -ListeningPort $ListeningPort)) {
    try {
      Get-Process -Id $listenerPid -ErrorAction Stop | Stop-Process -Force -ErrorAction Stop
      $stopped += $listenerPid
    } catch {
      # Ignore already-exited processes and continue cleaning up the port.
    }
  }
  return @($stopped | Select-Object -Unique)
}

function Get-LatestBackendSourceWriteTimeUtc {
  $paths = @()
  $pythonRoot = Join-Path $script:RepoRoot "python"
  if (Test-Path -LiteralPath $pythonRoot) {
    $paths += Get-ChildItem -LiteralPath $pythonRoot -Recurse -File -Filter *.py | Select-Object -ExpandProperty FullName
  }
  if (Test-Path -LiteralPath $script:RunnerPath) {
    $paths += $script:RunnerPath
  }
  $latest = [datetime]::MinValue
  foreach ($path in ($paths | Select-Object -Unique)) {
    try {
      $item = Get-Item -LiteralPath $path -ErrorAction Stop
      if ($item.LastWriteTimeUtc -gt $latest) {
        $latest = $item.LastWriteTimeUtc
      }
    } catch {
      # Ignore transient file lookup issues and continue.
    }
  }
  return $latest
}

function Get-ListenerStartTimeUtc {
  param(
    [int[]]$ListenerPids
  )

  $startTimes = @()
  foreach ($listenerPid in ($ListenerPids | Select-Object -Unique)) {
    try {
      $process = Get-Process -Id $listenerPid -ErrorAction Stop
      if ($process.StartTime) {
        $startTimes += $process.StartTime.ToUniversalTime()
      }
    } catch {
      # Ignore exited processes.
    }
  }
  if (-not $startTimes) {
    return $null
  }
  return ($startTimes | Sort-Object | Select-Object -First 1)
}

if (-not (Test-Path -LiteralPath $script:PythonExe)) {
  throw "Python executable not found: $script:PythonExe"
}

if (-not (Test-Path -LiteralPath $script:RunnerPath)) {
  throw "Backend runner not found: $script:RunnerPath"
}

$listenerPids = @(Get-ListeningProcessIds -ListeningPort $Port)
$probe = Test-BackendHealth -Url $script:RuntimeProbeUrl -TimeoutSeconds $ProbeTimeoutSeconds
$latestSourceWriteUtc = Get-LatestBackendSourceWriteTimeUtc
$listenerStartUtc = Get-ListenerStartTimeUtc -ListenerPids $listenerPids
$staleProcess = ((-not $ForceRestart) -and $probe -and $listenerStartUtc -and ($latestSourceWriteUtc -gt $listenerStartUtc))
if ($probe -and -not $ForceRestart -and -not $staleProcess) {
  [pscustomobject]@{
    action = "already_healthy"
    port = $Port
    base_url = $BaseUrl
    runtime_probe = $probe
    listener_pids = $listenerPids
    listener_start_time_utc = $listenerStartUtc
    latest_source_write_time_utc = $latestSourceWriteUtc
  } | ConvertTo-Json -Depth 8 -Compress
  exit 0
}

$stoppedPids = Stop-ListeningProcesses -ListeningPort $Port

$startedProcess = Start-Process `
  -FilePath $script:PythonExe `
  -ArgumentList $script:RunnerPath `
  -WorkingDirectory $script:RepoRoot `
  -WindowStyle Hidden `
  -PassThru

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$healthyProbe = $null
do {
  Start-Sleep -Milliseconds 750
  $healthyProbe = Test-BackendHealth -Url $script:RuntimeProbeUrl -TimeoutSeconds $ProbeTimeoutSeconds
  if ($healthyProbe) {
    break
  }
} while ((Get-Date) -lt $deadline)

if (-not $healthyProbe) {
  throw "Backend did not become healthy on $BaseUrl within $StartupTimeoutSeconds seconds."
}

[pscustomobject]@{
  action = if ($ForceRestart) { "force_restarted" } elseif ($staleProcess) { "restarted_stale_process" } else { "restarted" }
  port = $Port
  base_url = $BaseUrl
  stopped_listener_pids = $stoppedPids
  launcher_pid = $startedProcess.Id
  listener_pids = @(Get-ListeningProcessIds -ListeningPort $Port)
  runtime_probe = $healthyProbe
  listener_start_time_utc = (Get-ListenerStartTimeUtc -ListenerPids @(Get-ListeningProcessIds -ListeningPort $Port))
  latest_source_write_time_utc = $latestSourceWriteUtc
} | ConvertTo-Json -Depth 8 -Compress
