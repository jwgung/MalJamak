; Inno Setup 설치 파일: iscc /DAppVersion=0.1.0 packaging\installer.iss
; 사용자 폴더에 설치해 관리자 권한이 필요 없다 (자동 실행도 HKCU 에 등록하므로 맞춘다).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{120A0149-7D22-43BA-8F9C-5A4CC679EF1B}
AppName=말자막
AppVersion={#AppVersion}
AppPublisher=jwgung
DefaultDirName={localappdata}\Programs\MalJamak
; 예전 이름(Voice Keyboard)과 같은 AppId 라 업그레이드로 잡히지만, 예전 폴더 대신 새 폴더에 깐다.
UsePreviousAppDir=no
DefaultGroupName=말자막
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MalJamak-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\MalJamak.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
#if FileExists(CompilerPath + "Languages\Korean.isl")
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; Flags: unchecked

[InstallDelete]
; 예전 이름(Voice Keyboard, v0.8 이전) 설치본과 바로가기를 지운다. 설정 폴더는 앱이 처음 뜰 때 옮긴다.
Type: filesandordirs; Name: "{localappdata}\Programs\VoiceKeyboard"
Type: filesandordirs; Name: "{autoprograms}\Voice Keyboard"
Type: files; Name: "{autodesktop}\Voice Keyboard.lnk"

[Files]
Source: "..\dist\MalJamak\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\말자막"; Filename: "{app}\MalJamak.exe"
Name: "{autodesktop}\말자막"; Filename: "{app}\MalJamak.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MalJamak.exe"; Description: "말자막 실행"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM MalJamak.exe /F"; Flags: runhidden; RunOnceId: "KillApp"

[Registry]
; 예전 이름의 자동 실행 항목은 지운다 (설정에서 켜 두었으면 앱이 새 이름으로 다시 등록한다).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VoiceKeyboard"; Flags: deletevalue dontcreatekey
; 설정에서 켠 자동 실행 항목을 제거할 때 지운다.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "MalJamak"; Flags: uninsdeletevalue dontcreatekey

[Code]
// 예전 이름으로 실행 중인 앱을 닫아야 예전 설치 폴더를 지울 수 있다.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM VoiceKeyboard.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
