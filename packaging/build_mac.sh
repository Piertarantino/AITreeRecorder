#!/bin/zsh
# Build Mac: helper nativo + app (PyInstaller) + DMG. Lanciato dalla build su GitHub (macos-14 / macos-13).
set -euo pipefail
cd "${0:A:h}/.."
arch=$(uname -m)                   # arm64 o x86_64
version=${APP_VERSION:-0.4.0}
version=${version#v}

# 1. Helper nativo (audio del Mac + app che usano il microfono), solo per questa architettura
mkdir -p mac/build
swiftc -O -target "$arch-apple-macos14.0" mac/AitreeHelper.swift -o mac/build/aitree-helper
codesign --force --sign - --identifier it.aitree.helper mac/build/aitree-helper

# 2. ffmpeg/ffprobe statici (con libopus, libx264, VideoToolbox)
mkdir -p vendor
if [[ ! -x vendor/ffmpeg ]]; then
  m=$([[ $arch == arm64 ]] && echo arm64 || echo amd64)
  for tool in ffmpeg ffprobe; do
    curl -fL "https://ffmpeg.martin-riedl.de/redirect/latest/macos/$m/release/$tool.zip" -o vendor/$tool.zip \
      || curl -fL "https://evermeet.cx/ffmpeg/getrelease/$([[ $tool == ffprobe ]] && echo ffprobe/)zip" -o vendor/$tool.zip
    unzip -o vendor/$tool.zip -d vendor >/dev/null
  done
  chmod +x vendor/ffmpeg vendor/ffprobe
fi
vendor/ffmpeg -hide_banner -encoders | grep -E "libopus|libx264|videotoolbox"

# 3. App
python packaging/make_icon.py packaging/icon.png
pyinstaller ${(f)"$(cat packaging/pyinstaller_common.txt)"} --icon packaging/icon.png \
  --osx-bundle-identifier it.aitree.recorder \
  --add-binary "vendor/ffmpeg:bin" --add-binary "vendor/ffprobe:bin" \
  --add-binary "mac/build/aitree-helper:bin" app.py
app="dist/AI Tree Recorder.app"
plist="$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Serve per registrare la tua voce durante le call.'" "$plist"
/usr/libexec/PlistBuddy -c "Add :NSAudioCaptureUsageDescription string 'Serve per registrare la voce degli altri partecipanti alla call.'" "$plist"
/usr/libexec/PlistBuddy -c "Add :NSScreenCaptureUsageDescription string 'Serve per registrare lo schermo della call.'" "$plist" || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$plist"
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 14.0" "$plist" || true
codesign --force --deep --sign - "$app"

# 4. Controllo dell'app impacchettata
"$app/Contents/MacOS/AI Tree Recorder" selftest selftest.txt || { cat selftest.txt; exit 1; }
cat selftest.txt

# 5. DMG con collegamento ad Applicazioni
rm -rf dist/dmg && mkdir -p dist/dmg
cp -R "$app" dist/dmg/
ln -s /Applications dist/dmg/Applicazioni
name=$([[ $arch == arm64 ]] && echo "Apple-Silicon" || echo "Intel")
hdiutil create -volname "AI Tree Recorder" -srcfolder dist/dmg -ov -format UDZO "dist/AI-Tree-Recorder-$version-Mac-$name.dmg"
ls -la dist/*.dmg
