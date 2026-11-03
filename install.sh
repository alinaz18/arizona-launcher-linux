#!/usr/bin/env bash
# Arizona Launcher for Linux — installer / установщик
#
#   ./install.sh            install dependencies + launcher (asks for sudo password)
#   ./install.sh --no-deps  install only the launcher (dependencies already present)
#   ./install.sh --dry-run  show what would be done, change nothing
#
# Supported: Arch / CachyOS / Manjaro / EndeavourOS, Debian / Ubuntu / Mint / Pop!_OS,
#            Fedora / Nobara, openSUSE. Others: install Python 3, Wine and winetricks manually,
#            then run with --no-deps (PySide6 is installed via pip automatically if missing).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/arizona-launcher-app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
OS_RELEASE="${OS_RELEASE:-/etc/os-release}"

DEPS=1
DRY=0
for arg in "$@"; do
  case "$arg" in
    --no-deps) DEPS=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
run()  { if [ "$DRY" = 1 ]; then printf '    [dry-run] %s\n' "$*"; else "$@"; fi; }
sudo_run() { if [ "$(id -u)" = 0 ]; then run "$@"; else run sudo "$@"; fi; }

# ------------------------------------------------------------------ distro detection
distro_family() {
  local id="" like=""
  if [ -r "$OS_RELEASE" ]; then
    id=$(. "$OS_RELEASE"; echo "${ID:-}")
    like=$(. "$OS_RELEASE"; echo "${ID_LIKE:-}")
  fi
  for x in $id $like; do
    case "$x" in
      arch|cachyos|manjaro|endeavouros|garuda) echo arch; return ;;
      debian|ubuntu|linuxmint|pop|elementary|zorin) echo debian; return ;;
      fedora|nobara|rhel|centos) echo fedora; return ;;
      opensuse*|suse|sles) echo suse; return ;;
    esac
  done
  echo unknown
}

# ------------------------------------------------------------------ dependencies
install_deps() {
  local fam; fam=$(distro_family)
  say "Distribution / дистрибутив: $fam"
  case "$fam" in
    arch)
      sudo_run pacman -S --needed --noconfirm python pyside6 wine winetricks cabextract curl \
        || warn "pacman failed. Update the system (sudo pacman -Syu) and run ./install.sh again."
      ;;
    debian)
      sudo_run dpkg --add-architecture i386
      sudo_run apt-get update
      sudo_run apt-get install -y curl python3 python3-venv python3-pip wine wine64 wine32:i386 \
        || sudo_run apt-get install -y curl python3 python3-venv python3-pip wine
      # PySide6 is packaged only in Debian 13+ / Ubuntu 26.04+; otherwise pip is used below.
      sudo_run apt-get install -y python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
        || warn "PySide6 is not in your repositories — it will be installed via pip."
      # libraries the pip build of Qt needs to open a window
      sudo_run apt-get install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1 || true
      # winetricks: Debian "contrib" / Ubuntu "multiverse"; fallback below downloads it.
      sudo_run apt-get install -y winetricks cabextract || true
      ;;
    fedora)
      sudo_run dnf install -y python3 python3-pyside6 wine winetricks cabextract \
        || sudo_run dnf install -y python3 wine winetricks cabextract
      ;;
    suse)
      sudo_run zypper --non-interactive install python3 python3-pyside6 wine winetricks \
        || sudo_run zypper --non-interactive install python3 wine
      ;;
    *)
      warn "Unknown distribution. Install Python 3, Wine and winetricks with your package manager."
      ;;
  esac
}

# winetricks is a single shell script — if the distro has none, put the upstream one in ~/.local/bin
ensure_winetricks() {
  command -v winetricks >/dev/null 2>&1 && return
  say "Downloading winetricks → $BIN_DIR/winetricks"
  run mkdir -p "$BIN_DIR"
  run curl -fsSL -o "$BIN_DIR/winetricks" \
    https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks \
    || { warn "Could not download winetricks (DXVK install button will not work)."; return; }
  run chmod +x "$BIN_DIR/winetricks"
}

# PySide6: system package if available, otherwise a private venv with pip
PYTHON=python3
ensure_pyside() {
  if python3 -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
    say "PySide6: system package"
    return
  fi
  say "PySide6 not found — installing into $APP_DIR/venv via pip"
  run python3 -m venv "$APP_DIR/venv"
  run "$APP_DIR/venv/bin/pip" install --upgrade pip PySide6
  PYTHON="$APP_DIR/venv/bin/python"
}

# ------------------------------------------------------------------ files
install_files() {
  say "Installing launcher → $APP_DIR"
  run mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
  run install -m 644 "$SRC_DIR/arizona_launcher.py" "$APP_DIR/arizona_launcher.py"
  run install -m 644 "$SRC_DIR/arizona_core.py" "$APP_DIR/arizona_core.py"
  run install -m 644 "$SRC_DIR/data/arizona-launcher.svg" "$ICON_DIR/arizona-launcher.svg"

  local py; py=$(command -v "$PYTHON" || echo "$PYTHON")
  [ -x "$APP_DIR/venv/bin/python" ] && py="$APP_DIR/venv/bin/python"
  if [ "$DRY" = 1 ]; then
    echo "    [dry-run] write $BIN_DIR/arizona-launcher (python: $py)"
    echo "    [dry-run] write $DESKTOP_DIR/arizona-launcher.desktop"
  else
    printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$py" "$APP_DIR/arizona_launcher.py" > "$BIN_DIR/arizona-launcher"
    chmod +x "$BIN_DIR/arizona-launcher"
    # if the icon from the official launcher was already extracted, keep it
    local icon=arizona-launcher
    [ -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps/arizona-launcher-original.png" ] \
      && icon=arizona-launcher-original
    sed -e "s|@BIN@|$BIN_DIR/arizona-launcher|" -e "s|^Icon=.*|Icon=$icon|" \
      "$SRC_DIR/data/arizona-launcher.desktop" > "$DESKTOP_DIR/arizona-launcher.desktop"
  fi
  run update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
}

# ------------------------------------------------------------------ main
[ "$DEPS" = 1 ] && install_deps
ensure_winetricks
ensure_pyside
install_files

command -v wine >/dev/null 2>&1 || warn "Wine is not installed — the game will not start without it."
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not in PATH — start the launcher from the app menu.";; esac
say "Done! Start \"Arizona Launcher\" from the application menu or run: arizona-launcher"
say "Готово! Запустите «Arizona Launcher» из меню приложений или командой: arizona-launcher"
