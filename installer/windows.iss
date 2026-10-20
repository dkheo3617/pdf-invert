; Inno Setup 설치 스크립트 (Windows)
#define AppName "PDF 색상반전"
#define AppVersion "2.2.3"
#define AppExe "PDFInvert.exe"

[Setup]
CloseApplications=force
RestartApplications=no
AppId={{6F2B1E57-3C2A-4C1B-9D51-7A1F0B4E2D10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=과사람 서부산
DefaultDirName={localappdata}\Programs\PDFInvert
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PDFInvert-Windows-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; Flags: unchecked
Name: "contextmenu"; Description: "PDF 파일 오른쪽 클릭 메뉴에 'PDF 색상반전' 추가"

[Files]
Source: "..\dist\PDFInvert\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{usersendto}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Registry]
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFInvert"; ValueType: string; ValueName: ""; ValueData: "PDF 색상반전"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFInvert"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFInvert"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFInvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent
; 앱 안에서 자동 업데이트(무인 설치)한 경우 설치 후 바로 다시 실행
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent
