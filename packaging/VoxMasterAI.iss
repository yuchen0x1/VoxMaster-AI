#define ProductVersion "0.1.1"
[Setup]
AppId={{88A1E9AC-B8AB-4BB9-B1B8-FC4046736E24}
AppName=VoxMaster AI
AppVersion={#ProductVersion}
VersionInfoVersion={#ProductVersion}.0
VersionInfoProductVersion={#ProductVersion}.0
DefaultDirName={localappdata}\Programs\VoxMaster AI
DefaultGroupName=VoxMaster AI
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VoxMasterAI-Setup
UninstallDisplayIcon={app}\VoxMasterAI.exe
SetupIconFile=VoxMasterAI.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
[Files]
Source: "..\dist\VoxMasterAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Icons]
Name: "{group}\VoxMaster AI"; Filename: "{app}\VoxMasterAI.exe"
[Run]
Filename: "{app}\VoxMasterAI.exe"; Description: "{cm:LaunchProgram,VoxMaster AI}"; Flags: postinstall nowait skipifsilent
