@echo off
cd /d "%~dp0"

:: --- 1. CREATE DESKTOP SHORTCUT (FIRST RUN ONLY) ---
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\SMART Lab DfMA Tool.lnk"
set "ICON_PATH=%~dp0lab_logo.ico"

if not exist "%SHORTCUT_PATH%" (
    echo Building quick access desktop icon...
    powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%~dp0Install_and_Run.bat'; $shortcut.WorkingDirectory = '%~dp0'; $shortcut.IconLocation = '%ICON_PATH%'; $shortcut.Save()"
)
:: ---------------------------------------------------

echo Welcome to the SMART Lab DfMA Tool!
echo Initializing the virtual environment...
python -m venv venv

echo Activating the environment...
call venv\Scripts\activate

echo Installing required packages...
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

echo Launching the DfMA Tool...
streamlit run DfMA_tool-Win_v0.1.0/Jose_Task_2.2_resumed/Start.py

pause
