# THE STORE STAYS UP (Nick 2026-09-15: "The loop doesn't work if it can't reach you - that's
# twice today. Whatever it is, make it reliable.")
#
# Cowork reaches the store only from a browser tab on http://127.0.0.1:5050. When the backend
# is not listening, every filing fails and looks exactly like Cowork's own browser failing.
# This loop pings /api/ping every 30 seconds; after three misses in a row it restarts the
# backend (and the client, if it is down) with start_persona_backend.ps1, then files a
# progress row so Cowork knows to re-post anything it queued.
#
# A deliberate shutdown stays down: create _runtime\backend_keepalive.stop and the loop idles
# (delete the file to resume). Only one keepalive runs: _runtime\backend_keepalive.pid.

param([int]$Port = 5050, [int]$IntervalSeconds = 30, [int]$MissesBeforeRestart = 3)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo "_runtime"
if (-not (Test-Path $runtime)) { New-Item -ItemType Directory -Force $runtime | Out-Null }
$pidFile = Join-Path $runtime "backend_keepalive.pid"
$stopFile = Join-Path $runtime "backend_keepalive.stop"
$logFile = Join-Path $runtime "backend_keepalive.log"

if (Test-Path $pidFile) {
  $other = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($other -and ($other -ne "$PID") -and (Get-Process -Id ([int]$other) -ErrorAction SilentlyContinue)) {
    exit 0
  }
}
Set-Content -Path $pidFile -Value "$PID" -Encoding ascii

function Write-KeepaliveLog([string]$line) {
  Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $line) -Encoding utf8
}

function Test-Store {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/ping" -UseBasicParsing -TimeoutSec 10
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

Write-KeepaliveLog "keepalive started pid=$PID port=$Port"
$misses = 0
while ($true) {
  Start-Sleep -Seconds $IntervalSeconds
  if (Test-Path $stopFile) { $misses = 0; continue }
  if (Test-Store) { $misses = 0; continue }
  $misses += 1
  Write-KeepaliveLog "ping missed ($misses/$MissesBeforeRestart)"
  if ($misses -lt $MissesBeforeRestart) { continue }
  $misses = 0
  Write-KeepaliveLog "store not answering - restarting"
  try {
    & (Join-Path $PSScriptRoot "start_persona_backend.ps1") -Port $Port -Force -SkipPreflight -NoKeepalive *>> $logFile
  } catch {
    Write-KeepaliveLog "restart raised: $($_.Exception.Message)"
  }
  if (Test-Store) {
    Write-KeepaliveLog "store back up"
    try {
      $body = @{
        signature = "vs-store-restarted-by-keepalive"
        category  = "progress"
        severity  = "note"
        source    = "vs"
        title     = "The store stopped answering and was restarted at $(Get-Date -Format 'HH:mm:ss') - re-post anything queued"
        observed  = "backend_keepalive.ps1 missed $MissesBeforeRestart pings on http://127.0.0.1:$Port/api/ping and restarted the backend. Anything Cowork could not file in that window should be re-posted now."
        expected  = "Cowork re-posts queued filings"
      } | ConvertTo-Json
      Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/issues" -Method Post -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 20 | Out-Null
    } catch {
      Write-KeepaliveLog "could not post the restart row: $($_.Exception.Message)"
    }
  } else {
    Write-KeepaliveLog "restart did not bring the store back - will retry"
  }
}
