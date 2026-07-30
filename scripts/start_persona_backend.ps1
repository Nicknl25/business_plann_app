# Start the :5050 backend for a persona (browser-driven) run with full observability:
#   - BPLAN_TRACE_VERBOSE=1  -> post_intake_handler_traces rows carry verbatim GPT request/response
#   - stderr+stdout          -> one timestamped log file (_logs_persona_<stamp>.txt)
#   - frontend/.env.local    -> VITE_API_BASE_URL pinned to this port (Vite reads it on next `npm run dev`)
#
# After it prints "backend is up", start the frontend and (optionally) the watcher:
#   cd frontend; npm run dev
#   .venv\Scripts\python.exe scripts\run_live_e2e_monitor.py --watch-only --stall-seconds 300
#
# Doctrine reminder: restart this server after EVERY app-code edit (stale-server rule),
# and run the Sunny_V3 canary before any batch.

param(
  [int]$Port = 5050
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$launcher = Join-Path $repo "_run_server_noreload.py"
if (-not (Test-Path $launcher)) {
  throw "Missing $launcher (local, untracked launcher). Create it or start api.app on :$Port yourself."
}
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing venv python at $python"
}

# Pin the frontend at this API port. .env.local overrides frontend/.env and is not committed.
$envLocal = Join-Path $repo "frontend\.env.local"
$apiLine = "VITE_API_BASE_URL=http://127.0.0.1:$Port"
$kept = @()
if (Test-Path $envLocal) {
  $kept = @(Get-Content $envLocal | Where-Object { $_ -notmatch "^\s*VITE_API_BASE_URL=" })
}
Set-Content -Path $envLocal -Value (@($apiLine) + $kept) -Encoding utf8
Write-Host "frontend/.env.local -> $apiLine"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $repo ("_logs_persona_{0}.txt" -f $stamp)

$env:PORT = "$Port"
$env:BPLAN_TRACE_VERBOSE = "1"

# Spawn python directly; the launcher self-redirects stdout+stderr to
# BPLAN_SERVER_LOG. The former `cmd /c ... >> log 2>&1` layer is gone:
# powershell.exe 5.1 Start-Process re-quotes a space-containing argument,
# cmd's quote-stripping then mangles the line, and the backend died with
# exit 1 before the redirect ever created the log.
$env:BPLAN_SERVER_LOG = "$log"
$proc = Start-Process -FilePath $python -ArgumentList "-u", $launcher -WorkingDirectory $repo -WindowStyle Hidden -PassThru
$env:BPLAN_SERVER_LOG = ""
Write-Host "backend starting (pid $($proc.Id)), log -> $log"

$up = $false
foreach ($i in 1..30) {
  Start-Sleep -Seconds 1
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/business-types" -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -ge 200) { $up = $true; break }
  } catch {}
  if ($proc.HasExited) { break }
}

if (-not $up) {
  Write-Host "backend did NOT come up; tail of $log :"
  if (Test-Path $log) { Get-Content $log -Tail 30 }
  exit 1
}

Write-Host "backend is up on http://127.0.0.1:$Port (BPLAN_TRACE_VERBOSE=1)"
Write-Host "next: cd frontend; npm run dev   (then open http://localhost:5173)"
Write-Host "watch: `"$python`" scripts\run_live_e2e_monitor.py --watch-only --stall-seconds 300"
