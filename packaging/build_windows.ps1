# Build Windows: app (PyInstaller) + installer (Inno Setup). Lanciato dalla build su GitHub.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# ffmpeg con libopus, libx264, NVENC, Quick Sync, AMF
New-Item -ItemType Directory -Force vendor | Out-Null
if (-not (Test-Path vendor\ffmpeg.exe)) {
  Invoke-WebRequest https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip -OutFile vendor\ff.zip
  Expand-Archive vendor\ff.zip -DestinationPath vendor\ff -Force
  Copy-Item (Get-ChildItem vendor\ff -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName vendor\
  Copy-Item (Get-ChildItem vendor\ff -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName vendor\
}
& vendor\ffmpeg.exe -hide_banner -encoders | Select-String "libopus|libx264|h264_nvenc"

python packaging\make_icon.py packaging\icon.png packaging\icon.ico
$common = Get-Content packaging\pyinstaller_common.txt
pyinstaller @common --icon packaging\icon.png --hidden-import pystray._win32 `
  --add-binary "vendor\ffmpeg.exe;bin" --add-binary "vendor\ffprobe.exe;bin" app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller non riuscito" }

# Controllo dell'app impacchettata
$p = Start-Process -FilePath "dist\AI Tree Recorder\AI Tree Recorder.exe" -ArgumentList "selftest","selftest.txt" -Wait -PassThru
Get-Content selftest.txt
if ($p.ExitCode -ne 0) { throw "Selftest non superato" }

# Installer
$version = if ($env:APP_VERSION) { $env:APP_VERSION.TrimStart("v") } else { "0.4.0" }
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup non riuscito" }
Get-ChildItem dist\*.exe
