#define MyAppName "MoM Relive (Unofficial Community Toolkit)"
#ifndef MyAppVersion
  #define MyAppVersion "0.8.7"
#endif
#define MyAppExeName "MoMRevival.exe"

[Setup]
AppId={{D976685B-497C-4437-A511-E2C7A38F8C36}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=MoM Relive Community Project
AppPublisherURL=https://github.com/drbermejor/MoM-Relive
AppSupportURL=https://github.com/drbermejor/MoM-Relive/issues
AppUpdatesURL=https://github.com/drbermejor/MoM-Relive/releases
VersionInfoDescription=Unofficial community compatibility toolkit
VersionInfoCompany=MoM Relive Community Project
VersionInfoCopyright=Copyright (C) 2026 David Bermejo and contributors
LicenseFile=..\LICENSE
InfoBeforeFile=..\LEGAL.md
DefaultDirName={localappdata}\Programs\MoMRevival
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MoMRevivalSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\dist\MoMClientLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: client
Source: "..\dist\MoMServerManager.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: server
Source: "..\dist\MoMNativeServer.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: server
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LEGAL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\COPYRIGHT"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Types]
Name: "full"; Description: "Client and dedicated server"
Name: "clientonly"; Description: "Client only"
Name: "serveronly"; Description: "Dedicated server only"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "client"; Description: "Client: reversible community compatibility launcher"; Types: full clientonly
Name: "server"; Description: "Server: replacement backend and management panel"; Types: full serveronly

[Icons]
Name: "{group}\MoM Revival Client"; Filename: "{app}\{#MyAppExeName}"; Components: client
Name: "{group}\Server Manager"; Filename: "{app}\MoMServerManager.exe"; Components: server
Name: "{group}\Native Server (console)"; Filename: "{app}\MoMNativeServer.exe"; WorkingDir: "{app}"; Components: server
Name: "{group}\Legal notice"; Filename: "{app}\LEGAL.md"
Name: "{group}\Project licence"; Filename: "{app}\LICENSE"
Name: "{group}\Third-party notices"; Filename: "{app}\THIRD-PARTY-NOTICES.md"
Name: "{autodesktop}\MoM Revival Client"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Components: client
Name: "{autodesktop}\MoM Server Manager"; Filename: "{app}\MoMServerManager.exe"; Tasks: managerdesktopicon; Components: server

[Tasks]
Name: "desktopicon"; Description: "Create a client desktop shortcut"; GroupDescription: "Shortcuts:"; Components: client
Name: "managerdesktopicon"; Description: "Create a server manager desktop shortcut"; GroupDescription: "Shortcuts:"; Components: server

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Configure the client"; Flags: nowait postinstall skipifsilent shellexec; Components: client
Filename: "{app}\MoMServerManager.exe"; Description: "Open the server manager"; Flags: nowait postinstall skipifsilent shellexec unchecked; Components: server
