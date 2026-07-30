# One-command persona stack: backend (:5050, full observability) + frontend (:5173).
# This is the exact start command for browser-driven persona runs (Claude Cowork
# as the client). After it prints STACK READY, open:
#
#   http://localhost:5173/business-plan-form
#
# in a FRESH browser tab/window per run (draft identity lives in sessionStorage,
# so a new tab = a new draft; reusing a tab resumes the old draft).
#
# Idempotent-ish: if a port is already serving, that half is left as-is.
# Stale-server rule still applies: after ANY app-code edit, stop the backend
# and rerun this so the run exercises current code.

param(
  [int]$BackendPort = 5050,
  [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Test-PortUp([int]$Port, [string]$Path = "/") {
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port$Path" -UseBasicParsing -TimeoutSec 3
    return ($resp.StatusCode -ge 200)
  } catch { return $false }
}

# --- Backend ---------------------------------------------------------------
if (Test-PortUp $BackendPort "/api/business-types") {
  Write-Host "backend already serving on :$BackendPort (leaving it; restart manually after app-code edits)"
} else {
  powershell -File (Join-Path $PSScriptRoot "start_persona_backend.ps1") -Port $BackendPort
  if ($LASTEXITCODE -ne 0) { throw "backend failed to start (see start_persona_backend output)" }
}

# --- Frontend --------------------------------------------------------------
if (Test-PortUp $FrontendPort) {
  Write-Host "frontend already serving on :$FrontendPort"
} else {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $feLog = Join-Path $repo ("_logs_frontend_{0}.txt" -f $stamp)
  $feDir = Join-Path $repo "frontend"
  $cmdLine = "npm run dev >> `"$feLog`" 2>&1"
  $proc = Start-Process -FilePath $env:ComSpec -ArgumentList "/c", $cmdLine -WorkingDirectory $feDir -WindowStyle Hidden -PassThru
  Write-Host "frontend starting (pid $($proc.Id)), log -> $feLog"
  $up = $false
  foreach ($i in 1..45) {
    Start-Sleep -Seconds 1
    if (Test-PortUp $FrontendPort) { $up = $true; break }
    if ($proc.HasExited) { break }
  }
  if (-not $up) {
    Write-Host "frontend did NOT come up; tail of $feLog :"
    if (Test-Path $feLog) { Get-Content $feLog -Tail 30 }
    exit 1
  }
}

Write-Host ""
Write-Host "STACK READY"
Write-Host "  client entry : http://localhost:$FrontendPort/business-plan-form  (fresh tab per run)"
Write-Host "  backend      : http://127.0.0.1:$BackendPort (BPLAN_TRACE_VERBOSE=1)"
Write-Host "  watcher      : .venv\Scripts\python.exe scripts\persona_session_watch.py"
