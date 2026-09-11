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
  [int]$Port = 5050,
  [switch]$Force,
  [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# NO HOT-PATCHING: never restart while a persona intake is live (a restart
# mid-run kills the browser session's turn and strands the draft - the
# 2026-08-02 restart froze a run at ops and spawned phantom drafts). A
# LIVE intake = in_progress draft touched in the last 10 minutes with no
# terminal planning run. Use -Force only when you have decided the run is
# expendable.
if (-not $Force) {
  $python0 = Join-Path $repo ".venv\Scripts\python.exe"
  $probeScript = Join-Path $repo "scripts\_active_intake_probe.py"
  $active = ""
  if ((Test-Path $python0) -and (Test-Path $probeScript)) {
    try { $active = (& $python0 $probeScript 2>$null | Select-Object -Last 1) } catch { $active = "" }
  }
  if ($active) {
    Write-Host "REFUSED: persona intake $($active.Substring(0,8)) is live right now."
    Write-Host "Restarting would kill its turn mid-flight. Wait for the run boundary, or re-run with -Force."
    exit 2
  }
}

# PREFLIGHT (Nick 2026-09-11): a broken submit-path door is caught HERE, in
# seconds and for free - never 45 minutes into a paid intake. scripts/preflight.py
# checks source (control characters, renderer JS, imports), the pins, the
# INTAKE->POST_INTAKE boundary and the payroll payload door on recent stored
# drafts, read-only. A failure refuses the start. -SkipPreflight only when you
# have decided to run blind.
if (-not $SkipPreflight) {
  $pyPre = Join-Path (Join-Path (Join-Path $repo ".venv") "Scripts") "python.exe"
  $preflight = Join-Path (Join-Path $repo "scripts") "preflight.py"
  if (-not ((Test-Path $pyPre) -and (Test-Path $preflight))) {
    Write-Host "REFUSED: preflight script or venv python missing."
    exit 3
  }
  Write-Host "preflight: source, pins, boundary and payroll doors on recent stored drafts ..."
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $pyPre -X utf8 $preflight
  $preCode = $LASTEXITCODE
  # The ten-draft replay is a command, not a gate - but it is ALWAYS run
  # before a Cowork run (Nick 2026-09-11). Say so when the last one does not
  # cover this build. A note, never a refusal.
  $replayNote = "no full replay on record"
  $replayReport = Join-Path (Join-Path $repo "_runtime") "post_intake_replay_last.json"
  if (Test-Path $replayReport) {
    try {
      $rep = Get-Content $replayReport -Raw | ConvertFrom-Json
      $headSha = (& git -C $repo rev-parse HEAD 2>$null)
      $blocking = @($rep.results | Where-Object { @("REGRESSION", "NEW_FAILURE", "GPT_MISS", "ERROR", "ACCEPTANCE_DROP") -contains $_.verdict })
      if ($rep.build -ne $headSha) {
        $replayNote = "the last full replay ran on $("$($rep.build)".Substring(0, 8)), not this build"
      } elseif ($blocking.Count -gt 0) {
        $replayNote = "the last full replay of this build did NOT pass ($($blocking.Count) blocking)"
      } else {
        $replayNote = ""
      }
    } catch {
      $replayNote = "the last full replay report is unreadable"
    }
  }
  $ErrorActionPreference = $prevEap
  if ($preCode -ne 0) {
    Write-Host "REFUSED: preflight failed - fix the door before starting a run (or -SkipPreflight)."
    exit 3
  }
  if ($replayNote) {
    Write-Host "NOTE: $replayNote - run python scripts/replay_post_intake.py before a Cowork run."
  }
}

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

# Kill ANY existing listener on the port first. Windows allowed two pythons
# to LISTEN on 127.0.0.1:$Port simultaneously; the OLD server kept taking
# all traffic (stale code) while the new one sat starved — and the health
# probe below passed because the old server answered. (2026-07-31: this
# masked the submit-trigger verification for an hour.)
$stale = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
           Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($stalePid in $stale) {
  Write-Host "killing stale listener on :$Port (pid $stalePid)"
  try { Stop-Process -Id $stalePid -Force -ErrorAction Stop } catch {}
}
if ($stale.Count) { Start-Sleep -Seconds 2 }

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

# Exactly ONE listener must own the port — a second one means the health
# probe above may have been answered by a survivor running stale code.
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
               Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count -ne 1) {
  Write-Host "FATAL: expected exactly 1 listener on :$Port, found $($listeners.Count) (pids: $($listeners -join ', '))."
  Write-Host "Kill them all and re-run this script."
  exit 1
}

Write-Host "backend is up on http://127.0.0.1:$Port (BPLAN_TRACE_VERBOSE=1)"
Write-Host "next: cd frontend; npm run dev   (then open http://localhost:5173)"
Write-Host "watch: `"$python`" scripts\run_live_e2e_monitor.py --watch-only --stall-seconds 300"
