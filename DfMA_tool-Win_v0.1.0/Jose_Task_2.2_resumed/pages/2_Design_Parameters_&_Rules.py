import streamlit as st
import os
import sys
import UI_Helpers

# --- PATH HACK FOR PARENT FOLDER IMPORTS ---
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import streamlit as st
import os
from PIL import Image
import sys

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
# 1. Get the absolute path to the 'pages' folder
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Go up TWO levels:
#    First ".." escapes the 'pages' folder.
#    Second ".." escapes 'Jose_Task_2.2_resumed' into 'DfMA_tool-Win_v0.1.0'
#    Then enter the 'Images' folder.
images_dir = os.path.join(current_dir, "..", "..", "Images")

# 3. Path hack to allow importing UI_Helpers from the parent directory
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import UI_Helpers

# --- PAGE SETUP ---
logo_path = os.path.join(images_dir, "smart_logo.jpeg")
try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = "🏗️"

# Side bar format (external to Streamlit)
st.markdown(
    """
    <style>
    /* Target the sidebar navigation menu items */
    [data-testid="stSidebarNav"] span {
        font-size: 30px !important; 
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.set_page_config(
    layout="wide",
    page_title="DfMA Display",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.set_page_config(page_title="Design Parameters", layout="wide")

# Initialize Session State
if "design_params" not in st.session_state:
    st.session_state["design_params"] = {
        "max_length": 6.00,
        "max_height": 3.00,
        "hole_tol": 0.010,
        "track_cont_tol": 0.020,
        "track_hole_tol": 0.20,
        "max_weight": 50.00,     
        "allowed_holes_mm": "14, 34", 
        "hole_size_tol_mm": 2.0,
        "max_parts": 50,
        "stud_spacing_mm": 600,
        "stud_tol_mm": 50, 
        "joist_depth_tolerance": 100,
        "part_max_length_mm": 5000,
        "part_max_height_mm": 5000,
        "part_max_depth_mm" : 500,
        "hole_border_clearance_mm": 20,
        "slanted_beam_angle" : 45,
        "total_assembly_payload_limit_kg": 100,
        "CoG_radius_tolerance_mm" : 250
    }

if "pinned_rules" not in st.session_state:
    # Default pinned rules
    st.session_state["pinned_rules"] = ["max_length", "max_height", "max_weight"]

params = st.session_state["design_params"]
pinned = st.session_state["pinned_rules"]

# Helper to manage pinning
def pin_control(rule_id):
    is_pinned = rule_id in pinned
    if st.toggle("Pin to Display", value=is_pinned, key=f"pin_{rule_id}"):
        if rule_id not in pinned:
            if len(pinned) < 14: pinned.append(rule_id)
            else: st.warning("Maximum 14 rules pinned.")
    else:
        if rule_id in pinned: pinned.remove(rule_id)

st.title("Design Constraints")
st.write("Configure physical limitations. Toggle 'Pin to Display' to bring the rule into DfMA Display.")
st.markdown("---")

tab1, tab2, tab3 = st.tabs(["Dimensional & Spatial Limits", "Tolerances & Alignment", "Assembly Capabilities"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        params["max_length"] = st.number_input("Maximum Operational Length (m)", value=params["max_length"], step=0.5)
        pin_control("max_length")
        params["max_height"] = st.number_input("Maximum Operational Height (m)", value=params["max_height"], step=0.5)
        pin_control("max_height")
    with col2:
        params["max_weight"] = st.number_input("Max Element Weight (kg)", value=params["max_weight"], step=5.0)
        pin_control("max_weight")
        params["part_max_length_mm"] = st.number_input("Max Element Lenght", value=params["part_max_length_mm"])
        pin_control("part_max_length_mm") # Fixed pin label
        params["part_max_height_mm"] = st.number_input("Max Element Height", value=params["part_max_height_mm"]) # Fixed value lookup
        pin_control("part_max_height_mm") # Fixed pin label
        params["part_max_depth_mm"] = st.number_input("Max Element Depth", value=params["part_max_depth_mm"]) # Fixed value lookup
        pin_control("part_max_depth_mm") # Fixed pin label

with tab2:
    col3, col4 = st.columns(2)
    with col3:
        params["allowed_holes_mm"] = st.text_input("Allowed Hole Sizes (mm)", value=params["allowed_holes_mm"])
        pin_control("allowed_holes_mm")
        params["hole_size_tol_mm"] = st.number_input("Hole Tolerance (mm)", value=params["hole_size_tol_mm"], step=0.5)
        pin_control("hole_size_tol_mm")
        params["hole_tol"] = st.number_input("Stud Hole Alignment Tolerance", value=params["hole_tol"], step=0.005)
        pin_control("hole_tol")
        params["track_hole_tol"] = st.number_input("Vertical Drop Hole Alignment Tolerance", value=params["track_hole_tol"], step=0.005)
        pin_control("track_hole_tol")
    with col4:
        params["track_cont_tol"] = st.number_input("Track Continuity Length (m)", value=params["track_cont_tol"], step=0.005)
        pin_control("track_cont_tol")
        params["stud_spacing_mm"] = st.text_input("Stud Spacing (mm)", value=params["stud_spacing_mm"])
        pin_control("stud_spacing_mm")
        params["stud_tol_mm"] = st.number_input("Stud Spacing Tolerance (mm)", value=params["stud_tol_mm"])
        pin_control("stud_tol_mm")
        params["hole_border_clearance_mm"] = st.number_input("hole-border clearance (mm)", value=params["hole_border_clearance_mm"])
        pin_control("hole_border_clearance_mm")


with tab3:
    col5, col6 = st.columns(2)
    with col5:
        params["slanted_beam_angle"] = st.number_input("Slanted beam angle (Roof Panels)", value=params["slanted_beam_angle"])
        pin_control("slanted_beam_angle")
        params["CoG_radius_tolerance_mm"] = st.number_input("Center of Gravity Tolerance", value = params["CoG_radius_tolerance_mm"])
        pin_control("CoG_radius_tolerance_mm")
    with col6:
        params["total_assembly_payload_limit_kg"] = st.number_input("Total Assembly Payload", value=params["total_assembly_payload_limit_kg"])
        pin_control("total_assembly_payload_limit_kg")
        params["max_parts"] = st.number_input("Total Assembly Parts", value=params["max_parts"])
        pin_control("max_parts")