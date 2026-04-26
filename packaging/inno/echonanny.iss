#define MyAppName "EchoNanny"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "EchoNanny"
#define MyAppExeName "echonanny.exe"
#ifndef MyDistDir
  #define MyDistDir "..\pyinstaller\dist\echonanny"
#endif

[Setup]
AppId={{A7C13E5D-6E3C-4548-A300-6F17D07A5B6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=EchoNanny-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "{#MyDistDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName} Server"; Filename: "{app}\{#MyAppExeName}"; Parameters: "serve --env-file ""{localappdata}\EchoNanny\.env"""; WorkingDir: "{app}"
Name: "{autoprograms}\{#MyAppName} Init Config"; Filename: "{app}\{#MyAppExeName}"; Parameters: "init-env"; WorkingDir: "{localappdata}\EchoNanny"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "init-env"; WorkingDir: "{localappdata}\EchoNanny"; Flags: postinstall skipifsilent runhidden

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    ForceDirectories(ExpandConstant('{localappdata}\EchoNanny'));
  end;
end;
