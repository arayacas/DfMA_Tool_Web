"""
Description: 
    This script runs the DfMA tool through streamlit (Web Deployment Version)

------
Dependencies:
Streamlit
IfcOpenShell
stPyVista
trame
------
Author: Jose Pablo Araya Castillo
Date: May 12, 2026
"""

import streamlit as st
import os
import json
import tempfile
from PIL import Image
import UI_Helpers

# --- PAGE SETUP ---
logo_path = os.path.join("..", "Images", "smart_logo.jpeg")
try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = "🏗️"

st.set_page_config(
    layout="wide",
    page_title="DiefeMA",
    page_icon=logo_img
)

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

lablogo_path = os.path.join("..", "Images", "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

# --- DEFAULT CONSTRAINTS SETTINGS (WEB SAFE) ---
# We store the path to the constraints file in session_state so other pages can find it
if 'config_path' not in st.session_state:
    st.session_state['config_path'] = None

if st.button("Initialize / Reset Default Constraints"):
    default_config = {
        "max_length": 12.00,
        "max_height": 3.00,
        "hole_tol": 0.010,
        "track_cont_tol": 0.020,
        "track_hole_tol": 0.20,
        "max_weight": 50.00,     
        "allowed_holes": [0.014, 0.034]
    }
    try:
        # Create a unique temporary file for this user's constraints
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".json") as tmp_config:
            json.dump(default_config, tmp_config, indent=4)
            st.session_state['config_path'] = tmp_config.name
        st.success("Default constraints initialized!")
    except Exception as e:
        st.error(f"Failed to initialize/reset system constraints: {e}")

# Title
st.title("Design for Manufacturing and Robot Assembly check tool")
st.write("Upload an IFC file to check for DfMA constraints and rules")

st.write("DfMA Tool Setup")
st.markdown("### Step 1: Upload Files")

col1, col2 = st.columns(2)

# ==========================================
# 1. THE BODY (3D Geometry / IFC)
# ==========================================

with col1:
    st.markdown("#### BIM .ifc 3D Geometry")
    
    if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
        st.success(f"✅ IFC Loaded & Ready")
        
        # Button to clear just the IFC memory and delete the temp file from the server
        if st.button("Upload Different IFC"):
            try:
                os.remove(st.session_state['current_ifc_path']) 
            except Exception: pass
            del st.session_state['current_ifc_path']        
            st.rerun()                                      
    else:
        ifcfile = st.file_uploader("Drop an IFC file here", type=["ifc"]) 

        if ifcfile is not None:
            st.info("Processing Geometry...")
            
            # Creates a unique temp file just for this user
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_file:
                tmp_file.write(ifcfile.getbuffer())
                st.session_state['current_ifc_path'] = tmp_file.name
                
            st.rerun()

# ==========================================
# 2. THE BRAIN (Ontology)
# ==========================================
with col2:
    st.markdown("#### .rdf Ontology")
    if 'current_ontology_path' in st.session_state and os.path.exists(st.session_state['current_ontology_path']):
        st.success(f"✅ Ontology Loaded & Ready")
        
        if st.button("Upload Different Ontology"):
            try:
                os.remove(st.session_state['current_ontology_path'])
            except Exception: pass
            del st.session_state['current_ontology_path']
            st.rerun()
    else:
        ontology_file = st.file_uploader("Drop Ontology file here", type=['jsonld', 'ttl', 'rdf'])
        
        if ontology_file is not None:
            st.info("Processing Ontology...")
            
            # Extracts the correct extension and creates a unique temp file
            file_extension = "." + ontology_file.name.split('.')[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                tmp_file.write(ontology_file.getbuffer())
                st.session_state['current_ontology_path'] = tmp_file.name
                
            st.rerun()

# Check if both are loaded to give the green light
st.markdown("---")
if 'current_ifc_path' in st.session_state and 'current_ontology_path' in st.session_state:
    st.success("✨ All systems ready! Please move to the DfMA Display page.")
elif 'current_ifc_path' in st.session_state:
    st.warning("Geometry loaded. Waiting for Ontology file...")
else:
    st.info("Please upload your project files above to begin.")