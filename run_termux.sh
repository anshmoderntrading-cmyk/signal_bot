#!/data/data/com.termux/files/usr/bin/bash
# Run the Quotex OTC signal bot on an Android phone (Termux)
# First time:  bash run_termux.sh   (setup takes 10-20 minutes)
cd "$(dirname "$0")"
if [ ! -f .setup_done ]; then
  pkg update -y && pkg upgrade -y
  pkg install -y python git build-essential cmake ninja openssl libopenblas \
                 libandroid-execinfo patchelf llvm lld binutils python-numpy
  pip install requests pandas || { echo "pandas install failed"; exit 1; }
  pip install "pyquotex @ git+https://github.com/cleitonleonel/pyquotex.git" || { echo "pyquotex install failed"; exit 1; }
  touch .setup_done
fi
if [ ! -f .env ]; then
  cp .env.quotex.example .env
  echo ""
  echo "Fill in the .env file:  nano .env"
  echo "(TELEGRAM_BOT_TOKEN, QUOTEX_EMAIL, QUOTEX_PASSWORD) -> Ctrl+O, Enter, Ctrl+X"
  echo "Then run again:  bash run_termux.sh"
  exit 0
fi
termux-wake-lock 2>/dev/null   # keeps the bot from stopping when the phone screen turns off
python bot.py
