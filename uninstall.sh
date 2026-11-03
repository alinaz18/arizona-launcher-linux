#!/usr/bin/env bash
# Arizona Launcher — uninstall / удаление
#   ./uninstall.sh          remove the launcher, keep settings, the Wine prefix and the game files
#   ./uninstall.sh --purge  also remove settings and the Wine prefix
#                           (downloaded game files in ~/Games/arizona-launcher are never touched)
set -euo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"

rm -rf "$DATA/arizona-launcher-app"
rm -f "$HOME/.local/bin/arizona-launcher" \
      "$DATA/applications/arizona-launcher.desktop" \
      "$DATA/icons/hicolor/scalable/apps/arizona-launcher.svg" \
      "$DATA"/icons/hicolor/*/apps/arizona-launcher-original.png \
      "$DATA/arizona-launcher/icon-source"
update-desktop-database "$DATA/applications" 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$DATA/arizona-launcher" "$CONF/arizona-launcher" "$CACHE/arizona-launcher"
  echo "Removed launcher, settings and Wine prefix. / Лаунчер, настройки и окружение Wine удалены."
else
  echo "Launcher removed. Settings: $CONF/arizona-launcher, Wine prefix: $DATA/arizona-launcher"
  echo "Лаунчер удалён. Настройки и окружение Wine оставлены (удалить: ./uninstall.sh --purge)."
fi
echo "Game files / файлы игры: ~/Games/arizona-launcher"
