; The Windows installer, compiled by build.py (Inno Setup 6): Sourcerer-Setup.exe.
;
; Per user, no admin rights: it lands in %LOCALAPPDATA%\Programs\Sourcerer (or where the user
; says), which the user may write to -- Userdata\ lives inside (Sourcerer_files\Userdata), as in
; the portable zip.
;
; Installing a newer version over an older one IS the update, and it is what Settings > Updates
; runs (silently) in an installed copy. Inno never removes a file the new version no longer has,
; so [Code] clears the program's folder first -- everything in Sourcerer_files except Userdata,
; which holds the user's cards, logins and downloads and is never touched, here or by the
; uninstaller.
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
; Per user only: Userdata lives in the program's folder and has to stay writable.
PrivilegesRequired=lowest
MinVersion=10.0
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

[Languages]
; English only -- the interface is English everywhere, whatever Windows' language is.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Sourcerer"; Filename: "{app}\Sourcerer.exe"
Name: "{autodesktop}\Sourcerer"; Filename: "{app}\Sourcerer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Sourcerer.exe"; Description: "Start Sourcerer"; Flags: nowait postinstall skipifsilent
; The in-app update runs this setup silently with /START=1 and wants Sourcerer back afterwards.
Filename: "{app}\Sourcerer.exe"; Parameters: "--restart"; Flags: nowait; Check: StartAfterSilentUpdate

[Code]
function StartAfterSilentUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:START|0}') = '1');
end;

procedure CleanProgramFolder;
var
  Dir: String;
  Found: TFindRec;
begin
  Dir := ExpandConstant('{app}\Sourcerer_files');
  if not DirExists(Dir) then
    Exit;
  if FindFirst(Dir + '\*', Found) then
  begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') and (CompareText(Found.Name, 'Userdata') <> 0) then
        begin
          if (Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            DelTree(Dir + '\' + Found.Name, True, True, True)
          else
            DeleteFile(Dir + '\' + Found.Name);
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { ssInstall: the running Sourcerer is closed, the new files are not copied yet. }
  if CurStep = ssInstall then
    CleanProgramFolder;
end;
