@echo off
cd /d "%~dp0"

echo Welcome to the SMART Lab DfMA Tool!
echo Initializing the virtual environment...
python -m venv venv

echo Activating the environment...
call venv\Scripts\activate

echo Installing required packages...
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

echo Launching the DfMA Tool...
streamlit run Start.py

pause