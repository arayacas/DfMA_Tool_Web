import streamlit as st
import os
import sys
import json
import pyvista as pv
from stpyvista import stpyvista
import UI_Helpers
import platform

# --- 1. PATH HACK FOR IMPORTS ---
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import Find_elements
import Constraints

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

st.set_page_config(
    layout="wide",
    page_title="Panel Connections",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

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

import streamlit as st
import os
import sys
import pyvista as pv

# (Assuming you use stpyvista for rendering in your app)
from stpyvista import stpyvista 

# --- PATH HACK FOR ENGINE ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import engine

st.set_page_config(page_title="Panel Connections", layout="wide")
st.title("Panel Connections")

if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']

    manual = st.toggle("Manual Mode, overwrite connectors")
    
    with st.spinner("Analyzing structural connections..."):
        try:
            # 3. Set up the 3D Plotter
            all_elements = Find_elements.get_elements(ifcfile_path)
            plotter = pv.Plotter(window_size=[800, 600])
            plotter.background_color = "white"
            to_meters = 1000.0 
            # Filter out the structural members (ignore fasteners here)
            summary, _ = engine.analyse(st.session_state['current_ifc_path'])
                        
            # Filter for all elements the engine classified as a Fastener
            fasteners_and_connectors = [e for e in summary["elements"] if e["cls"] == "Fastener"]
            plotter = pv.Plotter(window_size=[800, 800])
            panel_meshes = Find_elements.get_3d_meshes(all_elements)
            fasteners = engine.get_fasteners_table(summary)
            fastener_meshes = Find_elements.get_3d_meshes(fasteners)
            
            # --- UI CONTROLS ---
            st.markdown("### View Controls")
            show_panel = st.toggle("Show Panel Members (Studs & Tracks)", value=True)
            
            # ---------------------------------------------------------
            # THE MAIN PANEL RENDERING (Wrapped in the toggle)
            # ---------------------------------------------------------
            if show_panel:

                #Panel 3d Meshes
                for element, mesh in zip(all_elements, panel_meshes):
                    part_color = "lightgrey"
                                    
                    plotter.add_mesh(
                        mesh,
                        color=part_color,
                        show_edges=True,
                        edge_color="grey",
                        ambient=0.2,
                    )
                    
            # 4. The Brains: As-Designed vs. Recommended
            if len(fasteners_and_connectors) > 0 and manual==False:

                st.success(f"Ontology detected {len(fasteners_and_connectors)} native fasteners/connectors. Rendering As-Designed connections.")
                
                bolts_plotted = 0
                connectors_plotted = 0
                
                # --- AS-DESIGNED RENDERING LOGIC ---
                for f in fasteners_and_connectors:
                    pos = f.get("pos")
                    name = f.get("name", "").lower()
                    
                    if pos:
                        x, y, z = pos[0]/to_meters, pos[1]/to_meters, pos[2]/to_meters
                        
                        if "bolt" in name or "screw" in name:
                            axis = f.get("axis")
                            bolt_dir = (axis[0], axis[1], axis[2]) if axis else (0, 0, 1)
                            bolt_diam = (f.get("width") or 12.0) / to_meters
                            bolt_len = (f.get("length") or 30.0) / to_meters
                            
                            mesh = pv.Cylinder(center=(x, y, z), direction=bolt_dir, radius=bolt_diam/2.0, height=bolt_len)
                            plotter.add_mesh(mesh, color="gold", smooth_shading=True)
                            bolts_plotted += 1
                            
                        elif "connector" in name or "bracket" in name:
                            w = (f.get("width") or 50.0) / to_meters    # Leg length
                            d = (f.get("depth") or 50.0) / to_meters    # Extrusion (width of the bracket)
                            t = (f.get("thickness") or 5.0) / to_meters # Metal thickness
                                    
                                    # 2. Build the two legs of the L-shape at the origin
                                    # Leg 1 (The flat base plate)
                            leg1 = pv.Cube(center=(w/2, t/2, 0), x_length=w, y_length=t, z_length=d)
                                    # Leg 2 (The upright vertical plate)
                            leg2 = pv.Cube(center=(t/2, w/2, 0), x_length=t, y_length=d, z_length=w)

                            bracket_mesh = leg1 + leg2
                            bracket_mesh.translate((-w/2, -w/2, 0), inplace=True)
                            
                            # 4. Rotate it to face the right way (Tweak this 90 depending on your IFC axis)
                            bracket_mesh.rotate_y(90, inplace=True)
                            bracket_mesh.rotate_z(270, inplace=True)
                            bracket_mesh.rotate_x(0, inplace=True)   
                            
                            # 5. Move the finished bracket to the exact joint location
                            bracket_mesh.translate((x, y, z), inplace=True)
                            
                            # Draw it!
                            plotter.add_mesh(bracket_mesh, color="blue", smooth_shading=True)
                            connectors_plotted += 1

            else:
                # --- GEOMETRIC JOINT RECOMMENDATION ENGINE (AABB + HOLE DETECTION) ---
                st.warning("No native fasteners found. Initiating Geometric Joint Recommendation...")
                
                st.markdown("#### Joint Recommendation Parameters")
                col1, col2 = st.columns(2)
                with col1:
                    connection_type = st.radio("Connection Method (For joints without pre-drilled holes)", ["Fastening", "Welding"])
                with col2:
                    inflate_size = st.slider("Connection Zone Tolerance (mm)", min_value=0.0, max_value=150.0, value=25.0, step=5.0)
                
                tol = inflate_size / 1000.0  
                recommended_fasteners = 0
                recommended_welds = 0
                
                # --- NEW: Initialize Data Tracking for the Table ---
                import pandas as pd
                connection_table_data = []
                conn_id = 1
                
                # 1. Fetch Holes (IfcOpeningElement)
                import ifcopenshell
                model = ifcopenshell.open(ifcfile_path)
                holes = model.by_type("IfcOpeningElement")
                hole_points = []
                
                for h in holes:
                    try:
                        coords = h.ObjectPlacement.RelativePlacement.Location.Coordinates
                        hole_points.append((coords[0]/1000.0, coords[1]/1000.0, coords[2]/1000.0))
                    except:
                        pass
                
                def get_overlap_center(min1, max1, min2, max2, buffer):
                    i_min1, i_max1 = min1 - buffer, max1 + buffer
                    i_min2, i_max2 = min2 - buffer, max2 + buffer
                    intersect_min = max(i_min1, i_min2)
                    intersect_max = min(i_max1, i_max2)
                    if intersect_min <= intersect_max:
                        return (intersect_min + intersect_max) / 2.0
                    return None

                bounds_list = [mesh.bounds for mesh in panel_meshes]
                
                # 2. Find intersecting zones
                for i in range(len(bounds_list)):
                    for j in range(i + 1, len(bounds_list)):
                        b1 = bounds_list[i]
                        b2 = bounds_list[j]
                        
                        cx = get_overlap_center(b1[0], b1[1], b2[0], b2[1], tol/2)
                        cy = get_overlap_center(b1[2], b1[3], b2[2], b2[3], tol/2)
                        cz = get_overlap_center(b1[4], b1[5], b2[4], b2[5], tol/2)
                        
                        if cx is not None and cy is not None and cz is not None:
                            # --- A CONNECTION ZONE IS FOUND! ---
                            box_size = max(0.06, tol * 2)
                            zone_mesh = pv.Cube(center=(cx, cy, cz), x_length=box_size, y_length=box_size, z_length=box_size)
                            plotter.add_mesh(zone_mesh, color="lime", style="wireframe", opacity=0.3)
                            
                            # Perpendicularity Check
                            dx1, dy1, dz1 = b1[1]-b1[0], b1[3]-b1[2], b1[5]-b1[4]
                            axis1 = 0 if dx1 > max(dy1, dz1) else (1 if dy1 > dz1 else 2)
                            
                            dx2, dy2, dz2 = b2[1]-b2[0], b2[3]-b2[2], b2[5]-b2[4]
                            axis2 = 0 if dx2 > max(dy2, dz2) else (1 if dy2 > dz2 else 2)
                            
                            is_perpendicular = (axis1 != axis2)

                            # Orientation Engine
                            ox = max(0.0001, min(b1[1]+tol, b2[1]+tol) - max(b1[0]-tol, b2[0]-tol))
                            oy = max(0.0001, min(b1[3]+tol, b2[3]+tol) - max(b1[2]-tol, b2[2]-tol))
                            oz = max(0.0001, min(b1[5]+tol, b2[5]+tol) - max(b1[4]-tol, b2[4]-tol))
                            
                            min_overlap = min(ox, oy, oz)
                            
                            if min_overlap == ox:
                                rot_x, rot_y, rot_z = 0, 90, 0
                                bolt1_dir, bolt2_dir = (0, 1, 0), (0, 0, 1)
                                flat_plate_dims = (0.005, box_size, box_size * 1.5)
                                direct_bolt_dir = (1, 0, 0)
                            elif min_overlap == oy:
                                rot_x, rot_y, rot_z = 90, 0, 0
                                bolt1_dir, bolt2_dir = (1, 0, 0), (0, 0, 1)
                                flat_plate_dims = (box_size, 0.005, box_size * 1.5)
                                direct_bolt_dir = (0, 1, 0)
                            else:
                                rot_x, rot_y, rot_z = 0, 0, 0
                                bolt1_dir, bolt2_dir = (1, 0, 0), (0, 1, 0)
                                flat_plate_dims = (box_size * 1.5, box_size, 0.005)
                                direct_bolt_dir = (0, 0, 1)

                            # Check for holes
                            has_hole = False
                            for hx, hy, hz in hole_points:
                                dist = ((cx-hx)**2 + (cy-hy)**2 + (cz-hz)**2)**0.5
                                if dist <= (tol * 2):  
                                    has_hole = True
                                    break
                            
                            # --- 4. Apply DfMA Rules & Log Data! ---
                            if has_hole or connection_type == "Fastening":
                                
                                if is_perpendicular:
                                    w, d, t_thick = 0.05, 0.05, 0.005 
                                    leg1 = pv.Cube(center=(w/2, t_thick/2, 0), x_length=w, y_length=t_thick, z_length=d)
                                    leg2 = pv.Cube(center=(t_thick/2, w/2, 0), x_length=t_thick, y_length=w, z_length=d)
                                    bracket = leg1 + leg2
                                    bracket.translate((-w/2, -w/2, 0), inplace=True)
                                    if rot_x: bracket.rotate_x(rot_x, inplace=True)
                                    if rot_y: bracket.rotate_y(rot_y, inplace=True)
                                    if rot_z: bracket.rotate_z(rot_z, inplace=True)
                                    bracket.translate((cx, cy, cz), inplace=True) 
                                    plotter.add_mesh(bracket, color="blue", smooth_shading=True)
                                    
                                    shift = 0.015
                                    b1_center = (cx + bolt2_dir[0]*shift, cy + bolt2_dir[1]*shift, cz + bolt2_dir[2]*shift)
                                    b2_center = (cx + bolt1_dir[0]*shift, cy + bolt1_dir[1]*shift, cz + bolt1_dir[2]*shift)
                                    bolt1 = pv.Cylinder(center=b1_center, direction=bolt1_dir, radius=0.006, height=0.04)
                                    bolt2 = pv.Cylinder(center=b2_center, direction=bolt2_dir, radius=0.006, height=0.04)
                                    plotter.add_mesh(bolt1, color="gold", smooth_shading=True)
                                    plotter.add_mesh(bolt2, color="gold", smooth_shading=True)
                                    
                                    recommended_fasteners += 2
                                    
                                    # --- NEW: Log Perpendicular Data ---
                                    connection_table_data.append({
                                        "Connection #": f"J-{conn_id:03d}",
                                        "Location Type": "Perpendicular (L-Bracket)",
                                        "Fasteners Qty": 2,
                                        "Connectors Qty": 1,
                                        "Coordinates (X, Y, Z) m": f"({cx:.3f}, {cy:.3f}, {cz:.3f})"
                                    })
                                    
                                else:
                                    plate = pv.Cube(center=(cx, cy, cz), x_length=flat_plate_dims[0], y_length=flat_plate_dims[1], z_length=flat_plate_dims[2])
                                    plotter.add_mesh(plate, color="blue", smooth_shading=True)
                                    bolt = pv.Cylinder(center=(cx, cy, cz), direction=direct_bolt_dir, radius=0.006, height=0.08)
                                    plotter.add_mesh(bolt, color="gold", smooth_shading=True)
                                    
                                    recommended_fasteners += 1
                                    
                                    # --- NEW: Log Parallel Data ---
                                    connection_table_data.append({
                                        "Connection #": f"J-{conn_id:03d}",
                                        "Location Type": "Parallel (Flat Splice)",
                                        "Fasteners Qty": 1,
                                        "Connectors Qty": 1,
                                        "Coordinates (X, Y, Z) m": f"({cx:.3f}, {cy:.3f}, {cz:.3f})"
                                    })
                                
                            else:
                                weld_dims = (0.005, box_size, box_size) if min_overlap == ox else ((box_size, 0.005, box_size) if min_overlap == oy else (box_size, box_size, 0.005))
                                weld_mesh = pv.Cube(center=(cx, cy, cz), x_length=weld_dims[0], y_length=weld_dims[1], z_length=weld_dims[2])
                                plotter.add_mesh(weld_mesh, color="purple", opacity=0.9, smooth_shading=True)
                                
                                recommended_welds += 1
                                
                                # --- NEW: Log Weld Data ---
                                connection_table_data.append({
                                    "Connection #": f"J-{conn_id:03d}",
                                    "Location Type": "Weld Bead",
                                    "Fasteners Qty": 0,
                                    "Connectors Qty": 0,
                                    "Coordinates (X, Y, Z) m": f"({cx:.3f}, {cy:.3f}, {cz:.3f})"
                                })
                            
                            # Increment the Joint ID for the next loop
                            conn_id += 1
                                
                st.info(f"DfMA Analysis complete! Recommended **{recommended_fasteners} Fasteners** and **{recommended_welds} Welds**.")
                
            # --- RENDER 3D MODEL ---
            stpyvista(plotter)
            
            # --- NEW: RENDER THE DATA TABLE ---
            if 'connection_table_data' in locals() and len(connection_table_data) > 0:
                st.markdown("---")
                st.markdown("### Generated Connection Coordinates & BOM")
                df_connections = pd.DataFrame(connection_table_data)
                
                # Render clean dataframe
                st.dataframe(df_connections, use_container_width=True)
                
                # Optional: Add a download button so the robot programmer can export the CSV!
                csv = df_connections.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download Connection Elements & Coordinates (CSV)",
                    data=csv,
                    file_name='panel_connections_bom.csv',
                    mime='text/csv',
                )
        except Exception as e:
            st.error(f"Error during Connection Analysis: {e}")
        
else:
    st.warning("⚠️ No IFC file loaded. Please upload a model on the Start page.")