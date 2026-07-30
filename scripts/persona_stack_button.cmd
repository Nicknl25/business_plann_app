@echo off
title Persona Stack
rem Launch button for the persona testing stack. The Cowork testing app
rem launches this via its Start-menu shortcut; the window stays open so the
rem STACK READY line is visible.
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\dev\business_plann_app\scripts\start_persona_stack.ps1"
echo.
echo (You can close this window; the stack keeps running.)
pause
