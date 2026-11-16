; Tool-Hub – Setup und Deinstallation (Inno Setup 6)
; Bauen: installer\build.ps1   (baut erst dist\ToolHub mit PyInstaller, dann dieses Setup)
;
; Ohne Administratorrechte. Einstellungen und Zwischenspeicher liegen unter %LOCALAPPDATA%\Tool-Hub,
; der GitHub-Token in der Windows-Anmeldeinformationsverwaltung.
; Stilles Setup:  Tool-Hub-Setup-x.y.z.exe /VERYSILENT [/DIR="D:\Tool-Hub"] [/RESTARTAPP=1]

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist"
#endif

[Setup]
AppId={{D20DF06A-8A66-404D-8223-A3EB9DA11486}
AppName=Tool-Hub
AppVersion={#AppVersion}
AppVerName=Tool-Hub {#AppVersion}
AppPublisher=phillhf
AppPublisherURL=https://github.com/phillhf/tool-hub
AppSupportURL=https://github.com/phillhf/tool-hub/issues
AppUpdatesURL=https://github.com/phillhf/tool-hub/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Tool-Hub Setup
DefaultDirName=C:\Tools\Tool-Hub
AppendDefaultDirName=no
DirExistsWarning=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#DistDir}
OutputBaseFilename=Tool-Hub-Setup-{#AppVersion}
SetupIconFile=app.ico
WizardStyle=modern
LicenseFile=..\LICENSE
UninstallDisplayName=Tool-Hub
UninstallDisplayIcon={app}\ToolHub.exe
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.Welcome=Dieses Setup installiert Tool-Hub {#AppVersion}.%n%nTool-Hub installiert, startet, aktualisiert und entfernt die Tools von github.com/phillhf. Private Tools lassen sich mit einem GitHub-Token freischalten.%n%nEs werden keine Administratorrechte benötigt.
en.Welcome=This setup installs Tool-Hub {#AppVersion}.%n%nTool-Hub installs, starts, updates and removes the tools from github.com/phillhf. Private tools can be unlocked with a GitHub token.%n%nNo administrator rights are required.
de.DesktopIcon=Verknüpfung auf dem Desktop anlegen
en.DesktopIcon=Create a desktop shortcut
de.Shortcuts=Zusätzliche Verknüpfungen:
en.Shortcuts=Additional shortcuts:
de.Uninstall=Tool-Hub deinstallieren
en.Uninstall=Uninstall Tool-Hub
de.LaunchNow=Tool-Hub jetzt starten
en.LaunchNow=Start Tool-Hub now
de.DeleteData=Sollen auch die Einstellungen von Tool-Hub und der gespeicherte GitHub-Token gelöscht werden?%n%nDie installierten Tools bleiben in jedem Fall erhalten.
en.DeleteData=Should Tool-Hub's settings and the saved GitHub token be deleted as well?%n%nThe installed tools are kept in any case.

[Messages]
de.WelcomeLabel1=Willkommen bei Tool-Hub
en.WelcomeLabel1=Welcome to Tool-Hub

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:Shortcuts}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\ToolHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Tool-Hub"; Filename: "{app}\ToolHub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Tool-Hub"; Filename: "{app}\ToolHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ToolHub.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchNow}"; Flags: postinstall nowait skipifsilent
Filename: "{app}\ToolHub.exe"; WorkingDir: "{app}"; Flags: nowait; Check: RestartAfterSilentUpdate

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption := CustomMessage('Welcome');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // Update aus Tool-Hub heraus: laufendes Tool-Hub beenden, damit die Dateien ersetzt werden können
  if WizardSilent() then
  begin
    Sleep(1500);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM ToolHub.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(500);
  end;
  Result := '';
end;

function RestartAfterSilentUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RESTARTAPP|0}') = '1');
end;

var
  DeleteData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  DeleteData := False;
  if not UninstallSilent() then
    DeleteData := MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if (CurUninstallStep = usPostUninstall) and DeleteData then
  begin
    DelTree(ExpandConstant('{localappdata}\Tool-Hub'), True, True, True);
    Exec(ExpandConstant('{sys}\cmdkey.exe'), '/delete:Tool-Hub/github-token', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
