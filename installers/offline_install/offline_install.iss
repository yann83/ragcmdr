; ragcmdr/install.iss
; Inno Setup 6 script for Ragcmdr

#define AppName      "Ragcmdr"
#define AppVersion   "1.0.0"
#define AppPublisher "Ragcmdr"
#define AppURL       "https://github.com/ragcmdr"
#define AppExeName   "ragcmdr.bat"
#define MyLicence "..\..\LICENSE"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
LicenseFile={#MyLicence}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=.\
OutputBaseFilename=ragcmdr-offline-setup-{#AppVersion}
SetupIconFile=..\..\img\ragcmdr.ico
UninstallDisplayIcon=..\..\img\ragcmdr.ico
Compression=lzma2/ultra64
SolidCompression=yes
; Require 64-bit Windows
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Minimum Windows version: Windows 10
MinVersion=10.0
WizardStyle=modern
; Ask for admin rights so we can write to Program Files and add to PATH
PrivilegesRequired=lowest

[Languages]
Name: "french";  MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; --- Python embeddable runtime ---
Source: "..\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs
Source: "..\python\python312._pth"; DestDir: "{app}\python"; Flags: onlyifdoesntexist

; --- pip bootstrap ---
Source: "..\get-pip.py"; DestDir: "{app}"

; --- Application sources ---
Source: "..\..\ragcmdr.py";    DestDir: "{app}"
Source: "..\..\requirements.txt"; DestDir: "{app}"
Source: "..\..\config.json";     DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\run\ragcmdr.cmd";     DestDir: "{app}"
Source: "post_install.bat"; DestDir: "{app}"
Source: "..\..\commands\*";      DestDir: "{app}\commands"; Excludes: "__pycache__,*.pyc";  Flags: recursesubdirs createallsubdirs
Source: "..\..\core\*";          DestDir: "{app}\core";     Excludes: "__pycache__,*.pyc";  Flags: recursesubdirs createallsubdirs
Source: "..\..\chat\*";          DestDir: "{app}\chat";     Excludes: "__pycache__,*.pyc";  Flags: recursesubdirs createallsubdirs

; --- Pre-downloaded packages (offline install) ---
Source: "..\packages\*"; DestDir: "{app}\packages"; Flags: recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\collections"
Name: "{app}\output"

[Run]
; This runs post_install.bat after all files are copied.
; StatusMsg is shown in the installer progress window.
;Filename: "{cmd}"; Parameters: "/c ""{app}\post_install.bat"" ""{app}"""; WorkingDir: "{app}"; StatusMsg: "Installing Python dependencies (first run, please wait)..."; Flags: runhidden waituntilterminated
Filename: "{app}\post_install.bat";Parameters: """{app}""";  WorkingDir: "{app}"; StatusMsg: "Installing Python dependencies (first run, please wait)..."; Flags: runasoriginaluser waituntilterminated
; Add ragcmdr to the user PATH so user can type "ragcmdr" from terminal

[Registry]
Root: HKCU; \
    Subkey: "Environment"; \
    ValueType: expandsz; \
    ValueName: "Path"; \
    ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

; Uninstaller � remove the entire installation directory 
[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\commands"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\collections"
Type: filesandordirs; Name: "{app}\output"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\packages"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\commands\__pycache__"
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\chat\__pycache__"
Type: filesandordirs; Name: "{app}\install.log"

[Code]
/// Checks whether Dir is already present in the user PATH (HKCU).
/// Used by the [Registry] section to avoid duplicate entries.
function NeedsAddPath(Dir: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(
    HKEY_CURRENT_USER,
    'Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  // Do not add if already present (case-insensitive check)
  Result := Pos(';' + Uppercase(Dir) + ';',
                ';' + Uppercase(OrigPath) + ';') = 0;
end;

/// Removes AppDir from the user PATH (HKCU) during uninstallation.
/// Called by [UninstallRun] — does not touch the system PATH.
procedure RemoveFromPath(AppDir: string);
var
  OrigPath: string;
  NewPath: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
    exit;

  // Try to remove ;AppDir (trailing semicolons form)
  NewPath := OrigPath;
  P := Pos(';' + Uppercase(AppDir), Uppercase(NewPath));
  if P > 0 then
    Delete(NewPath, P, Length(';' + AppDir));

  // Also try AppDir; (leading semicolons form, e.g. first entry)
  P := Pos(Uppercase(AppDir) + ';', Uppercase(NewPath));
  if P > 0 then
    Delete(NewPath, P, Length(AppDir + ';'));

  if NewPath <> OrigPath then
    RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', NewPath);
end;

/// Called when the installer finishes. Reads install.log and shows an error
/// dialog if post_install.bat reported a failure.
/// LoadStringFromFile requires an AnsiString buffer in Inno Setup 6.
procedure CurStepChanged(CurStep: TSetupStep);
var
  LogPath: string;
  LogContent: AnsiString;
begin
  if CurStep = ssPostInstall then
  begin
    LogPath := ExpandConstant('{app}\install.log');
    if FileExists(LogPath) then
    begin
      LoadStringFromFile(LogPath, LogContent);
      if Pos('[ERROR]', String(LogContent)) > 0 then
        MsgBox(
          'Dependency installation encountered an error.'#13#10 +
          'Please check ' + LogPath + ' for details.',
          mbError, MB_OK);
    end;
  end;
end;

/// Called during uninstallation. Removes the app folder from the user PATH.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;