; Installer Windows di AI Tree Recorder (Inno Setup 6). Nessun permesso di amministratore.
#ifndef AppVersion
  #define AppVersion "0.4.1"
#endif

[Setup]
AppId={{8E3B6F1A-4C2D-4E7B-9A51-3C7D2E0A4B11}
AppName=AI Tree Recorder
AppVersion={#AppVersion}
AppPublisher=AI Tree
DefaultDirName={localappdata}\Programs\AI Tree Recorder
DefaultGroupName=AI Tree Recorder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AI-Tree-Recorder-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AI Tree Recorder.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Icona sul desktop"; GroupDescription: "Collegamenti:"
Name: "autostart"; Description: "Avvia insieme a Windows (consigliato per registrare le call in automatico)"; GroupDescription: "Avvio:"

[Files]
Source: "..\dist\AI Tree Recorder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AI Tree Recorder"; Filename: "{app}\AI Tree Recorder.exe"
Name: "{autodesktop}\AI Tree Recorder"; Filename: "{app}\AI Tree Recorder.exe"; Tasks: desktopicon
Name: "{userstartup}\AI Tree Recorder"; Filename: "{app}\AI Tree Recorder.exe"; Tasks: autostart

[Run]
Filename: "{app}\AI Tree Recorder.exe"; Description: "Avvia AI Tree Recorder"; Flags: nowait postinstall skipifsilent
