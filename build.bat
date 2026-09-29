@echo off
setlocal
echo === NEF2JPG: Windows-EXEs bauen ===
echo.

rem In den Ordner dieser Datei wechseln. pushd klappt auch auf Netzlaufwerken.
pushd "%~dp0" || goto :nodir
echo Arbeitsordner: %CD%
echo.

rem Liegen alle Dateien nebeneinander?
for %%F in (nef2jpg.py nef2jpg_gui.py requirements.txt app.ico) do if not exist "%%F" goto :missing

rem Python finden: erst den py-Launcher, dann python auf dem PATH
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto :nopython
echo Verwende Python-Aufruf: %PY%
%PY% --version
echo.

rem Eigene Umgebung im Unterordner .venv, damit nichts am System veraendert wird
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto :fail
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r requirements.txt pyinstaller || goto :fail
echo.
echo Baue NEF2JPG.exe (Oberflaeche) ...
"%VPY%" -m PyInstaller --onefile --windowed --clean --noconfirm --name NEF2JPG --icon app.ico --add-data "app.ico;." nef2jpg_gui.py || goto :fail
echo Baue nef2jpg-cli.exe (Kommandozeile) ...
"%VPY%" -m PyInstaller --onefile --console --noconfirm --name nef2jpg-cli --icon app.ico nef2jpg.py || goto :fail
copy /Y "dist\NEF2JPG.exe" "NEF2JPG.exe" >nul || goto :fail
copy /Y "dist\nef2jpg-cli.exe" "nef2jpg-cli.exe" >nul || goto :fail
echo.
echo ===================================================
echo Fertig: %CD%\NEF2JPG.exe  und  %CD%\nef2jpg-cli.exe
echo Beide laufen auf jedem 64-Bit-Windows, auch ohne Python.
echo ===================================================
popd
pause
exit /b 0

:missing
echo Es fehlen Dateien in diesem Ordner: %CD%
echo Benoetigt werden nef2jpg.py, nef2jpg_gui.py, requirements.txt und app.ico.
echo.
echo Haeufigste Ursache: build.bat wurde direkt aus dem ZIP heraus gestartet.
echo Windows entpackt dann nur diese eine Datei in einen Temp-Ordner.
echo Abhilfe: Repo bzw. ZIP vollstaendig entpacken und build.bat von dort starten.
popd
pause
exit /b 1

:nodir
echo Der Ordner dieser Datei konnte nicht geoeffnet werden: %~dp0
pause
exit /b 1

:nopython
echo Python wurde nicht gefunden.
echo Bitte Python von https://www.python.org/downloads/windows/ installieren
echo und im Installer "Add python.exe to PATH" anhaken. Danach build.bat erneut starten.
popd
pause
exit /b 1

:fail
echo.
echo Fehler beim Bauen, siehe Meldungen oben.
popd
pause
exit /b 1
