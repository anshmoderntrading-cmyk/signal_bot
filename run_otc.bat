@echo off
cd /d %~dp0
if not exist .venv (
  echo Setting up Python 3.12... (first time only, takes 3-5 minutes)
  py install 3.12 >nul 2>&1
  py -V:3.12 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || python -m venv .venv
  if not exist .venv\Scripts\python.exe (
    echo Python not found. Install Python from python.org with "Add to PATH" ticked.
    pause
    exit /b
  )
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements-quotex.txt
  if errorlevel 1 (
    echo Package install failed. Send a screenshot of this window.
    rmdir /s /q .venv
    pause
    exit /b
  )
)
if not exist .env (
  copy .env.quotex.example .env >nul
  echo .env file created. Notepad is opening - fill in the token/email/password, save, then run run_otc.bat again.
  notepad .env
  pause
  exit /b
)
.venv\Scripts\python bot.py
pause
