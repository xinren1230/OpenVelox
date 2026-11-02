#define AppName "OpenVelox"
#define AppVersion "0.5.0"
[Setup]
AppId={{6E0F4B7A-3C2D-4E8B-9A51-0B7E2C9F1D33}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Xinren Chen
AppPublisherURL=https://github.com/xinren1230/OpenVelox
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OpenVelox-Setup-{#AppVersion}
SetupIconFile=..\openvelox\resources\openvelox.ico
UninstallDisplayIcon={app}\OpenVelox.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
[Files]
Source: "..\OpenVelox.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\OpenVelox.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\OpenVelox.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Classes\.emd\OpenWithProgids"; ValueType: string; ValueName: "OpenVelox.emd"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\OpenVelox.emd\shell\open\command"; ValueType: string; ValueData: """{app}\OpenVelox.exe"" ""%1"""; Flags: uninsdeletekey
[Run]
Filename: "{app}\OpenVelox.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
