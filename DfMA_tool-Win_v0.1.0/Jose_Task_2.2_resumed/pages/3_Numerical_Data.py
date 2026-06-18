import streamlit as st
import pandas as pd
import os
import sys
import json
import UI_Helpers

# --- PATH HACK FOR PARENT FOLDER IMPORTS ---
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import Find_elements
import Constraints

# --- PAGE SETUP ---
st.set_page_config(page_title="Numerical Data", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] span { font-size: 30px !important; }
    </style>
    """, unsafe_allow_html=True
)

lablogo_path = os.path.join("..", "Images", "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.title("Raw Panel Data")
st.write("Extracting and analyzing spatial coordinates and dimensions from the IFC file.")

# --- CHECK THE BACKPACK ---
if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']
    
    try:
        # Load the elements
        all_elements = Find_elements.get_elements(ifcfile_path)
        vertical_studs, horizontal_tracks = Find_elements.sort_framing_by_orientation(all_elements)
        
        # Summary Metrics
        st.write(f"### Panel Composition")
        st.write(f"Total Structural Members: **{len(all_elements)}**")
        st.write(f"Vertical Studs: **{len(vertical_studs)}** | Horizontal Tracks: **{len(horizontal_tracks)}**")
        
        st.markdown("---")
        
        # 1. The Coordinate Table
        st.write("### Spatial Coordinates")
        coords = Find_elements.get_stud_coordinates(all_elements)
        st.dataframe(coords, use_container_width=True)

        st.markdown("---")

        # 2. The Hole Dimension Table
        st.write("### Extracted Hole Dimensions")
        
        # --- CLOUD SAFE MEMORY READ ---
        # Pull the allowed sizes from session memory so Pass/Fail is accurate
        config_path = st.session_state.get('config_path', None)
        allowed_holes_str_mm = "14, 34" # Default fallback in mm
        hole_size_tol_mm = 2.0
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    saved_data = json.load(f)
                    allowed_holes_str_mm = str(saved_data.get("allowed_holes_mm", "14, 34"))
                    hole_size_tol_mm = float(saved_data.get("hole_size_tol_mm", 2.0))
            except Exception:
                pass

        # Convert to meters for the engine
        try:
            allowed_sizes_list_m = [float(x.strip()) / 1000.0 for x in allowed_holes_str_mm.split(",")]
        except ValueError:
            allowed_sizes_list_m = [0.034] 
            
        hole_size_tol_m = hole_size_tol_mm / 1000.0

        # Run the engine
        hole_report = Constraints.check_hole_sizes(
            all_elements, 
            allowed_sizes_m=allowed_sizes_list_m, 
            tolerance_m=hole_size_tol_m
        )
        
        if len(hole_report["hole_details"]) > 0:
            # Convert list of dictionaries to a Pandas DataFrame
            df_holes = pd.DataFrame(hole_report["hole_details"])
            st.dataframe(df_holes, use_container_width=True)
        else:
            st.info("No standard holes detected in this panel.")
        
    except Exception as e:
        st.error(f"Something went wrong extracting the data: {e}")

else:
    st.warning("⚠️ Please upload an IFC file on the Start page first!")