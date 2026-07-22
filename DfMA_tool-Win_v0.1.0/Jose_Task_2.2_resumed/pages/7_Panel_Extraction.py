"""
Description: 
    This script runs the DfMA tool through streamlit (Web Deployment Version)
    Extracts isolated IfcElementAssembly panels from massive building files.

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
import tempfile
from PIL import Image
import UI_Helpers
import ifcopenshell
import ifcopenshell.geom
import pyvista as pv
from stpyvista import stpyvista
import numpy as np

# --- DYNAMIC PATH RESOLUTION ---
current_dir = os.path.dirname(os.path.abspath(__file__))
images_dir = os.path.join(current_dir, "..", "Images")

# --- PAGE SETUP ---
logo_path = os.path.join(images_dir, "smart_logo.jpeg")
try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = "🏗️"

st.set_page_config(
    layout="wide",
    page_title="DifeMA",
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

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass
    
# Title
st.title("Panel Extractor for full .ifc LGS panels only")
st.write("Upload a Building IFC file to isolate and extract specific panels.")

# ==========================================
# 1. THE BODY (3D Geometry / IFC)
# ==========================================

st.markdown("#### BIM .ifc Big Building")

# --- CACHE FUNCTION ---
@st.cache_resource
def load_ifc(file_path):
    return ifcopenshell.open(file_path)

# --- UPLOAD & RENDER LOGIC ---
if 'current_ifcbig_path' in st.session_state and os.path.exists(st.session_state['current_ifcbig_path']):
    st.success("Big IFC Loaded Successfully!")
    
    # Button to clear just the IFC memory and delete the temp file from the server
    if st.button("Upload Different Big IFC"):
        try:
            os.remove(st.session_state['current_ifcbig_path']) 
        except Exception: 
            pass
        del st.session_state['current_ifcbig_path']        
        st.rerun()  

    # --- 2. LOAD THE SAVED MODEL ---
    # We dynamically pass the temporary file path we saved earlier!
    try:
        ifc_model = load_ifc(st.session_state['current_ifcbig_path'])
        
        # --- 3. EXTRACT PANELS ---
        all_panels = ifc_model.by_type("IfcElementAssembly")
        panel_dict = {panel.Name: panel for panel in all_panels if panel.Name}
        
        if not panel_dict:
            st.warning("⚠️ No 'IfcElementAssembly' groupings found in this file. Please ensure the civil engineer exported the panels as Assemblies.")
        else:
            # --- 4. STREAMLIT UI ---
            st.sidebar.markdown("### Panel Selection")
            selected_panel_name = st.sidebar.selectbox(
                "Select a panel to inspect:", 
                options=list(panel_dict.keys())
            )

            active_panel = panel_dict[selected_panel_name]

            # --- 5. EXTRACTION ENGINE ---
            def get_assembly_parts(assembly):
                parts = []
                if hasattr(assembly, 'IsDecomposedBy'):
                    for relationship in assembly.IsDecomposedBy:
                        parts.extend(relationship.RelatedObjects)
                return parts

            panel_members = get_assembly_parts(active_panel)
            
            # --- NEW: ISOLATED IFC GENERATOR ---
            def extract_panel_to_ifc_string(original_model, panel):
                new_ifc = ifcopenshell.file(schema=original_model.schema)
                
                # 1. 🛠️ THE FIX: Bring over the Spatial Anchors (extremely lightweight)
                # This gives the panel's relative coordinates a real-world origin to attach to.
                for context_class in ["IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey"]:
                    for entity in original_model.by_type(context_class):
                        new_ifc.add(entity)
                        
                # 2. Maintain the relationship connecting the panel to the building layout
                for rel in original_model.by_type("IfcRelContainedInSpatialStructure"):
                    if panel in rel.RelatedElements:
                        new_ifc.add(rel)
                
                # 3. Add the panel itself
                new_ifc.add(panel)
                
                # 4. Add the decomposition relationships (this automatically brings all the steel parts!)
                if hasattr(panel, 'IsDecomposedBy'):
                    for rel in panel.IsDecomposedBy:
                        new_ifc.add(rel) 
                        
                # 5. Output as a raw string of text
                return new_ifc.to_string()

            # Generate the raw data for the download button
            isolated_ifc_data = extract_panel_to_ifc_string(ifc_model, active_panel)

            st.markdown("---")
            
            # --- CREATE THE DASHBOARD LAYOUT ---
            left_col, right_col = st.columns([1, 3])
            
            # ==========================================
            # LEFT COLUMN: PANEL STATS & DOWNLOAD
            # ==========================================
            with left_col:
                st.markdown(f"### Panel: {selected_panel_name}")
                st.write(f"**Total Sub-components:** {len(panel_members)}")
                
                st.success("Panel successfully isolated in memory!")
                
                # Streamlit Download Button
                st.download_button(
                    label=f"Download {selected_panel_name}.ifc",
                    data=isolated_ifc_data,
                    file_name=f"{selected_panel_name}.ifc",
                    mime="application/octet-stream"
                )
            # ==========================================
            # RIGHT COLUMN: 3D VIEWER
            # ==========================================
            with right_col:
                header_col1, header_col2 = st.columns([3, 1])
                with header_col1:
                    st.markdown("### 3D Isolated Panel Viewer")
                with header_col2:
                    show_alignment = st.toggle("Show Alignment Lines", value=False)
                
                # --- 6. RENDER TO PYVISTA ---
                plotter = pv.Plotter(window_size=[600, 800])
                settings = ifcopenshell.geom.settings()
                
                # THE FIX: Force the engine to calculate absolute world coordinates
                settings.set(settings.USE_WORLD_COORDS, True)
                
                # Loop ONLY through the parts of the selected panel
                for part in panel_members:
                    try:
                        shape = ifcopenshell.geom.create_shape(settings, part)
                        
                        # Convert IfcOpenShell geometry to PyVista mesh
                        faces = shape.geometry.faces
                        verts = shape.geometry.verts

                        # Enforce data types to help PyVista read it correctly
                        vertices = np.array(verts, dtype=np.float32).reshape((-1, 3))
                        faces_raw = np.array(faces, dtype=np.int32).reshape((-1, 3))
                        
                        padding = np.full((faces_raw.shape[0], 1), 3, dtype=np.int32) 
                        faces_pv = np.hstack((padding, faces_raw)).flatten()
                        
                        mesh = pv.PolyData(vertices, faces_pv)
                        plotter.add_mesh(mesh, color="lightblue", show_edges=True)
                    
                    except Exception as e:
                        # Silently pass parts that lack 3D geometry
                        pass

                # 🛠️ FIXED: These must be indented INSIDE the `with right_col:` block!
                plotter.view_isometric() 
                stpyvista(plotter)

    except Exception as e:
        st.error(f"Error loading IFC file: {e}")

# 🛠️ FIXED: Restored the missing 'else' block so the file uploader actually appears!
else:
    # --- IF NO FILE IS UPLOADED YET ---
    ifcbigfile = st.file_uploader("Drop a Big IFC file here", type=["ifc"]) 

    if ifcbigfile is not None:
        st.info("Saving and processing Geometry... Please wait.")
        
        # Creates a unique temp file just for this user
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_file:
            tmp_file.write(ifcbigfile.getbuffer())
            st.session_state['current_ifcbig_path'] = tmp_file.name
            
        st.rerun()
