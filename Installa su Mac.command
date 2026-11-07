#!/bin/zsh
# Installazione di AI Tree Recorder su Mac (macOS 14 o successivo).
set -euo pipefail
cd "${0:A:h}"
echo "== AI Tree Recorder · installazione Mac =="

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installo gli strumenti da riga di comando di Apple (si apre una finestra)..."
  xcode-select --install || true
  echo "Al termine rilancia questo file."; exit 1
fi

PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import tkinter, sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    PY="$c"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Serve Python 3.11 o 3.12 da python.org (include l'interfaccia grafica)."
  open "https://www.python.org/downloads/macos/"; exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  else
    echo "ffmpeg mancante: lo installo dentro il programma (imageio-ffmpeg)."
    EXTRA_FFMPEG=1
  fi
fi

"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt
[[ "${EXTRA_FFMPEG:-0}" == 1 ]] && .venv/bin/pip install imageio-ffmpeg

zsh mac/build-mac.sh
echo
echo "Fatto. Ora apri «Avvia AI Tree Recorder.command»."
echo "Al primo avvio macOS chiederà i permessi Microfono e Registrazione schermo e audio"
echo "per il Terminale: concedili, poi chiudi e riapri il programma."
mac/build/aitree-helper check || true
