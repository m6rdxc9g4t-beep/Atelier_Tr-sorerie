#!/bin/bash
# Variante « navigateur » : crée un lanceur « Atelier Trésorerie.app » qui démarre le serveur en
# arrière-plan et ouvre l'interface dans le navigateur (bouton « Quitter » dans la barre latérale).
#
# L'application recommandée est l'application de bureau (fenêtre native) :
#     bash scripts/macos/install-desktop.sh
#
# Usage de cette variante, depuis le dossier du projet :
#     bash scripts/macos/install-launcher.sh
#
# L'application est installée dans /Applications (ou ~/Applications si ce dossier n'est
# pas accessible en écriture). À relancer si vous déplacez le dossier du projet ou si
# vous changez d'installation de Python.
set -euo pipefail

APP_NAME="Atelier Trésorerie"
BUNDLE_ID="fr.atelier-tresorerie.app"

if [ "$(uname)" != "Darwin" ]; then
  echo "Ce script est réservé à macOS." >&2
  exit 1
fi

cd "$(dirname "$0")/../.."
PROJECT_DIR="$(pwd)"

# Python utilisé dans ce terminal (une application lancée par double-clic ne connaît pas
# le PATH du terminal : on enregistre donc son chemin complet).
PYTHON="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON" ]; then
  echo "Python est introuvable. Installez-le, puis relancez ce script." >&2
  exit 1
fi
PYTHON="$("$PYTHON" -c 'import sys; print(sys.executable)')"
if ! "$PYTHON" -c "import flask, openpyxl" 2>/dev/null; then
  echo "Il manque des dépendances pour $PYTHON. Lancez d'abord :" >&2
  echo "    \"$PYTHON\" -m pip install -r requirements.txt" >&2
  exit 1
fi
PORT="$("$PYTHON" -c 'from config import Config; print(Config.PORT)')"

DEST_DIR="/Applications"
if [ ! -w "$DEST_DIR" ]; then
  DEST_DIR="$HOME/Applications"
  mkdir -p "$DEST_DIR"
fi
APP="$DEST_DIR/$APP_NAME.app"

echo "→ Création de « $APP »"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ---------------------------------------------------------------- icône (.icns)
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ICONSET="$TMP_DIR/AppIcon.iconset"
mkdir "$ICONSET"
SOURCE_ICON="$PROJECT_DIR/static/img/icon-1024.png"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$SOURCE_ICON" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

# ---------------------------------------------------------------- Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>atelier</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# ---------------------------------------------------------------- lanceur
{
  echo '#!/bin/bash'
  echo '# Lanceur généré par scripts/macos/install-launcher.sh : ne pas modifier à la main.'
  printf 'PROJECT=%q\n' "$PROJECT_DIR"
  printf 'PYTHON=%q\n' "$PYTHON"
  printf 'PORT=%q\n' "$PORT"
  cat <<'LAUNCHER'
URL="http://127.0.0.1:$PORT"
LOG="$HOME/Library/Logs/Atelier Tresorerie.log"

alert() {
  osascript -e "display alert \"Atelier Trésorerie\" message \"$1\" as critical" >/dev/null 2>&1 || true
}
running() {
  curl -fsS --max-time 1 "$URL/api/ping" 2>/dev/null | grep -q atelier-tresorerie
}

# Déjà lancée : on ouvre simplement le navigateur
if running; then
  open "$URL"
  exit 0
fi

if [ ! -f "$PROJECT/app.py" ]; then
  alert "Dossier du projet introuvable : $PROJECT. Relancez scripts/macos/install-launcher.sh depuis le nouveau dossier."
  exit 1
fi
if [ ! -x "$PYTHON" ]; then
  alert "Python introuvable : $PYTHON. Relancez scripts/macos/install-launcher.sh."
  exit 1
fi
if curl -fsS --max-time 1 "$URL" >/dev/null 2>&1; then
  alert "Le port $PORT est déjà utilisé par un autre programme. Changez PORT dans le fichier .env du projet, puis relancez scripts/macos/install-launcher.sh."
  exit 1
fi

mkdir -p "$(dirname "$LOG")"
echo "=== Démarrage $(date) ===" >> "$LOG"
cd "$PROJECT" || exit 1
nohup "$PYTHON" app.py --app-mode >> "$LOG" 2>&1 &

# Attend que le serveur réponde (15 s au maximum), puis ouvre le navigateur
for _ in $(seq 1 60); do
  sleep 0.25
  if running; then
    open "$URL"
    exit 0
  fi
done
alert "Le serveur n'a pas démarré. Le journal va s'ouvrir pour voir l'erreur."
open -a Console "$LOG"
exit 1
LAUNCHER
} > "$APP/Contents/MacOS/atelier"
chmod +x "$APP/Contents/MacOS/atelier"

# Rafraîchit l'icône dans le Finder et le Dock
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1 || true

echo "✓ Application créée : $APP"
echo "  Projet : $PROJECT_DIR"
echo "  Python : $PYTHON"
echo
echo "Double-cliquez dessus (Launchpad, Spotlight ou dossier Applications)."
echo "Astuce : glissez-la dans le Dock pour la garder sous la main."
