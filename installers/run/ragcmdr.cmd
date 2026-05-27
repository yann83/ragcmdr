@echo off
:: ragcmdr.bat — Ragcmdr launcher
:: Activates the virtual environment created by post_install.bat
:: and forwards all arguments to ragcmdr.py.
::
:: Usage from any terminal (once {app} is in PATH):
::   ragcmdr create collection my-docs
::   ragcmdr open collection my-docs
::   ragcmdr add "D:\my docs\"
::   ragcmdr chat

:: %~dp0 = absolute path to the folder containing this .bat (always ends with \)
set "APP_DIR=%~dp0"
set "VENV=%APP_DIR%.venv"

:: Sanity check: make sure the venv was created by the installer
if not exist "%VENV%\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at %VENV%
    echo Please run the Ragcmdr installer again.
    pause
    exit /b 1
)

:: Activate the virtual environment
call "%VENV%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

:: Forward all arguments the user typed after "ragcmdr" to ragcmdr.py
:: %* passes every argument as-is (quoted paths included)
python "%APP_DIR%ragcmdr.py" %*

:: Deactivate cleanly after the command returns
call deactivate
