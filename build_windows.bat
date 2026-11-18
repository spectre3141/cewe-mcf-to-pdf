@echo off
rem Builds dist\MCF2PDF.exe - a single stand-alone Windows program (no Python needed to run it).
rem Requirements for building only: Python 3.10+ from python.org (with tcl/tk, the default).
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

%PY% -m venv .build-venv || goto :error
call .build-venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name MCF2PDF ^
  --add-data "fonts;fonts" ^
  mcf2pdf_gui.py || goto :error

echo.
echo Done: %~dp0dist\MCF2PDF.exe
exit /b 0

:error
echo.
echo Build failed.
exit /b 1
