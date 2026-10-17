; The Windows installer, compiled by build.py (Inno Setup 6): Sourcerer-Setup.exe.
;
; Per user, no admin rights: it lands in %LOCALAPPDATA%\Programs\Sourcerer, which the user may
; write to -- Userdata\ lives inside (Sourcerer_files\Userdata), as in the portable zip.
; Installing a newer version over an older one is the update, and it never touches Userdata;
; neither does the uninstaller (a user's cards, logins and downloads are not ours to delete).
#ifndef Version
  #define Version "0"
#endif

[Setup]
AppId={{6C1F6B7A-5D0E-4B27-9C54-0D9A4A6E51B3}
AppName=Sourcerer
AppVersion={#Version}
AppPublisher=Moritz-arts
AppPublisherURL=https://github.com/Moritz-arts/Sourcerer
DefaultDirName={autopf}\Sourcerer
DefaultGroupName=Sourcerer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Sourcerer-Setup
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\Sourcerer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; A running Sourcerer holds its files: ask Windows' restart manager to close it.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Sourcerer"; Filename: "{app}\Sourcerer.exe"
Name: "{autodesktop}\Sourcerer"; Filename: "{app}\Sourcerer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Sourcerer.exe"; Description: "Start Sourcerer"; Flags: nowait postinstall skipifsilent
