#!/bin/bash
# Lock the terminal to the directory where this script lives
cd "$(dirname "$0")"

# --- 1. CREATE DESKTOP SHORTCUT (FIRST RUN ONLY) ---
SHORTCUT_PATH="$HOME/Desktop/SMART_Lab_DfMA_Tool.desktop"
ICON_PATH="$(pwd)/lab_logo.png"
EXEC_PATH="$(pwd)/Install_and_Run.sh"

if [ ! -f "$SHORTCUT_PATH" ]; then
    echo "Building quick access desktop icon..."
    cat <<EOF > "$SHORTCUT_PATH"
[Desktop Entry]
Version=1.0
Name=SMART Lab DfMA Tool
Comment=Launch the DfMA Tool
Exec=bash "$EXEC_PATH"
Icon=$ICON_PATH
Terminal=true
Type=Application
Categories=Science;Engineering;
EOF
    # Make the shortcut executable so Ubuntu trusts it
    chmod +x "$SHORTCUT_PATH"
fi
# ---------------------------------------------------

echo "=========================================="
echo "   Welcome to the SMART Lab DfMA Tool!"
echo "=========================================="
echo ""

echo "Initializing the virtual environment..."
# Using python3 as the standard Linux command
python3 -m venv venv

echo "Activating the environment..."
source venv/bin/activate

echo "Installing required packages..."
pip install -r requirements.txt

echo "Launching the DfMA Tool..."
streamlit run DfMA_tool-Win_v0.1.0/Jose_Task_2.2_resumed/Start.py