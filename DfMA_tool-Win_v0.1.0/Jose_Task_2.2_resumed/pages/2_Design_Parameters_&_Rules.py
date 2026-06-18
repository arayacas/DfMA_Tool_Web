import streamlit as st
import os
import json
import UI_Helpers

# --- PAGE SETUP ---
st.set_page_config(page_title="Constraints & Rules", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] span { font-size: 30px !important; }
    </style>
    """, unsafe_allow_html=True)

lablogo_path = os.path.join("..", "Images", "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.title("DfMA Design Parameters & Constraints")
st.write("Configure the manufacturing rules for the wall panels here.")
st.markdown("---")

st.subheader("Maximum Panel Dimensions")

# --- CLOUD-SAFE JSON CONFIGURATION SETUP ---
import tempfile # Ensure this is imported at the top of your script!

# Grab the unique temp file path generated on the Start page
config_path = st.session_state.get('config_path', None)

# NEW LOGIC: If the file doesn't exist yet, build it right now so the user isn't blocked!
if not config_path or not os.path.exists(config_path):
    default_config = {
        "max_length": 6.00,
        "max_height": 3.00,
        "hole_tol": 0.010,
        "track_cont_tol": 0.020,
        "track_hole_tol": 0.20,
        "max_weight": 50.00,     
        "allowed_holes_mm": "14, 34",
        "hole_size_tol_mm": 2.0
    }
    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".json") as tmp_config:
        json.dump(default_config, tmp_config, indent=4)
        st.session_state['config_path'] = tmp_config.name
        config_path = tmp_config.name # Update local variable so the rest of the page works

# 1. READ: Load existing data so sliders remember their positions
saved_data = {} 
default_length = 6.00
default_height = 3.00

try:
    with open(config_path, "r") as f:
        saved_data = json.load(f)
        default_length = float(saved_data.get("max_length", 6.00))
        default_height = float(saved_data.get("max_height", 3.00))
except Exception:
    pass 

# 2. UI: Draw the sliders using the loaded default values
selected_length = st.slider("Max Allowed Length (m)", min_value=0.5, max_value=12.00, value=default_length, step=0.01)
selected_height = st.slider("Max Allowed Height (m)", min_value=0.5, max_value=12.00, value=default_height, step=0.01)

# 3. WRITE: Update the specific keys WITHOUT deleting the rest of the file
saved_data["max_length"] = selected_length
saved_data["max_height"] = selected_height

try:
    with open(config_path, "w") as f:
        json.dump(saved_data, f, indent=4)
    st.success("💾 Constraints actively saved to cloud session!")
except Exception as e:
    st.error(f"Failed to save constraints: {e}")
else:
    st.warning("⚠️ Session memory not initialized. Please visit the Start page first.")