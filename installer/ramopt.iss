; ============================================================================
;  RAM Optimizer Service — Inno Setup 6 script
;
;  Build:  iscc installer\ramopt.iss        (after build_exe.bat)
;  Output: installer\Output\RamOptimizerService-<version>-setup.exe
;
;  Why an installer instead of just two .bat files:
;    * upgrades work (old service stopped and removed before copying files)
;    * uninstall removes the service, the Event Log source and the data folder
;    * the SmartScreen prompt is at least attached to a named program
; ============================================================================

#define AppName        "RAM Optimizer Service"
#define AppShortName   "RamOptimizer"
#define AppVersion     "2.0.0"
#define AppPublisher   "Behnam Ehsani"
#define ServiceName    "RamOptimizerService"
#define AppURL         "https://github.com/wrappedman/Ram-Optimizer-Service"
#define SourceDir      "..\release"

[Setup]
AppId={{B2E9B0E4-7C0E-4C2B-9B7B-1D5E6C0A2F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
OutputDir=Output
OutputBaseFilename={#AppShortName}Service-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
LicenseFile=..\LICENSE
Uninstallable=yes
; SignTool=signtool  (فعال کنید اگر گواهی کد امضا دارید — به بخش امضای کد در README مراجعه کنید)

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fa"; MessagesFile: "compiler:Languages\Farsi.isl"

[Tasks]
Name: "conffile"; Description: "Create the default configuration file"; GroupDescription: "Configuration:"

[Files]
Source: "{#SourceDir}\RamOptimizerService\*"; DestDir: "{app}\RamOptimizerService"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "{#SourceDir}\README.en.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\SHA256SUMS.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#SourceDir}\config.ini.example"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Run]
; Write a default config before the service starts (harmless if it already exists)
Filename: "{app}\RamOptimizerService\RamOptimizerService.exe"; Parameters: "config --init"; Flags: runhidden; Tasks: conffile
; Install + start the service
Filename: "{app}\RamOptimizerService\RamOptimizerService.exe"; Parameters: "service install --wait 30"; Flags: runhidden; StatusMsg: "Installing the Windows service..."
Filename: "{app}\RamOptimizerService\RamOptimizerService.exe"; Parameters: "test --dry-run"; Flags: runhidden; Description: "Verify the installation now"; Verb: "RunDryRun"

[UninstallRun]
; Stop + remove the service before files disappear
Filename: "{app}\RamOptimizerService\RamOptimizerService.exe"; Parameters: "service remove --wait 25"; Flags: runhidden; RunOnceId: "RemoveService"

[UninstallDelete]
; Logs, status and configuration. Comment out the first two lines to keep
; the log while uninstalling.
Type: filesandordirs; Name: "{commonappdata}\{#AppShortName}"
Type: files; Name: "{app}\LICENSE"
Type: dirifempty; Name: "{app}"

[Code]
// --- Upgrades: stop and remove any previous service -------------------------
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop {#ServiceName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Sleep(3000);
  Exec(ExpandConstant('{sys}\sc.exe'), 'delete {#ServiceName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
