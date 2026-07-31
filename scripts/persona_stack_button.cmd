@echo off
title Persona Stack
rem Launch button for the persona testing stack. The Cowork testing app
rem launches this via its Start-menu shortcut. All output goes to
rem C:\dev\business_plann_app\_logs_stack_button.txt so Cowork can read the
rem result (STACK READY or the failure) from the file.
cd /d C:\dev\business_plann_app
echo ==== persona_stack_button %DATE% %TIME% ==== >> "C:\dev\business_plann_app\_logs_stack_button.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\dev\business_plann_app\scripts\start_persona_stack.ps1" >> "C:\dev\business_plann_app\_logs_stack_button.txt" 2>&1
echo exitcode=%ERRORLEVEL% >> "C:\dev\business_plann_app\_logs_stack_button.txt"
