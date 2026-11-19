; Inno Setup script: packs dist\Stem Studio (built by PyInstaller) into one Setup .exe.
; Build with "Build installer.bat". To rename the app, change AppName here and APP_NAME in engine\meta.py.
#define AppName "Stem Studio"
#define AppVersion "1.3.0"
#define AppExe "Stem Studio.exe"

[Setup]
AppId={{2E53FE04-29FF-406F-95D6-9B6402A6C60A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without an admin prompt; the user can still choose "all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename={#AppName} Setup {#AppVersion}
SetupIconFile=stem_studio.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/normal
SolidCompression=yes
LZMAUseSeparateProcess=yes
DiskSpanning=no
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; App settings, log and caches. Your results in Music\{#AppName} are kept.
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
