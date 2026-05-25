@echo off
:: ragcmdr/download_packages.bat
::
:: Run this ONCE on your build machine before compiling the installer.
:: Downloads all Python packages as .whl files into the packages\ folder.
:: The installer will use this local cache instead of the internet.
::
:: Requirements:
::   - Python 3.12 installed on your build machine
::   - Internet connection (only needed during this step)

setlocal

set "SCRIPT_DIR=%~dp0"
set "PACKAGES_DIR=%SCRIPT_DIR%packages"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"

echo ============================================================
echo  Ragcmdr — Downloading packages for offline installation
echo ============================================================
echo.
echo Target folder : %PACKAGES_DIR%
echo Requirements  : %REQUIREMENTS%
echo.

:: Create the packages folder if it does not exist
if not exist "%PACKAGES_DIR%" mkdir "%PACKAGES_DIR%"

:: Download all wheels for Windows 64-bit Python 3.12
:: --platform and --python-version ensure we get the correct binary wheels
:: even if the build machine runs a different Python version.
echo Downloading packages (this may take several minutes)...
echo.
python -m pip download ^
    --dest "%PACKAGES_DIR%" ^
    --platform win_amd64 ^
    --python-version 3.12 ^
    --only-binary=:all: ^
    --requirement "%REQUIREMENTS%"

if errorlevel 1 (
    echo.
    echo [ERROR] Some packages could not be downloaded as binary wheels.
    echo Retrying without --only-binary to allow source packages...
    echo.
    python -m pip download ^
        --dest "%PACKAGES_DIR%" ^
        --platform win_amd64 ^
        --python-version 3.12 ^
        --requirement "%REQUIREMENTS%"
)

if errorlevel 1 (
    echo.
    echo [ERROR] Download failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Download complete.
echo  Packages saved to: %PACKAGES_DIR%
echo  You can now compile install.iss with Inno Setup.
echo ============================================================
pause