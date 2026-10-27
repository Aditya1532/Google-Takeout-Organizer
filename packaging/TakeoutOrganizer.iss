#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B236B5DD-D6D8-48E8-A62E-89D5E79E88A1}
AppName=Takeout Organizer
AppVersion={#AppVersion}
AppPublisher=Takeout Organizer Contributors
DefaultDirName={localappdata}\Programs\Takeout Organizer
DefaultGroupName=Takeout Organizer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TakeoutOrganizer-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Takeout Organizer
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\TakeoutOrganizer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; DestName: "Getting Started.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Takeout Organizer"; Filename: "{app}\TakeoutOrganizer.exe"
Name: "{autodesktop}\Takeout Organizer"; Filename: "{app}\TakeoutOrganizer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\TakeoutOrganizer.exe"; Description: "Launch Takeout Organizer"; Flags: postinstall nowait skipifsilent
