#!/bin/zsh
# Compila aitree-helper (audio del Mac + app che usano il microfono).
# Serve solo: xcode-select --install
set -euo pipefail
here=${0:A:h}
mkdir -p "$here/build"
out="$here/build/aitree-helper"
for arch in arm64 x86_64; do
  swiftc -O -target "$arch-apple-macos14.0" "$here/AitreeHelper.swift" -o "$out-$arch"
done
lipo -create "$out-arm64" "$out-x86_64" -output "$out"
rm -f "$out-arm64" "$out-x86_64"
codesign --force --sign - --identifier it.aitree.helper "$out"
echo "Pronto: $out"
