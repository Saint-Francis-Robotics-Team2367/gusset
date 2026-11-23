@echo off
setlocal EnableExtensions
rem ==========================================================================
rem  Install Gusset (Windows) - double-click this file.
rem  Copies Gusset into Fusion's own add-ins folder, so it starts by itself with
rem  Fusion. Safe to run again: your settings, remembered choices and logs stay.
rem  If Windows says "Windows protected your PC": More info > Run anyway.
rem ==========================================================================
set "SRC=%~dp0Gusset"
set "DEST=%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\Gusset"
echo.
echo   Installing Gusset...
echo.
if not exist "%SRC%\Gusset.py" (
  echo   Problem: can't find the Gusset folder next to this installer. Unzip the whole download first.
  goto :fail
)

:checkfusion
tasklist /FI "IMAGENAME eq Fusion360.exe" 2>nul | find /I "Fusion360.exe" >nul
if not errorlevel 1 (
  echo   Fusion is open. Save your work and QUIT Fusion, then press any key.
  pause >nul
  goto :checkfusion
)

if not exist "%DEST%" mkdir "%DEST%"

rem Move this computer's files over from an older "FRC Plugins" copy.
for %%O in ("%USERPROFILE%\FRC Plugins\Gusset" "%USERPROFILE%\Documents\FRC Plugins\Gusset") do (
  if exist "%%~O\Gusset.py" (
    echo   Found an older copy in: %%~O
    for %%F in (gusset_config.json gusset_state.json team_settings_draft.json) do (
      if exist "%%~O\%%F" if not exist "%DEST%\%%F" copy /Y "%%~O\%%F" "%DEST%\%%F" >nul && echo     kept %%F
    )
    if exist "%%~O\cache" if not exist "%DEST%\cache" robocopy "%%~O\cache" "%DEST%\cache" /E /NFL /NDL /NJH /NJS /NP >nul
    ren "%%~O" "Gusset (old copy - safe to delete)" && echo     renamed the old copy so Fusion stops loading it
  )
)

rem Copy the new code, never touching this computer's own files.
robocopy "%SRC%" "%DEST%" /E /XF gusset_config.json gusset_state.json team_settings_draft.json /XD logs cache __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo   Problem: couldn't copy the files into %DEST%
  goto :fail
)
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%DEST%' -Recurse | Unblock-File" >nul 2>&1

echo.
echo   Done! Gusset is installed in:
echo     %DEST%
echo.
echo   Open Fusion - the GUSSET tab appears by itself.
echo   (If it doesn't: UTILITIES ^> ADD-INS ^> Scripts and Add-Ins ^> Add-Ins ^> Gusset ^> Run, and turn on Run on Startup.)
echo.
pause
exit /b 0

:fail
echo   Nothing else was changed.
pause
exit /b 1
