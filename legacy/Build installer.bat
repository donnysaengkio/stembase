@echo off
rem Rebuilds the standalone app and its installer. Needs: Python with requirements.txt + pyinstaller, and Inno Setup 6.
cd /d "%~dp0"
echo [1/2] Building the app folder with PyInstaller (several minutes)...
python -m PyInstaller stem_studio.spec --noconfirm || goto :fail
echo [2/2] Packing the installer with Inno Setup (several minutes)...
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" installer.iss || goto :fail
echo.
echo Done: the installer is in the "installer" folder.
pause
exit /b 0
:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
