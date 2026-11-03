#!/usr/bin/env bash
# Build dist/arizona-launcher-<version>-1.noarch.rpm (needs rpmbuild).
#   packaging/build-rpm.sh <version>
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="${1:?version required}"
TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT

mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}
tar -C "$SRC" --exclude=.git --exclude=dist --transform "s|^\.|arizona-launcher-$VER|" \
    -czf "$TOP/SOURCES/arizona-launcher-$VER.tar.gz" .
rpmbuild -bb --define "_topdir $TOP" --define "pkg_version $VER" --define "dist %{nil}" \
    "$SRC/packaging/arizona-launcher.spec"
mkdir -p "$SRC/dist"
cp "$TOP"/RPMS/noarch/*.rpm "$SRC/dist/"
