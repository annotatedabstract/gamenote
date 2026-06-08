; Inno Setup script for gamenote.
; Wraps the PyInstaller one-folder build (dist\gamenote) into a single setup.exe
; with a Start-menu shortcut, optional desktop icon, an optional "run at login"
; entry, and an uninstaller. Per-user install by default (no admin needed); the
; user can choose all-users from the privileges dialog.
;
; Build:  packaging\build-installer.sh   (or run ISCC.exe on this file)
; Requires Inno Setup 6:  winget install JRSoftware.InnoSetup

#define MyAppName "gamenote"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "AnnotatedAbstract"
#define MyAppURL "https://github.com/annotatedabstract/gamenote"
#define MyAppExeName "gamenote.exe"

[Setup]
AppId={{7E7CF2F8-4DFF-467A-871C-563C35512AA4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile=..\gamenote\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=installer_output
OutputBaseFilename=gamenote-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start {#MyAppName} automatically when I log in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The whole one-folder PyInstaller build (exe, _internal, DLLs). No model bundled;
; it downloads on first run.
Source: "..\dist\gamenote\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
