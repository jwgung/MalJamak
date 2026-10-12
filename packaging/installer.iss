; Inno Setup 설치 파일: iscc /DAppVersion=0.1.0 packaging\installer.iss
; 사용자 폴더에 설치해 관리자 권한이 필요 없다 (자동 실행도 HKCU 에 등록하므로 맞춘다).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{120A0149-7D22-43BA-8F9C-5A4CC679EF1B}
AppName=Voice Keyboard
AppVersion={#AppVersion}
AppPublisher=jwgung
DefaultDirName={localappdata}\Programs\VoiceKeyboard
DefaultGroupName=Voice Keyboard
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VoiceKeyboard-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\VoiceKeyboard.exe
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

[Files]
Source: "..\dist\VoiceKeyboard\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Voice Keyboard"; Filename: "{app}\VoiceKeyboard.exe"
Name: "{autodesktop}\Voice Keyboard"; Filename: "{app}\VoiceKeyboard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VoiceKeyboard.exe"; Description: "Voice Keyboard 실행"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM VoiceKeyboard.exe /F"; Flags: runhidden; RunOnceId: "KillApp"

[Registry]
; 설정에서 켠 자동 실행 항목을 제거할 때 지운다.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VoiceKeyboard"; Flags: uninsdeletevalue dontcreatekey
