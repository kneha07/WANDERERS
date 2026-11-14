@echo off
rem One-click boot for WANDERERS and the live explorer (Windows). Needs Node.js and Python 3.11+.
where node >nul 2>nul || (echo Node.js is needed: https://nodejs.org/ & pause & exit /b 1)
node "%~dp0start.js" %*
if errorlevel 1 pause
