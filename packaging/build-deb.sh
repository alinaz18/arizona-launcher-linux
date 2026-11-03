#!/usr/bin/env bash
# Build dist/arizona-launcher_<version>_all.deb (needs dpkg-deb).
#   packaging/build-deb.sh <version>
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="${1:?version required}"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

"$SRC/packaging/stage.sh" "$ROOT"
# Debian keeps the license in /usr/share/doc/<pkg>/copyright
mv "$ROOT/usr/share/licenses/arizona-launcher/LICENSE" "$ROOT/usr/share/doc/arizona-launcher/copyright"
rm -rf "$ROOT/usr/share/licenses"

mkdir -p "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: arizona-launcher
Version: $VER
Section: games
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets, wine
Recommends: winetricks, cabextract, wine32
Maintainer: bagira818 <noreply@github.com>
Homepage: https://github.com/alinaz18/arizona-launcher-linux
Description: Unofficial Arizona RP / Rodina RP launcher for Linux
 Native Qt launcher for Arizona RP, Rodina RP and Village Life: server list,
 game install, updates and repair from the official servers, mod catalog
 and news. The Windows game itself runs through a Wine prefix managed by
 the launcher. Not affiliated with Arizona Games.
EOF
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

mkdir -p "$SRC/dist"
dpkg-deb --root-owner-group --build "$ROOT" "$SRC/dist/arizona-launcher_${VER}_all.deb"
