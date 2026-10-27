Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef APP_VERSION
  !define APP_VERSION "1.0.0"
!endif

!include "MUI2.nsh"

Name "Google Takeout Organizer"
OutFile "..\dist\GoogleTakeoutOrganizer-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Google Takeout Organizer"
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

Section "Google Takeout Organizer" MainSection
  SectionIn RO
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File "..\dist\GoogleTakeoutOrganizer.exe"
  File "/oname=Getting Started.txt" "..\README.md"
  CreateDirectory "$SMPROGRAMS\Google Takeout Organizer"
  CreateShortcut "$SMPROGRAMS\Google Takeout Organizer\Google Takeout Organizer.lnk" "$INSTDIR\GoogleTakeoutOrganizer.exe" "$INSTDIR\GoogleTakeoutOrganizer.exe" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GoogleTakeoutOrganizer" "DisplayName" "Google Takeout Organizer"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GoogleTakeoutOrganizer" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GoogleTakeoutOrganizer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GoogleTakeoutOrganizer" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd

Section /o "Desktop shortcut" DesktopShortcut
  SetShellVarContext current
  CreateShortcut "$DESKTOP\Google Takeout Organizer.lnk" "$INSTDIR\GoogleTakeoutOrganizer.exe" "$INSTDIR\GoogleTakeoutOrganizer.exe" 0
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Google Takeout Organizer.lnk"
  Delete "$SMPROGRAMS\Google Takeout Organizer\Google Takeout Organizer.lnk"
  RMDir "$SMPROGRAMS\Google Takeout Organizer"
  Delete "$INSTDIR\GoogleTakeoutOrganizer.exe"
  Delete "$INSTDIR\Getting Started.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\GoogleTakeoutOrganizer"
SectionEnd
