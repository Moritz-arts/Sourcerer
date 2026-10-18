; The Windows installer, compiled by build.py (Inno Setup 6): Sourcerer-Setup.exe.
;
; Per user, no admin rights: it lands in %LOCALAPPDATA%\Programs\Sourcerer (or where the user says),
; which the user may write to. The program is ONE file, Sourcerer.exe; Userdata\ -- the user's cards,
; logins and downloads -- is made beside it on the first start and is never touched, here or by the
; uninstaller.
;
; Installing a newer version over an older one IS the update, and it is what Settings > Updates runs
; (silently) in an installed copy. The new Sourcerer.exe replaces the old one. Up to v0.21 the
; program was a folder, Sourcerer_files\, with Userdata inside it: [Code] moves that Userdata out
; beside the executable and clears the rest of the old folder. Only that one folder of ours is
; ever cleared -- never the install folder itself, which a user may have pointed at anything.
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
Source: "{#Exe}"; DestDir: "{app}"; Flags: ignoreversion

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

function InitializeSetup: Boolean;
var
  Dir, Exe: String;
  Limit, Waited: Integer;
begin
  Result := True;
  { The in-app update runs this Setup while Sourcerer is still going down (v0.25 and older: at once, and
    the program quits seconds later). Setup then meets a program on its way out, its restart manager
    sits on "Closing applications..." and rolls the update back. So Setup waits itself: while the
    installed Sourcerer.exe refuses to be opened for writing (a running program does), up to /WAIT
    seconds (60). It never forces the program closed: when it stays open Setup stops, exit code 1,
    and the update is not run. Only for that silent start (/START=1) -- started by hand, Setup asks
    the user to close Sourcerer as usual. }
  if not (WizardSilent and (ExpandConstant('{param:START|0}') = '1')) then
    Exit;
  if not RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6C1F6B7A-5D0E-4B27-9C54-0D9A4A6E51B3}_is1',
                             'Inno Setup: App Path', Dir) then
    Exit;
  Exe := AddBackslash(Dir) + 'Sourcerer.exe';
  Limit := StrToIntDef(ExpandConstant('{param:WAIT|60}'), 60);
  Waited := 0;
  while Waited < Limit do
  begin
    if not FileExists(Exe) then
      Break;
    if SaveStringToFile(Exe, '', True) then   { appends nothing; fails while the program runs }
      Break;
    Sleep(1000);
    Waited := Waited + 1;
  end;
  if Waited > 0 then
    Log(Format('waited %d s for Sourcerer.exe to close', [Waited]));
  if FileExists(Exe) and not SaveStringToFile(Exe, '', True) then
  begin
    Log('Sourcerer.exe is still in use; Setup does not force it closed');
    Result := False;
  end;
end;

procedure RetireOldProgramFolder;
var
  Old, Mine: String;
  Found: TFindRec;
begin
  Old := ExpandConstant('{app}\Sourcerer_files');
  Mine := ExpandConstant('{app}\Userdata');
  if not DirExists(Old) then
    Exit;
  { The user's data first: beside the executable, where this version looks for it. If that cannot
    be done it stays where it is, and Sourcerer still finds it there. }
  if DirExists(Old + '\Userdata') and not DirExists(Mine) then
    RenameFile(Old + '\Userdata', Mine);
  if FindFirst(Old + '\*', Found) then
  begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') and (CompareText(Found.Name, 'Userdata') <> 0) then
        begin
          if (Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            DelTree(Old + '\' + Found.Name, True, True, True)
          else
            DeleteFile(Old + '\' + Found.Name);
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
  RemoveDir(Old);   { only when empty: a Userdata that could not be moved keeps its folder }
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { ssInstall: the running Sourcerer is closed, the new file is not copied yet. }
  if CurStep = ssInstall then
    RetireOldProgramFolder;
end;
