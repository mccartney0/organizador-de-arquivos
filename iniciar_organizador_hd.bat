@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 organizador_hd.py
) else (
  python organizador_hd.py
)
endlocal
