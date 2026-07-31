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
    
# Tracking state for Ghost Building Progress
if 'extracted_panels' not in st.session_state:
    st.session_state['extracted_panels'] = []

# Title
st.title("Panel Extractor for full .ifc LGS panels only")
st.write("Upload a Building IFC file to isolate and extract specific panels.")

# ==========================================
# 1. THE BODY (3D Geometry / IFC)
# ==========================================

st.markdown("#### BIM .ifc Big Building")

# --- CACHE FUNCTIONS ---
@st.cache_resource
def load_ifc(file_path):
    return ifcopenshell.open(file_path)

@st.cache_data(show_spinner="Calculating Ghost Building Layout. This takes about 60 seconds...")
def get_all_panel_bounds(_model, _panel_names_dict): # 🛠️ Includes the underscore fix!
    """Calculates the global bounding box for every panel to create the Ghost Building."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    bounds_dict = {}
    for name, panel in _panel_names_dict.items():
        parts = []
        if hasattr(panel, 'IsDecomposedBy'):
            for rel in panel.IsDecomposedBy:
                parts.extend(rel.RelatedObjects)
                
        min_pt = [float('inf'), float('inf'), float('inf')]
        max_pt = [float('-inf'), float('-inf'), float('-inf')]
        
        valid_geometry = False
        for part in parts:
            try:
                shape = ifcopenshell.geom.create_shape(settings, part)
                verts = np.array(shape.geometry.verts).reshape((-1, 3))
                min_pt = np.minimum(min_pt, verts.min(axis=0))
                max_pt = np.maximum(max_pt, verts.max(axis=0))
                valid_geometry = True
            except Exception:
                pass
                
        if valid_geometry:
            bounds_dict[name] = (min_pt[0], max_pt[0], min_pt[1], max_pt[1], min_pt[2], max_pt[2])
            
    return bounds_dict

# --- UPLOAD & RENDER LOGIC ---
if 'current_ifcbig_path' in st.session_state and os.path.exists(st.session_state['current_ifcbig_path']):
    st.success("Big IFC Loaded Successfully!")
    
    if st.button("Upload Different Big IFC"):
        try:
            os.remove(st.session_state['current_ifcbig_path']) 
        except Exception: 
            pass
        del st.session_state['current_ifcbig_path']        
        st.rerun()  

    try:
        ifc_model = load_ifc(st.session_state['current_ifcbig_path'])
        
        # --- 3. EXTRACT PANELS ---
        all_panels = ifc_model.by_type("IfcElementAssembly")
        panel_dict = {panel.Name: panel for panel in all_panels if panel.Name}
        
        if not panel_dict:
            st.warning("⚠️ No 'IfcElementAssembly' groupings found in this file.")
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
            
            def extract_panel_to_ifc_string(original_model, panel):
                new_ifc = ifcopenshell.file(schema=original_model.schema)
                for context_class in ["IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey"]:
                    for entity in original_model.by_type(context_class):
                        new_ifc.add(entity)
                for rel in original_model.by_type("IfcRelContainedInSpatialStructure"):
                    if panel in rel.RelatedElements:
                        new_ifc.add(rel)
                new_ifc.add(panel)
                if hasattr(panel, 'IsDecomposedBy'):
                    for rel in panel.IsDecomposedBy:
                        new_ifc.add(rel) 
                return new_ifc.to_string()

            # Pre-calculate data for UX
            isolated_ifc_data = extract_panel_to_ifc_string(ifc_model, active_panel)
            panel_bounds = get_all_panel_bounds(ifc_model, panel_dict)

            st.markdown("---")
            
            # ==========================================
            # TOP ROW: STATS & ISOLATED VIEWER
            # ==========================================
            left_col, right_col = st.columns([1, 2]) # Tweaked ratio slightly to fit 3D better
            
            with left_col:
                st.markdown(f"###Panel: {selected_panel_name}")
                st.write(f"**Total Sub-components:** {len(panel_members)}")
                
                # Show completion progress
                progress = len(st.session_state['extracted_panels'])
                total = len(panel_dict)
                st.progress(progress / total, text=f"Extraction Progress: {progress}/{total} Panels")
                
                def mark_extracted(panel_id):
                    if panel_id not in st.session_state['extracted_panels']:
                        st.session_state['extracted_panels'].append(panel_id)

                st.download_button(
                    label=f"Download {selected_panel_name}.ifc",
                    data=isolated_ifc_data,
                    file_name=f"{selected_panel_name}.ifc",
                    mime="application/octet-stream",
                    on_click=mark_extracted,
                    args=(selected_panel_name,) 
                )

            with right_col:
                st.markdown("### Isolated Panel View")
                # PLOTTER 1: The Isolated Panel
                plotter_iso = pv.Plotter(window_size=[800, 800])
                settings = ifcopenshell.geom.settings()
                settings.set(settings.USE_WORLD_COORDS, True)
                
                for part in panel_members:
                    try:
                        shape = ifcopenshell.geom.create_shape(settings, part)
                        verts = shape.geometry.verts
                        faces = shape.geometry.faces
                        vertices = np.array(verts, dtype=np.float32).reshape((-1, 3))
                        faces_raw = np.array(faces, dtype=np.int32).reshape((-1, 3))
                        padding = np.full((faces_raw.shape[0], 1), 3, dtype=np.int32) 
                        faces_pv = np.hstack((padding, faces_raw)).flatten()
                        
                        mesh = pv.PolyData(vertices, faces_pv)
                        plotter_iso.add_mesh(mesh, color="lightblue", show_edges=True)
                    except Exception: pass

                plotter_iso.view_isometric() 
                # UNIQUE KEY added to prevent component collision
                stpyvista(plotter_iso, key="isolated_viewer")


            st.markdown("---")
            
            # ==========================================
            # BOTTOM ROW: MACRO GHOST BUILDING
            # ==========================================
            st.markdown("###Whole Building Context")
            st.info("Macro View: Rotate the building below to see where your active panel (blue) fits into the overall structure. Extracted panels are marked in green.")
            
            # PLOTTER 2: The Ghost Building Context
            plotter_macro = pv.Plotter(window_size=[1200, 1200])
            
            # 🛠️ NEW: Lists to hold the coordinates and text for our labels
            label_coords = []
            label_texts = []

            # Draw the Ghost Boxes
            for p_name, bounds in panel_bounds.items():
                ghost_box = pv.Box(bounds=bounds)
                if p_name == selected_panel_name:
                    plotter_macro.add_mesh(ghost_box, style="wireframe", color="blue", line_width=3)
                elif p_name in st.session_state['extracted_panels']:
                    plotter_macro.add_mesh(ghost_box, color="green", opacity=0.2, show_edges=True)
                else:
                    plotter_macro.add_mesh(ghost_box, color="lightgrey", opacity=0.05, show_edges=True)

                # Calculate the exact 3D center of the bounding box
                center_x = (bounds[0] + bounds[1]) / 2.0
                center_y = (bounds[2] + bounds[3]) / 2.0
                center_z = (bounds[4] + bounds[5]) / 2.0
                
                # WEB FIX: Forge the text out of physical 3D geometry!
                try:
                    # Create physical 3D letters (PolyData)
                    text_mesh = pv.Text3D(str(p_name), depth=0.05)
                    
                    # SCALE FACTOR: IFC building units are usually either strictly meters or mm. 
                    # Tweak this number! If the text is massive, change to 0.1. If you can't see it, change to 50.0.
                    scale_factor = 0.1 
                    text_mesh.points *= scale_factor 
                    
                    # Move the physical text exactly to the center of the ghost box
                    text_mesh.translate([
                        center_x - text_mesh.center[0], 
                        center_y - text_mesh.center[1], 
                        center_z - text_mesh.center[2]
                    ], inplace=True)
                    
                    # Add the physical text and a red anchor dot
                    plotter_macro.add_mesh(text_mesh, color="black")
                    plotter_macro.add_mesh(pv.Sphere(radius=scale_factor*0.1, center=[center_x, center_y, center_z]), color="red")
                    
                except Exception:
                    pass

            plotter_macro.view_isometric() 
            stpyvista(plotter_macro, key="macro_viewer")

    except Exception as e:
        st.error(f"Error loading IFC file: {e}")

else:
    # --- IF NO FILE IS UPLOADED YET ---
    ifcbigfile = st.file_uploader("Drop a Big IFC file here", type=["ifc"]) 

    if ifcbigfile is not None:
        st.info("Saving and processing Geometry... Please wait.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_file:
            tmp_file.write(ifcbigfile.getbuffer())
            st.session_state['current_ifcbig_path'] = tmp_file.name
            
        st.rerun()

import ifcopenshell
import ifcopenshell.guid

# 1. Load the panel with missing materials
ifc_file = ifcopenshell.open("extracted_panel.ifc")

# 2. Create the Material entity safely
steel_material = ifc_file.createIfcMaterial("Steel")

# 3. Find all the physical parts (Adjust "IfcBeam" to "IfcBuildingElementPart" or "IfcMember" if needed)
members = ifc_file.by_type("IfcElement") 

# 4. Link the material to every member
for member in members:
    ifc_file.createIfcRelAssociatesMaterial(
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=None,
        Name="MaterialLink",
        Description=None,
        RelatedObjects=[member],
        RelatingMaterial=steel_material
    )

# 5. Save the fixed file!
ifc_file.write("extracted_panel_with_materials.ifc")
print("✅ Materials successfully injected!")
