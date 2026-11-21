@echo off
cd /d %~dp0
if not exist .venv (
  py -3.12 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements-quotex.txt
)
if not exist .env (
  copy .env.quotex.example .env
  echo .env file created. Open it in Notepad, fill in the token/email/password, then run run_otc.bat again.
  notepad .env
  pause
  exit /b
)
.venv\Scripts\python bot.py
pause
