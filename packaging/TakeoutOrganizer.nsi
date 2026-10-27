Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef APP_VERSION
  !define APP_VERSION "1.0.0"
!endif

!include "MUI2.nsh"

Name "Takeout Organizer"
OutFile "dist\TakeoutOrganizer-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Takeout Organizer"
ShowInstDetails show
ShowUnInstDetails show

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Takeout Organizer" MainSection
  SectionIn RO
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File "dist\TakeoutOrganizer.exe"
  File /oname="Getting Started.txt" "README.md"
  CreateDirectory "$SMPROGRAMS\Takeout Organizer"
  CreateShortcut "$SMPROGRAMS\Takeout Organizer\Takeout Organizer.lnk" "$INSTDIR\TakeoutOrganizer.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TakeoutOrganizer" "DisplayName" "Takeout Organizer"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TakeoutOrganizer" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TakeoutOrganizer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TakeoutOrganizer" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd

Section /o "Desktop shortcut" DesktopShortcut
  SetShellVarContext current
  CreateShortcut "$DESKTOP\Takeout Organizer.lnk" "$INSTDIR\TakeoutOrganizer.exe"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Takeout Organizer.lnk"
  Delete "$SMPROGRAMS\Takeout Organizer\Takeout Organizer.lnk"
  RMDir "$SMPROGRAMS\Takeout Organizer"
  Delete "$INSTDIR\TakeoutOrganizer.exe"
  Delete "$INSTDIR\Getting Started.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TakeoutOrganizer"
SectionEnd
