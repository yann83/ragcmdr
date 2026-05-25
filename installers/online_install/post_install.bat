:: @echo off
:: post_install.bat — Post-installation script for Ragcmdr
:: Called by Inno Setup after extracting all files.
::
:: Prerequisites handled at build time (no runtime patching needed):
::   - python312._pth already contains "Lib" and "import site"
::   - python\Lib\ensurepip\ copied from standard Python 3.12 install
::   - python\Lib\venv\     copied from standard Python 3.12 install
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
set "LOG=%INSTALL_DIR%\install.log"

echo Ragcmdr post-installation > "%LOG%"
echo Install dir: %INSTALL_DIR% >> "%LOG%"
echo. >> "%LOG%"

:: ---- Step 1: Verify embedded Python and venv module ----
echo [1/3] Checking embedded Python... >> "%LOG%"
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
echo [2/3] Installing pip into embedded Python... >> "%LOG%"
if not exist "%INSTALL_DIR%\python\Lib\site-packages\pip" (
    "%PYTHON%" "%INSTALL_DIR%\get-pip.py" --no-warn-script-location >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] pip bootstrap failed. >> "%LOG%"
        exit /b 1
    )
)
echo OK >> "%LOG%"

:: ---- Step 3: Create venv and install dependencies ----
echo [3/3] Creating venv and installing dependencies... >> "%LOG%"

:: Create the virtual environment
if exist "%VENV%" (
    echo Virtual environment already exists, skipping creation. >> "%LOG%"
) else (
    "%PYTHON%" -m venv "%VENV%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. >> "%LOG%"
        exit /b 1
    )
)

:: Upgrade pip inside the venv
"%VENV_PY%" -m pip install --upgrade pip --quiet --no-warn-script-location >> "%LOG%" 2>&1

:: Install setuptools and wheel first — required to build any sdist package.
:: Without this, pip fails with "Cannot import setuptools.build_meta".
"%VENV_PIP%" install setuptools wheel --quiet --no-warn-script-location >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to install setuptools/wheel. >> "%LOG%"
    exit /b 1
)

:: Install all application dependencies
"%VENV_PIP%" install -r "%REQUIREMENTS%" --quiet --no-warn-script-location >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. See install.log for details. >> "%LOG%"
    exit /b 1
)
echo OK >> "%LOG%"

echo. >> "%LOG%"
echo Installation completed successfully. >> "%LOG%"
exit /b 0