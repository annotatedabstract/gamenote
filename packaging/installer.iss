; Inno Setup script for gamenote.
; Wraps the PyInstaller one-folder build (dist\gamenote) into a single setup.exe
; with a Start-menu shortcut, optional desktop icon, an optional "run at login"
; entry, and an uninstaller. Per-user install by default (no admin needed); the
; user can choose all-users from the privileges dialog.
;
; Build:  packaging\build-installer.sh   (or run ISCC.exe on this file)
; Requires Inno Setup 6:  winget install JRSoftware.InnoSetup

#define MyAppName "gamenote"
; The version is single-sourced from gamenote/__init__.py: every real build
; passes /DMyAppVersion=<version> (build-installer.sh locally, the release and
; dev-build workflows in CI). The fallback below only exists so a bare
; "ISCC installer.iss" still compiles -- into an obviously mislabeled
; installer, never a silently stale version.
#ifndef MyAppVersion
#define MyAppVersion "0.0.0-unset"
#endif
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

[InstallDelete]
; The app payload is replaced wholesale on every install/upgrade. Deleting the
; old _internal tree first means files renamed or removed between versions
; (Python DLLs, collected packages) cannot linger and get loaded by mistake.
; Config and log live in %APPDATA%\gamenote and downloaded models in
; %LOCALAPPDATA%\gamenote, both untouched. A model bundled INSIDE the payload
; (v1.0/v1.1 installs upgraded in place ever since, or a hand-pre-bundled
; offline build) is rescued first: MigrateBundledModels below moves it to
; %LOCALAPPDATA%\gamenote\models, where the app loads it offline.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ Move any model folders out of the payload before [InstallDelete] wipes it.
  Same-volume renames, so this is instant even for a ~480 MB model. A child
  that already exists in the destination is left alone (the copy there wins);
  a failed rename just means the app re-downloads the model on next launch. }
procedure MigrateBundledModels();
var
  FindRec: TFindRec;
  Src, DestRoot, SrcChild, DestChild: string;
begin
  Src := ExpandConstant('{app}\_internal\models');
  if not DirExists(Src) then
    exit;
  DestRoot := ExpandConstant('{localappdata}\gamenote\models');
  ForceDirectories(DestRoot);
  if FindFirst(Src + '\*', FindRec) then begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          SrcChild := Src + '\' + FindRec.Name;
          DestChild := DestRoot + '\' + FindRec.Name;
          if not DirExists(DestChild) and not FileExists(DestChild) then
            RenameFile(SrcChild, DestChild);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { ssInstall fires just before installation starts, i.e. before the
    InstallDelete entries are processed. }
  if CurStep = ssInstall then
    MigrateBundledModels();
end;

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
