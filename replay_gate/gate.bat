@echo off
REM Replay gate - catch every KNOWN issue before spending a Cowork run.
REM   gate.bat              -> gate the current build (fast tier)
REM   gate.bat --tier full  -> include the live-judge legs
REM   gate.bat --prove      -> prove every leg on its own broken baseline
REM   gate.bat --list       -> the leg list
setlocal
set REPO=C:\dev\business_plann_app
pushd "%REPO%"
"%REPO%\.venv\Scripts\python.exe" -m replay_gate.run_gate %*
set RC=%ERRORLEVEL%
popd
if %RC%==0 echo(& echo GREEN - every known issue is clear. Safe to spend a Cowork run.
if %RC%==1 echo(& echo RED - a fixed bug regressed or an invariant broke. Bounce to VS.
if %RC%==2 echo(& echo SETUP FAILED - the gate is wrong, not the build.
exit /b %RC%
