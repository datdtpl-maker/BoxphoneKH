#ifndef MyAppVersion
  #define MyAppVersion "1.0.25"
#endif

#define MyAppName "BoxPhoneControl"
#define MyAppExeName "BoxPhoneControl.exe"

[Setup]
AppId={{A18BA19E-7F8D-4B85-9B27-AB6DA4B2714C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=BoxPhoneControl
DefaultDirName={autopf}\BoxPhoneControl
DefaultGroupName=BoxPhoneControl
DisableProgramGroupPage=yes
OutputDir=release
OutputBaseFilename=BoxPhoneControl-Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription=Bo cai BoxPhoneControl

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài màn hình Desktop"; GroupDescription: "Lối tắt bổ sung:"; Flags: checkedonce

[Files]
Source: "dist\BoxPhoneControl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\BoxPhoneControl"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\BoxPhoneControl"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở BoxPhoneControl"; Flags: nowait postinstall skipifsilent
