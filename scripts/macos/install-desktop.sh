#!/bin/bash
# Atelier Trésorerie — crée l'application de bureau macOS « Atelier Trésorerie.app » (Electron),
# sur le modèle d'Atelier Projets.
#
#   bash scripts/macos/install-desktop.sh              → ~/Applications/Atelier Trésorerie.app
#   bash scripts/macos/install-desktop.sh ~/Desktop    → dans un autre dossier
#
# Une vraie application : sa propre fenêtre, son icône dans le Dock et son menu, sans navigateur. Au
# lancement, elle vérifie Python, démarre le serveur local et affiche l'interface ; Cmd+Q arrête tout.
# Journal : ~/Library/Logs/Atelier_Tresorerie/app.log
#
# L'application contient Electron et un petit lanceur qui pointe vers ce dossier : le code reste dans le
# projet (desktop/main.cjs), un « git pull » suffit pour la mettre à jour. Relancer ce script après un
# déplacement du dossier, un changement d'installation de Python ou de Node, ou une mise à jour d'Electron.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "✘ Ce script crée une application macOS : à lancer sur le Mac." >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
TARGET_DIR="${1:-$HOME/Applications}"
NAME="Atelier Trésorerie"
APP="$TARGET_DIR/$NAME.app"
BUNDLE_ID="local.atelier-tresorerie.desktop"
OLD_BUNDLE_ID="fr.atelier-tresorerie.app" # ancien lanceur qui ouvrait le navigateur

cd "$REPO"

# ---------------------------------------------------------------- Python (serveur Flask)
PYTHON="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON" ]]; then
  echo "✘ Python introuvable dans ce terminal : installer Python 3 puis relancer." >&2
  exit 1
fi
PYTHON="$("$PYTHON" -c 'import sys; print(sys.executable)')"
if ! "$PYTHON" -c "import flask, openpyxl, dotenv" >/dev/null 2>&1; then
  echo "→ Installation des dépendances Python (pip install -r requirements.txt)…"
  "$PYTHON" -m pip install -r requirements.txt
fi

# ---------------------------------------------------------------- Node et Electron
NODE="$(command -v node || true)"
NPM="$(command -v npm || true)"
if [[ -z "$NODE" || -z "$NPM" ]]; then
  echo "✘ node ou npm introuvable dans ce terminal (Node.js est déjà requis par Atelier Projets) : installer Node.js puis relancer." >&2
  exit 1
fi
if [[ ! -d desktop/node_modules/electron ]]; then
  echo "→ Installation d'Electron (npm install dans desktop/)…"
  npm install --prefix desktop --no-audit --no-fund
fi
echo "→ Téléchargement d'Electron si besoin…"
(cd desktop && node -e "require('electron')" >/dev/null)
ELECTRON_APP="$REPO/desktop/node_modules/electron/dist/Electron.app"
if [[ ! -d "$ELECTRON_APP" ]]; then
  echo "✘ Electron introuvable ($ELECTRON_APP). Essayer : rm -rf desktop/node_modules && npm install --prefix desktop" >&2
  exit 1
fi

# PATH enregistré sans les dossiers ajoutés par npm (node_modules/.bin) : une application ouverte depuis le
# Finder ne charge pas ~/.zshrc, elle doit retrouver Python, git et Claude Code.
SAVED_PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v -e '/node_modules/\.bin$' -e 'node-gyp-bin' | paste -sd: -)"

# ---------------------------------------------------------------- ancienne version
echo "→ Création de ${APP}…"
osascript -e "if application \"$NAME\" is running then tell application \"$NAME\" to quit" >/dev/null 2>&1 || true
# Serveur lancé par l'ancien lanceur (bouton « Quitter » dans l'interface) : arrêté pour repartir proprement.
PORT="$("$PYTHON" -c 'from config import Config; print(Config.PORT)' 2>/dev/null || echo 5050)"
if curl -fsS --max-time 1 "http://127.0.0.1:$PORT/api/ping" 2>/dev/null | grep -q '"app_mode": *true'; then
  curl -fsS --max-time 2 -X POST -H "X-Requested-With: install" "http://127.0.0.1:$PORT/api/system/shutdown" >/dev/null 2>&1 || true
fi
sleep 1
# Ancien lanceur navigateur installé ailleurs (ex. /Applications) : retiré pour ne pas avoir deux icônes.
for OLD in "/Applications/$NAME.app" "$HOME/Applications/$NAME.app"; do
  if [[ -d "$OLD" && "$OLD" != "$APP" ]] && [[ "$(defaults read "$OLD/Contents/Info" CFBundleIdentifier 2>/dev/null)" == "$OLD_BUNDLE_ID" ]]; then
    rm -rf "$OLD" 2>/dev/null && echo "  Ancien lanceur retiré : $OLD" || echo "⚠ Impossible de retirer l'ancien lanceur $OLD : supprimez-le à la main." >&2
  fi
done
mkdir -p "$TARGET_DIR"
rm -rf "$APP"
ditto "$ELECTRON_APP" "$APP"

PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "$NAME" "$PLIST"
plutil -replace CFBundleDisplayName -string "$NAME" "$PLIST"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$PLIST"
plutil -replace CFBundleIconFile -string "AppIcon" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "Atelier Trésorerie — application locale" "$PLIST"

# ---------------------------------------------------------------- lanceur : le code est lu dans le projet
RESOURCES="$APP/Contents/Resources"
rm -f "$RESOURCES/default_app.asar"
mkdir -p "$RESOURCES/app"
ATELIER_REPO="$REPO" ATELIER_PYTHON="$PYTHON" ATELIER_PATH="$SAVED_PATH" ATELIER_OUT="$RESOURCES/app" node <<'NODE'
const fs = require('node:fs')
const path = require('node:path')
const { version } = require(path.join(process.env.ATELIER_REPO, 'desktop', 'package.json'))
const out = process.env.ATELIER_OUT
fs.writeFileSync(
  path.join(out, 'package.json'),
  `${JSON.stringify({ name: 'atelier-tresorerie', productName: 'Atelier Trésorerie', version, main: 'main.cjs', private: true }, null, 2)}\n`,
)
fs.writeFileSync(
  path.join(out, 'main.cjs'),
  `// Lanceur généré par scripts/macos/install-desktop.sh (ne pas modifier : relancer ce script).
'use strict'
process.env.ATELIER_REPO = ${JSON.stringify(process.env.ATELIER_REPO)}
process.env.ATELIER_PYTHON = ${JSON.stringify(process.env.ATELIER_PYTHON)}
process.env.PATH = ${JSON.stringify(process.env.ATELIER_PATH)}
const fs = require('node:fs')
const path = require('node:path')
const entry = path.join(process.env.ATELIER_REPO, 'desktop', 'main.cjs')
if (fs.existsSync(entry)) {
  require(entry)
} else {
  const { app, dialog } = require('electron')
  app.whenReady().then(() => {
    dialog.showErrorBox('Atelier Trésorerie', 'Dossier du projet introuvable : ' + process.env.ATELIER_REPO + '\\n\\nDepuis le dossier du projet (déplacé ?), relancer : bash scripts/macos/install-desktop.sh')
    app.quit()
  })
}
`,
)
NODE

# ---------------------------------------------------------------- icône (.icns avec les outils de macOS)
ICON_SRC="$REPO/static/img/icon-1024.png"
if [[ -f "$ICON_SRC" ]] && command -v iconutil >/dev/null 2>&1; then
  ICONSET="$(mktemp -d)/AppIcon.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns" && rm -rf "$(dirname "$ICONSET")"
fi

# Info.plist et contenu modifiés : nouvelle signature locale (« ad hoc »), exigée sur les Mac Apple Silicon.
xattr -cr "$APP" 2>/dev/null || true
if ! codesign --force --deep --sign - "$APP" >/dev/null 2>&1; then
  echo "⚠ Signature locale impossible (codesign) : si macOS refuse d'ouvrir l'application, clic droit → Ouvrir." >&2
fi
touch "$APP"
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[[ -x "$LSREGISTER" ]] && "$LSREGISTER" -f "$APP" >/dev/null 2>&1 || true

echo "✔ Application créée : $APP"
echo "  Projet   : $REPO"
echo "  Python   : $PYTHON"
echo "  Node     : $NODE ($("$NODE" --version))"
echo "  Electron : $(node -p "require('./desktop/node_modules/electron/package.json').version")"
echo "  Double-cliquer dessus dans le Finder ou Launchpad, ou la glisser dans le Dock."
