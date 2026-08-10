; Inno Setup script for AIO Runtime Installer.
;
; Builds a real Windows installer around the PyInstaller onedir build in
; dist\AIORuntimeInstaller\ - a Start Menu shortcut + Program Files install
; + uninstaller, replacing "unzip the dist folder yourself." This is a
; plain on-demand desktop app (Start Menu, run occasionally) - deliberately
; no auto-start entry, no scheduled task, no tray icon/background service.
;
; Build with (after `pyinstaller AIORuntimeInstaller.spec --clean` from the
; repo root has produced dist\AIORuntimeInstaller\):
;   "C:\Users\<you>\AppData\Local\Programs\Inno Setup 7\ISCC.exe" installer\AIORuntimeInstaller.iss
; Output lands in dist_installer\AIORuntimeInstaller-Setup-1.0.0.exe (gitignored -
; this script is what's tracked, not the built installer binary).
;
; PrivilegesRequired=admin matches the app's own behavior: AIORuntimeInstaller.exe
; already carries an embedded uac_admin manifest (see AIORuntimeInstaller.spec)
; that makes Windows elevate it on every launch regardless of install
; location, so a standard Program Files install (normally read-only to
; non-elevated processes) is consistent with how the app already runs -
; it always has the access it needs to write its portable .ini/logs next
; to the exe.

#define AppVersion "1.0.0"

[Setup]
AppId={{F6F12F2C-79EC-435A-A140-9D8381D0F40C}
AppName=AIO Runtime Installer
AppVersion={#AppVersion}
AppPublisher=XechostormX
AppPublisherURL=https://github.com/Echo-Storm/AIO_Runtime_Installer
DefaultDirName={autopf}\AIO Runtime Installer
DefaultGroupName=AIO Runtime Installer
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AIORuntimeInstaller.exe
OutputDir=..\dist_installer
OutputBaseFilename=AIORuntimeInstaller-Setup-{#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\AIORuntimeInstaller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu only, deliberately no desktop icon task and no auto-start
; entry - this is a "launch it from the Start Menu every few months"
; utility, not something that should announce itself anywhere else.
Name: "{group}\AIO Runtime Installer"; Filename: "{app}\AIORuntimeInstaller.exe"
Name: "{group}\Uninstall AIO Runtime Installer"; Filename: "{uninstallexe}"

[Run]
; runascurrentuser: without it, Inno Setup launches [Run] entries using the
; ORIGINAL (non-elevated) user token even though Setup itself is elevated -
; AIORuntimeInstaller.exe's own manifest demands admin (uac_admin=True in
; the PyInstaller spec), and a plain CreateProcess from a non-elevated
; context can't silently re-elevate the way ShellExecute's UAC prompt can,
; so it failed outright with "CreateProcess failed; code 740. The
; requested operation requires elevation." Confirmed via a real install:
; the install itself succeeded, only this post-install launch step failed.
Filename: "{app}\AIORuntimeInstaller.exe"; Description: "Launch AIO Runtime Installer now"; Flags: nowait postinstall skipifsilent runascurrentuser

; Deliberately no [UninstallDelete] entries for path_backups\, profiles\,
; or the .ini/log files the app generates next to itself at runtime -
; path_backups\ in particular is this app's own safety net for undoing a
; bad PATH change, so silently deleting it on uninstall would be actively
; harmful, not just unhelpful. Uninstalling only removes what this
; installer itself put down; anything the app generated afterward is left
; for the user to keep or clean up manually.
