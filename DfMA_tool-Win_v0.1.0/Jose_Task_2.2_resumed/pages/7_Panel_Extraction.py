"""
Description: 
    This script runs the DfMA tool through streamlit (Web Deployment Version)
    Extracts isolated IfcElementAssembly panels from massive building files.
    *UPDATED: Now utilizes IfcPatch to natively convert all files to Metric upon upload.*

------
Dependencies:
Streamlit
IfcOpenShell
stPyVista
trame
ifcpatch
------
Author: Jose Pablo Araya Castillo
Date: May 12, 2026
"""

import streamlit as st
import os
import tempfile
from PIL import Image
import ifcopenshell 
import ifcpatch 
import ifcopenshell.geom
import pyvista as pv
from stpyvista import stpyvista
import numpy as np
import sys
import platform

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
# 1. Get the absolute path to the 'pages' folder
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Go up TWO levels:
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

st.set_page_config(
    layout="wide",
    page_title="Objective Functions",
    page_icon=logo_img
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
    model = ifcopenshell.open(file_path)
    
    # 🛠️ IfcPatch Execution: Force the entire model to Metric upstream
    patched_model = ifcpatch.execute({
        "file": model,
        "recipe": "ConvertLengthUnit",
        "arguments": ["METER"] 
    })
    
    return patched_model if patched_model else model

@st.cache_data(show_spinner="Calculating Ghost Building Layout. This may take about 5 minutes...")
def get_all_panel_bounds(_model, _panel_names_dict): 
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
    st.success("Big IFC Loaded Successfully and Patching to Metric!")
    
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
            st.warning(" No 'IfcElementAssembly' groupings found in this file.")
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

            # ==========================================
            # 🛠️ 5.5 GENERATE COMBINED MESH FOR VIEWER & STL
            # ==========================================
            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)
            
            combined_mesh = pv.PolyData()
            
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
                    # Merge all sub-components into one big PyVista object
                    combined_mesh = combined_mesh.merge(mesh) if combined_mesh.n_points > 0 else mesh
                except Exception: 
                    pass

            # PROCESS FOR PHYSICS SIMULATION (Center only)
            stl_data = None
            if combined_mesh.n_points > 0:
                sim_mesh = combined_mesh.copy()
                
                # 1. Solve Global Origin Problem: Center mesh at (0, 0, 0)
                center_pt = sim_mesh.center
                sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)
                
                # NOTE: The mesh.scale() step was removed here because IfcPatch 
                # already guaranteed the raw extracted geometry is in Metric Meters!

                # 3. Save as binary STL to temporary file
                with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp_stl:
                    sim_mesh.save(tmp_stl.name)
                    with open(tmp_stl.name, "rb") as f:
                        stl_data = f.read()
                os.remove(tmp_stl.name)


            st.markdown("---")
            
            # ==========================================
            # TOP ROW: STATS & ISOLATED VIEWER
            # ==========================================
            left_col, right_col = st.columns([1, 2]) 
            
            with left_col:
                st.markdown(f"### Panel: {selected_panel_name}")
                st.write(f"**Total Sub-components:** {len(panel_members)}")
                
                # Show completion progress
                progress = len(st.session_state['extracted_panels'])
                total = len(panel_dict)
                st.progress(progress / total, text=f"Extraction Progress: {progress}/{total} Panels")
                
                def mark_extracted(panel_id):
                    if panel_id not in st.session_state['extracted_panels']:
                        st.session_state['extracted_panels'].append(panel_id)

                st.markdown("#### Exports")
                
                # Original IFC Download (Now inherently Metric!)
                st.download_button(
                    label=f"📦 Download {selected_panel_name}.ifc (Metric)",
                    data=isolated_ifc_data,
                    file_name=f"{selected_panel_name}.ifc",
                    mime="application/octet-stream",
                    on_click=mark_extracted,
                    args=(selected_panel_name,) 
                )

                # NEW: Simulation STL Download (appears below the IFC button)
                if stl_data:
                    st.download_button(
                        label=f"🤖 Download STL for Simulation (Centered)",
                        data=stl_data,
                        file_name=f"{selected_panel_name}_Sim.stl",
                        mime="application/octet-stream",
                        help="Exports a centered, metric (meters) STL perfect for Gazebo, MuJoCo, or Isaac Sim."
                    )

            with right_col:
                st.markdown("### Isolated Panel View")
                # PLOTTER 1: The Isolated Panel
                plotter_iso = pv.Plotter(window_size=[800, 800])
                
                # We plot the ORIGINAL un-scaled/un-centered combined_mesh here 
                # so it remains visually consistent with the Ghost Building!
                if combined_mesh.n_points > 0:
                    plotter_iso.add_mesh(combined_mesh, color="lightblue", show_edges=True)

                plotter_iso.view_isometric()
                backend_engine = "panel" if platform.system() == "Windows" else "trame"
                stpyvista(plotter_iso, key="isolated_viewer", backend=backend_engine)

            st.markdown("---")
            
            # ==========================================
            # BOTTOM ROW: MACRO GHOST BUILDING
            # ==========================================
            st.markdown("### Whole Building Context")
            st.info("Macro View: Rotate the building below to see where your active panel (blue) fits into the overall structure. Extracted panels are marked in green.")
            
            # PLOTTER 2: The Ghost Building Context
            plotter_macro = pv.Plotter(window_size=[1200, 1200])
            
            for p_name, bounds in panel_bounds.items():
                ghost_box = pv.Box(bounds=bounds)
                if p_name == selected_panel_name:
                    plotter_macro.add_mesh(ghost_box, style="wireframe", color="blue", line_width=3)
                elif p_name in st.session_state['extracted_panels']:
                    plotter_macro.add_mesh(ghost_box, color="green", opacity=0.2, show_edges=True)
                else:
                    plotter_macro.add_mesh(ghost_box, color="lightgrey", opacity=0.05, show_edges=True)

                center_x = (bounds[0] + bounds[1]) / 2.0
                center_y = (bounds[2] + bounds[3]) / 2.0
                center_z = (bounds[4] + bounds[5]) / 2.0
                
                try:
                    text_mesh = pv.Text3D(str(p_name), depth=0.05)
                    scale_factor = 0.1 
                    text_mesh.points *= scale_factor 
                    
                    text_mesh.translate([
                        center_x - text_mesh.center[0], 
                        center_y - text_mesh.center[1], 
                        center_z - text_mesh.center[2]
                    ], inplace=True)
                    
                    plotter_macro.add_mesh(text_mesh, color="black")
                    plotter_macro.add_mesh(pv.Sphere(radius=scale_factor*0.1, center=[center_x, center_y, center_z]), color="red")
                except Exception:
                    pass

            plotter_macro.view_isometric() 
            backend_engine = "panel" if platform.system() == "Windows" else "trame"
            stpyvista(plotter_macro, key="macro_viewer", backend=backend_engine)

    except Exception as e:
        st.error(f"Error loading IFC file: {e}")

else:
    # --- IF NO FILE IS UPLOADED YET ---
    ifcbigfile = st.file_uploader("Drop a Big IFC file here", type=["ifc"]) 

    if ifcbigfile is not None:
        st.info("Saving, Patcing, and processing Geometry... Please wait.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_file:
            tmp_file.write(ifcbigfile.getbuffer())
            st.session_state['current_ifcbig_path'] = tmp_file.name
            
        st.rerun()