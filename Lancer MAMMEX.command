#!/bin/bash
# Double-cliquez sur ce fichier pour lancer MAMMEX (macOS).
cd "$(dirname "$0")" || exit 1
clear
echo "MAMMEX — démarrage..."
if ! command -v python3 >/dev/null 2>&1; then
  echo
  echo "Python 3 est introuvable sur ce Mac."
  echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
  echo
  read -r -p "Appuyez sur Entrée pour fermer."
  exit 1
fi
python3 lancer.py
echo
read -r -p "MAMMEX est arrêté. Appuyez sur Entrée pour fermer cette fenêtre."
