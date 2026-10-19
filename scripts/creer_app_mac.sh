#!/bin/bash
# Raccourci conservé : crée l'application de bureau « Atelier Trésorerie » (fenêtre native, Electron).
# Voir scripts/macos/install-desktop.sh ; variante qui ouvre le navigateur : scripts/macos/install-launcher.sh
exec bash "$(dirname "$0")/macos/install-desktop.sh" "$@"
