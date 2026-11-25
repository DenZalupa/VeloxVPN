@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/k cd /d """%~dp0""" && call run.bat' -Verb RunAs"
