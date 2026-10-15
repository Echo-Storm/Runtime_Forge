; Inno Setup script for Runtime Forge.
;
; Builds a real Windows installer around the PyInstaller onedir build in
; dist\RuntimeForge\ - a Start Menu shortcut + Program Files install
; + uninstaller, replacing "unzip the dist folder yourself." This is a
; plain on-demand desktop app (Start Menu, run occasionally) - deliberately
; no auto-start entry, no scheduled task, no tray icon/background service.
;
; Build with (after `pyinstaller RuntimeForge.spec --clean` from the
; repo root has produced dist\RuntimeForge\):
;   "C:\Users\<you>\AppData\Local\Programs\Inno Setup 7\ISCC.exe" installer\RuntimeForge.iss
; Output lands in dist_installer\RuntimeForge-Setup-0.4.2.exe (gitignored -
; this script is what's tracked, not the built installer binary).
;
; PrivilegesRequired=admin matches the app's own behavior: RuntimeForge.exe
; already carries an embedded uac_admin manifest (see RuntimeForge.spec)
; that makes Windows elevate it on every launch regardless of install
; location, so a standard Program Files install (normally read-only to
; non-elevated processes) is consistent with how the app already runs -
; it always has the access it needs to stage installers next to the exe.
; (Logs, settings, profiles and PATH backups are NOT written here - they go
; to %LOCALAPPDATA%\RuntimeForge so they survive upgrades and uninstalls.)
;
; AppId is a fresh GUID, not carried over from the old "AIO Runtime
; Installer" identity - this is a rename/rebrand, not a version bump of
; the same product, so it installs cleanly to its own new location rather
; than upgrading in place into a directory still named after the old
; branding. If you tested the old-named build, uninstall it separately
; first (Start Menu or Settings > Apps) - it won't be touched by this one.

#define AppVersion "0.4.2"

[Setup]
AppId={{7444CA67-BD70-4A65-BDD0-9F0EB7A3AB80}
AppName=Runtime Forge
AppVersion={#AppVersion}
AppPublisher=XechostormX
AppPublisherURL=https://github.com/Echo-Storm/Runtime_Forge
DefaultDirName={autopf}\Runtime Forge
DefaultGroupName=Runtime Forge
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\RuntimeForge.exe
OutputDir=..\dist_installer
OutputBaseFilename=RuntimeForge-Setup-{#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\RuntimeForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu only, deliberately no desktop icon task and no auto-start
; entry - this is a "launch it from the Start Menu every few months"
; utility, not something that should announce itself anywhere else.
Name: "{group}\Runtime Forge"; Filename: "{app}\RuntimeForge.exe"
Name: "{group}\Uninstall Runtime Forge"; Filename: "{uninstallexe}"

[Run]
; runascurrentuser: without it, Inno Setup launches [Run] entries using the
; ORIGINAL (non-elevated) user token even though Setup itself is elevated -
; RuntimeForge.exe's own manifest demands admin (uac_admin=True in the
; PyInstaller spec), and a plain CreateProcess from a non-elevated context
; can't silently re-elevate the way ShellExecute's UAC prompt can, so it
; failed outright with "CreateProcess failed; code 740. The requested
; operation requires elevation." Confirmed via a real install: the install
; itself succeeded, only this post-install launch step failed.
Filename: "{app}\RuntimeForge.exe"; Description: "Launch Runtime Forge now"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
; Installer staging is disposable (the app normally removes it itself).
Type: filesandordirs; Name: "{app}\temp_installers"

; Deliberately no [UninstallDelete] entries for path_backups\, profiles\,
; or the .ini/log files, which now live in %LOCALAPPDATA%\RuntimeForge -
; path_backups\ in particular is this app's own safety net for undoing a
; bad PATH change, so silently deleting it on uninstall would be actively
; harmful, not just unhelpful. Uninstalling only removes what this
; installer itself put down; anything the app generated afterward is left
; for the user to keep or clean up manually.
