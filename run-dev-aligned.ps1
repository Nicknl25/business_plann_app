$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing venv interpreter at $python. Create the venv first."
}

$backendPort = 5050
$apiBase = "http://localhost:$backendPort"
$backendScript = Join-Path $repoRoot "python\\run_backend_aligned.py"
if (-not (Test-Path $backendScript)) {
  throw "Missing backend entrypoint at $backendScript."
}

function Stop-ListenersOnPort {
  param([int[]]$Ports)
  foreach ($p in $Ports) {
    $pids = @()
    try {
      $pids = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
      $pids = @()
    }

    if (-not $pids -or $pids.Count -eq 0) {
      try {
        $pids = netstat -ano |
          Select-String -Pattern (":$p\\s+.*LISTENING") |
          ForEach-Object { (($_.Line -split '\\s+')[-1]).Trim() } |
          Where-Object { $_ -match '^\\d+$' } |
          Select-Object -Unique
      } catch {
        $pids = @()
      }
    }

    foreach ($owningPid in ($pids | Where-Object { $_ -and $_ -ne 0 })) {
      try { Stop-Process -Id ([int]$owningPid) -Force -ErrorAction SilentlyContinue } catch {}
    }
  }
}

# Kill any existing listeners so the frontend can't accidentally hit an old backend.
Stop-ListenersOnPort -Ports @(
  5000, $backendPort,
  5173, 5174, 5175, 5176, 5177
)

$backendLine = "cd /d `"$repoRoot`" && set LLM_TIMING=1 && set BACKEND_PORT=$backendPort && set FLASK_RUN_PORT=$backendPort && set PORT=$backendPort && set PYTHONUNBUFFERED=1 && `"$python`" -u `"$backendScript`""
$frontendLine = "cd /d `"$repoRoot\\frontend`" && set VITE_API_BASE_URL=$apiBase && npm run dev"

Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $backendLine) | Out-Null
Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $frontendLine) | Out-Null

Write-Host "Started backend on $apiBase with LLM_TIMING=1 (no reloader)."
Write-Host "Started frontend with VITE_API_BASE_URL=$apiBase."
Write-Host "Use the frontend URL shown in the Vite window."
