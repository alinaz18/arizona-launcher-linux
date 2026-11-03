#!/usr/bin/env bash
# Lay out the launcher files for a system-wide package (deb / rpm / PKGBUILD).
#   packaging/stage.sh <destdir> [prefix=/usr]
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:?destdir required}"
PREFIX="${2:-/usr}"

install -Dm644 "$SRC/arizona_launcher.py"        "$DEST$PREFIX/share/arizona-launcher/arizona_launcher.py"
install -Dm644 "$SRC/arizona_core.py"            "$DEST$PREFIX/share/arizona-launcher/arizona_core.py"
install -Dm644 "$SRC/data/arizona-launcher.svg"     "$DEST$PREFIX/share/icons/hicolor/scalable/apps/arizona-launcher.svg"
install -Dm644 "$SRC/LICENSE"                    "$DEST$PREFIX/share/licenses/arizona-launcher/LICENSE"
install -Dm644 "$SRC/README.md"                  "$DEST$PREFIX/share/doc/arizona-launcher/README.md"
install -Dm644 "$SRC/README.en.md"               "$DEST$PREFIX/share/doc/arizona-launcher/README.en.md"

install -dm755 "$DEST$PREFIX/bin" "$DEST$PREFIX/share/applications"
cat > "$DEST$PREFIX/bin/arizona-launcher" <<EOF
#!/bin/sh
exec python3 $PREFIX/share/arizona-launcher/arizona_launcher.py "\$@"
EOF
chmod 755 "$DEST$PREFIX/bin/arizona-launcher"
sed "s|@BIN@|arizona-launcher|" "$SRC/data/arizona-launcher.desktop" > "$DEST$PREFIX/share/applications/arizona-launcher.desktop"
chmod 644 "$DEST$PREFIX/share/applications/arizona-launcher.desktop"
