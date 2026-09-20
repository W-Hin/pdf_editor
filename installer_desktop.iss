#define MyAppName "PDF Editor (Desktop)"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "W-Hin"
#define MyAppURL "https://github.com/W-Hin/pdf_editor"
#define MyAppExeName "PDFEditorDesktop.exe"

[Setup]
; Keep this GUID stable across releases — it's how Inno Setup recognizes
; "this is an upgrade of the same app" and installs in-place over an
; existing install rather than side-by-side. It is deliberately different
; from installer.iss's (the web app) so the two can be installed together.
AppId={{6B0B0D0A-3C4E-4E86-9C1B-7D2F5A8E4C31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; No admin rights required — installs to the current user's own profile.
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=PDFEditorDesktopSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\PDFEditorDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
