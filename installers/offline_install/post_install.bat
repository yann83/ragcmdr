:: @echo off
:: post_install.bat — Post-installation script for Ragcmdr (offline installer)
:: Called silently by Inno Setup after extracting all files.
:: Creates the virtual environment and installs all Python dependencies
:: from the pre-downloaded packages\ folder bundled in the installer.
::
:: Prerequisites handled at build time:
::   - python312._pth already contains "Lib" and "import site"
::   - python\Lib\ensurepip\ copied from standard Python 3.12 install
::   - python\Lib\venv\     copied from standard Python 3.12 install
::   - packages\            pre-downloaded wheels (pip download -r requirements.txt -d packages)
::
:: Arguments passed by Inno Setup:
::   %1 = full path to the installation directory (e.g. C:\Users\...\Ragcmdr)

setlocal enabledelayedexpansion

set "INSTALL_DIR=%~1"
set "PYTHON=%INSTALL_DIR%\python\python.exe"
set "VENV=%INSTALL_DIR%\.venv"
set "VENV_PY=%INSTALL_DIR%\.venv\Scripts\python.exe"
set "VENV_PIP=%INSTALL_DIR%\.venv\Scripts\pip.exe"
set "REQUIREMENTS=%INSTALL_DIR%\requirements.txt"
set "PACKAGES_DIR=%INSTALL_DIR%\packages"
set "LOG=%INSTALL_DIR%\install.log"

echo Ragcmdr post-installation > "%LOG%"
echo Install dir: %INSTALL_DIR% >> "%LOG%"
echo. >> "%LOG%"

:: ---- Step 1: Verify embedded Python and venv module ----
echo [1/4] Checking embedded Python... >> "%LOG%"
if not exist "%PYTHON%" (
    echo [ERROR] Python not found at %PYTHON% >> "%LOG%"
    exit /b 1
)
"%PYTHON%" --version >> "%LOG%" 2>&1
"%PYTHON%" -c "import venv" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] venv module not found. >> "%LOG%"
    echo         Make sure python\Lib\venv\ exists in the installer sources. >> "%LOG%"
    exit /b 1
)
echo OK >> "%LOG%"

:: ---- Step 2: Bootstrap pip into the embedded Python ----
:: get-pip.py is extracted by the installer alongside the sources.
echo [2/4] Installing pip into embedded Python... >> "%LOG%"
if not exist "%INSTALL_DIR%\python\Lib\site-packages\pip" (
    "%PYTHON%" "%INSTALL_DIR%\get-pip.py" --no-warn-script-location >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] pip bootstrap failed. >> "%LOG%"
        exit /b 1
    )
)
echo OK >> "%LOG%"

:: ---- Step 3: Create the virtual environment ----
echo [3/4] Creating virtual environment... >> "%LOG%"
if exist "%VENV%" (
    echo Virtual environment already exists, skipping creation. >> "%LOG%"
) else (
    "%PYTHON%" -m venv "%VENV%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. >> "%LOG%"
        exit /b 1
    )
)
echo OK >> "%LOG%"

:: ---- Step 4: Install dependencies from packages\ folder (offline) ----
:: setuptools and wheel are installed first — required as build backend
:: for any package that does not ship a pre-built wheel.
:: --no-index   : never reach the internet
:: --find-links : use only the local packages\ folder
echo [4/4] Installing dependencies (offline)... >> "%LOG%"

if not exist "%PACKAGES_DIR%" (
    echo [ERROR] packages\ folder not found at %PACKAGES_DIR% >> "%LOG%"
    echo         This installer requires the packages\ folder to be present. >> "%LOG%"
    exit /b 1
)

:: Upgrade pip from local packages (no internet)
"%VENV_PY%" -m pip install --upgrade pip --quiet --no-index --find-links="%PACKAGES_DIR%" --no-warn-script-location >> "%LOG%" 2>&1

:: Install setuptools and wheel first so build backends are available
"%VENV_PIP%" install setuptools wheel --quiet --no-index --find-links="%PACKAGES_DIR%" --no-warn-script-location >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to install setuptools/wheel from packages\. >> "%LOG%"
    echo         Make sure setuptools and wheel wheels are present in packages\. >> "%LOG%"
    exit /b 1
)

:: Install all application dependencies
"%VENV_PIP%" install -r "%REQUIREMENTS%" --quiet --no-index --find-links="%PACKAGES_DIR%" --no-warn-script-location >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. See install.log for details. >> "%LOG%"
    exit /b 1
)
echo OK >> "%LOG%"

:: ---- Step 5: Remove packages\ folder (no longer needed after install) ----
echo [5/5] Cleaning up packages folder... >> "%LOG%"
if exist "%PACKAGES_DIR%" (
    rmdir /s /q "%PACKAGES_DIR%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [WARNING] Could not remove packages\ folder. You can delete it manually. >> "%LOG%"
    ) else (
        echo Packages folder removed. >> "%LOG%"
    )
)
echo OK >> "%LOG%"

echo. >> "%LOG%"
echo Installation completed successfully. >> "%LOG%"
exit /b 0