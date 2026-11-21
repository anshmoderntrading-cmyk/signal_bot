#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements-quotex.txt
fi
if [ ! -f .env ]; then
  cp .env.quotex.example .env
  echo ".env file created. Fill in the token/email/password, then run ./run_otc.sh again."; exit 0
fi
.venv/bin/python bot.py
