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
            # 3. Set up the 3D Plotter
            plotter = pv.Plotter(window_size=[800, 600])
            plotter.background_color = "white"
            
            # --- NEW: ADD THE CAD-STYLE COMPASS ---
            plotter.add_axes(line_width=5, labels_off=False, color="black")
            
            to_meters = 1000.0
            
                        
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
            if len(fasteners_and_connectors) > 0 and manual == False:
                st.success(f"Ontology detected {len(fasteners_and_connectors)} native fasteners/connectors. Rendering As-Designed connections.")
                
                bolts_plotted = 0
                connectors_plotted = 0

                # 1. Initialize the override dictionary in session state if it doesn't exist
                if 'manual_rotations' not in st.session_state:
                    st.session_state.manual_rotations = {}

                st.markdown("### Manual Connector Overrides")

                # Filter out only the connectors so the dropdown isn't cluttered with studs/bolts
                connector_list = [f for f in fasteners_and_connectors if "connector" in f.get("name", "").lower() or "bracket" in f.get("name", "").lower()]

                if connector_list:
                    # Create a clean dictionary for the dropdown: {"Bracket Name (GlobalId)": "GlobalId"}
                    conn_options = {f"{c.get('name', 'Connector')} ({c['gid']})": c['gid'] for c in connector_list}
                    
                    selected_label = st.selectbox("Select a connector to manually rotate:", list(conn_options.keys()))
                    selected_gid = conn_options[selected_label]
                    
                    # --- NEW: Add the Highlight Toggle ---
                    highlight_selected = st.toggle("Highlight Selected Connector in 3D View", value=True)

                    # Fetch existing overrides if the user already tweaked this one, else default to 0
                    current_rot = st.session_state.manual_rotations.get(selected_gid, {"x": 0, "y": 0, "z": 0})
                    
                    # Layout the controls
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        rx = st.number_input("Add X Rotation", value=current_rot["x"], step=90, key=f"rx_{selected_gid}")
                    with col2:
                        ry = st.number_input("Add Y Rotation", value=current_rot["y"], step=90, key=f"ry_{selected_gid}")
                    with col3:
                        rz = st.number_input("Add Z Rotation", value=current_rot["z"], step=90, key=f"rz_{selected_gid}")
                        
                    # Save the new values back to memory (Streamlit will automatically rerun and apply them!)
                    st.session_state.manual_rotations[selected_gid] = {"x": rx, "y": ry, "z": rz}
                
                # --- NEW: Initialize the Data Tracker ---
                import pandas as pd
                as_designed_data = []
                
                # --- AS-DESIGNED RENDERING LOGIC ---
                for f in fasteners_and_connectors:
                    pos = f.get("pos")
                    name = f.get("name", "").lower()
                    gid = f.get("gid")
                    
                    if pos:
                        x, y, z = pos[0]/to_meters, pos[1]/to_meters, pos[2]/to_meters
                        axis = f.get("axis")
                        
                        # Default manual rotations to 0
                        man_rx, man_ry, man_rz = 0, 0, 0
                        comp_type = "Unknown"
                        
                        # ... (Keep all your existing PyVista Drawing Logic for Bolts here) ...
                        if "bolt" in name or "screw" in name:
                            comp_type = "Fastener (Bolt/Screw)"
                            # ... your bolt rendering code ...
                            
                        # ... (Keep all your existing PyVista Drawing Logic for Connectors here) ...
                        elif "connector" in name or "bracket" in name:
                            comp_type = "Connector (Bracket)"
                            # ... your bracket rendering code ...
                            
                            # Trap the manual overrides for the CSV export!
                            if gid in st.session_state.manual_rotations:
                                man_rx = st.session_state.manual_rotations[gid]["x"]
                                man_ry = st.session_state.manual_rotations[gid]["y"]
                                man_rz = st.session_state.manual_rotations[gid]["z"]
                                
                        # --- NEW: Log the exact coordinates and orientations! ---
                        as_designed_data.append({
                            "GlobalId": gid,
                            "Part Type": comp_type,
                            "Name": f.get("name", "Unknown"),
                            "Location X (m)": round(x, 4),
                            "Location Y (m)": round(y, 4),
                            "Location Z (m)": round(z, 4),
                            "IFC Axis X": round(axis[0], 4) if axis else 0,
                            "IFC Axis Y": round(axis[1], 4) if axis else 0,
                            "IFC Axis Z": round(axis[2], 4) if axis else 1,
                            "Manual Override X (deg)": man_rx,
                            "Manual Override Y (deg)": man_ry,
                            "Manual Override Z (deg)": man_rz
                        })
                        
                        if "bolt" in name or "screw" in name:
                            axis = f.get("axis")
                            bolt_dir = (axis[0], axis[1], axis[2]) if axis else (0, 0, 1)
                            bolt_diam = (f.get("width") or 12.0) / to_meters
                            bolt_len = (f.get("length") or 30.0) / to_meters
                            
                            mesh = pv.Cylinder(center=(x, y, z), direction=bolt_dir, radius=bolt_diam/2.0, height=bolt_len)
                            plotter.add_mesh(mesh, color="gold", smooth_shading=True)
                            bolts_plotted += 1
                            
                        elif "connector" in name or "bracket" in name:
                            # 1. Fetch exact dimensions
                            w = (f.get("width") or 50.0) / to_meters    
                            d = (f.get("depth") or 50.0) / to_meters    
                            t = (f.get("thickness") or 5.0) / to_meters 
                            
                            # 2. Build the two legs of the L-shape at the origin
                            leg1 = pv.Cube(center=(0, t/2, w/2), x_length=w, y_length=t, z_length=d)
                            leg2 = pv.Cube(center=(t/2, w/2, 0), x_length=t, y_length=w, z_length=d)
                            #Leg2 Mofifiers
                            leg1.translate((-w/2, w, -d/2), inplace=True)
                            bracket_mesh = leg1 + leg2

                            
                            # 3. ROTATION LOGIC (Using the IFC Axis!)
                            axis = f.get("axis")
                            
                            # We check which primary axis the bracket is pointing along
                            if axis:
                                # If pointing mostly along X
                                if abs(axis[0]) > 0.5: 
                                    bracket_mesh.rotate_y(90, inplace=True)
                                    # Handle Yaw based on sign
                                    if axis[0] < 0: bracket_mesh.rotate_y (180, inplace=True)
                                    
                                # If pointing mostly along Y
                                elif abs(axis[1]) > 0.5:
                                    bracket_mesh.rotate_x(90, inplace=True)
                                    #Hard to vizualize but Z eje hacia adentro 
                                    if axis[1] < 0: bracket_mesh.rotate_x(180, inplace=True)
                                    
                                # If pointing mostly along Z (Default)
                                else:
                                    if axis[2] < 0: bracket_mesh.rotate_z(180, inplace=True)
                                    
                            # Fallback if no axis exists
                            else:
                                bracket_mesh.rotate_z(90, inplace=True)
                                
                            gid = f.get("gid")
                            if gid in st.session_state.manual_rotations:
                                manual_rot = st.session_state.manual_rotations[gid]
                                
                                # Apply the extra spins if they are not zero
                                if manual_rot["x"] != 0:
                                    bracket_mesh.rotate_x(manual_rot["x"], inplace=True)
                                if manual_rot["y"] != 0:
                                    bracket_mesh.rotate_y(manual_rot["y"], inplace=True)
                                if manual_rot["z"] != 0:
                                    bracket_mesh.rotate_z(manual_rot["z"], inplace=True)
                            # 4. Move to the joint location
                            # -d offset needed in the X axis, this one aligns perfectly 
                            bracket_mesh.translate((-d*1.5/2, 0, 0), inplace=True)
                            bracket_mesh.translate((x, y, z), inplace=True)
                            
                            # ==========================================
                            # NEW: HIGHLIGHT LOGIC
                            # ==========================================
                            # Default color is blue
                            connector_color = "blue"
                            
                            # Check if this specific bracket is the one selected in the dropdown
                            if 'selected_gid' in locals() and gid == selected_gid:
                                # If the user turned the toggle ON, paint it green!
                                if highlight_selected:
                                    connector_color = "lime" 
                            
                            # Draw it using the dynamic color
                            plotter.add_mesh(bracket_mesh, color=connector_color, smooth_shading=True)
                            connectors_plotted += 1

            else:
                # --- GEOMETRIC JOINT RECOMMENDATION ENGINE (V2: CLEAN SLATE) ---
                st.warning("No native fasteners found. Initiating Geometric Joint Recommendation...")
                
                st.markdown("#### Joint Recommendation Parameters")
                col1, col2 = st.columns(2)
                with col1:
                    connection_type = st.radio("Connection Method (For joints without pre-drilled holes)", ["Fastening", "Welding"])
                with col2:
                    inflate_size = st.slider("Connection Zone Tolerance (mm)", min_value=0.0, max_value=150.0, value=25.0, step=5.0)
                
                tol = inflate_size / 1000.0  
                
                import pandas as pd
                import ifcopenshell
                
                connection_table_data = []
                
                # 1. Fetch Exact Hole Geometries (IfcOpeningElement)
                model = ifcopenshell.open(ifcfile_path)
                holes = model.by_type("IfcOpeningElement")
                
                # Use your existing script to extract the actual 3D meshes of the holes!
                raw_hole_meshes = Find_elements.get_3d_meshes(holes)
                
                hole_data = []
                for raw_mesh in raw_hole_meshes:
                    if raw_mesh.n_points > 0: # Ensure the mesh is valid
                        # MAGIC TRICK: If the CAD software grouped multiple holes into one object,
                        # this splits them into separate geometric pieces!
                        bodies = raw_mesh.split_bodies()
                        
                        for body in bodies:
                            hx, hy, hz = body.center
                            bds = body.bounds
                            dx, dy, dz = bds[1]-bds[0], bds[3]-bds[2], bds[5]-bds[4]
                            
                            # For LGS sheet metal, the hole diameter is larger than the metal thickness.
                            # Therefore, the SHORTEST dimension of the hole is the drill axis.
                            min_dim = min(dx, dy, dz)
                            diam = max(dx, dy, dz) 
                            
                            if min_dim == dx:
                                h_dir = (1, 0, 0)
                            elif min_dim == dy:
                                h_dir = (0, 1, 0)
                            else:
                                h_dir = (0, 0, 1)
                                
                            hole_data.append({
                                "x": hx, "y": hy, "z": hz,
                                "dir": h_dir,
                                "diam": diam,
                                "length": 0.04 # Standardize bolt length to 40mm so it is visible
                            })

                def get_overlap_center(min1, max1, min2, max2, buffer):
                    i_min1, i_max1 = min1 - buffer, max1 + buffer
                    i_min2, i_max2 = min2 - buffer, max2 + buffer
                    intersect_min = max(i_min1, i_min2)
                    intersect_max = min(i_max1, i_max2)
                    if intersect_min <= intersect_max:
                        return (intersect_min + intersect_max) / 2.0
                    return None

                bounds_list = [mesh.bounds for mesh in panel_meshes]
                
                # ==========================================
                # PASS 1: GATHER JOINTS & HOLES
                # ==========================================
                detected_joints = []
                conn_id = 1
                
                for i in range(len(bounds_list)):
                    for j in range(i + 1, len(bounds_list)):
                        b1 = bounds_list[i]
                        b2 = bounds_list[j]
                        
                        cx = get_overlap_center(b1[0], b1[1], b2[0], b2[1], tol/2)
                        cy = get_overlap_center(b1[2], b1[3], b2[2], b2[3], tol/2)
                        cz = get_overlap_center(b1[4], b1[5], b2[4], b2[5], tol/2)
                        
                        if cx is not None and cy is not None and cz is not None:
                            box_size = max(0.06, tol * 2)

                            ox = max(0.0001, min(b1[1]+tol, b2[1]+tol) - max(b1[0]-tol, b2[0]-tol))
                            oy = max(0.0001, min(b1[3]+tol, b2[3]+tol) - max(b1[2]-tol, b2[2]-tol))
                            oz = max(0.0001, min(b1[5]+tol, b2[5]+tol) - max(b1[4]-tol, b2[4]-tol))
                            min_overlap = min(ox, oy, oz)
                            
                            if min_overlap == ox: bolt_dir = (1, 0, 0)
                            elif min_overlap == oy: bolt_dir = (0, 1, 0)
                            else: bolt_dir = (0, 0, 1)

                            # --- UPDATED: Check against our new geometric hole_data list ---
                            local_holes = []
                            for h in hole_data:
                                dist = ((cx-h["x"])**2 + (cy-h["y"])**2 + (cz-h["z"])**2)**0.5
                                if dist <= (tol * 2):  
                                    local_holes.append(h)
                                    
                            detected_joints.append({
                                "gid": f"J-{conn_id:03d}",
                                "cx": cx, "cy": cy, "cz": cz,
                                "box_size": box_size,
                                "bolt_dir": bolt_dir,
                                "local_holes": local_holes
                            })
                            conn_id += 1

                # ==========================================
                # UNIVERSAL MANUAL OVERRIDE UI
                # ==========================================
                if 'manual_overrides' not in st.session_state:
                    st.session_state.manual_overrides = {}

                st.markdown("### 🛠️ Connection Fine-Tuning (Overrides)")
                
                selected_gid = None
                highlight_selected = False

                if len(detected_joints) > 0:
                    override_options = {f"Generated Joint {j['gid']}": j['gid'] for j in detected_joints}
                    selected_label = st.selectbox("Select a generated joint to manually adjust:", list(override_options.keys()))
                    selected_gid = override_options[selected_label]
                    
                    highlight_selected = st.toggle("Highlight Selected Joint in 3D View (Lime Green)", value=True)
                    
                    current_ovr = st.session_state.manual_overrides.get(selected_gid, {"rx": 0, "ry": 0, "rz": 0, "tx": 0.0, "ty": 0.0, "tz": 0.0})
                    
                    st.markdown("**1. Rotation Overrides (Degrees)**")
                    r_col1, r_col2, r_col3 = st.columns(3)
                    with r_col1: rx = st.number_input("Pitch (X-Axis)", value=current_ovr["rx"], step=90, key="rx_rec")
                    with r_col2: ry = st.number_input("Yaw (Y-Axis)", value=current_ovr["ry"], step=90, key="ry_rec")
                    with r_col3: rz = st.number_input("Roll (Z-Axis)", value=current_ovr["rz"], step=90, key="rz_rec")

                    st.markdown("**2. Translation Overrides (Millimeters)**")
                    t_col1, t_col2, t_col3 = st.columns(3)
                    with t_col1: tx = st.number_input("Offset X (mm)", value=current_ovr["tx"], step=5.0, key="tx_rec")
                    with t_col2: ty = st.number_input("Offset Y (mm)", value=current_ovr["ty"], step=5.0, key="ty_rec")
                    with t_col3: tz = st.number_input("Offset Z (mm)", value=current_ovr["tz"], step=5.0, key="tz_rec")
                        
                    st.session_state.manual_overrides[selected_gid] = {"rx": rx, "ry": ry, "rz": rz, "tx": tx, "ty": ty, "tz": tz}


                # ==========================================
                # PASS 2: RENDER BOLTS IN EXACT HOLES
                # ==========================================
                recommended_fasteners = 0
                recommended_welds = 0
                
                for j in detected_joints:
                    gid = j["gid"]
                    cx, cy, cz = j["cx"], j["cy"], j["cz"]
                    bolt_dir = j["bolt_dir"]
                    local_holes = j["local_holes"]
                    box_size = j["box_size"]
                    
                    ovr = st.session_state.manual_overrides.get(gid, {"rx": 0, "ry": 0, "rz": 0, "tx": 0.0, "ty": 0.0, "tz": 0.0})
                    
                    zone_mesh = pv.Cube(center=(cx, cy, cz), x_length=box_size, y_length=box_size, z_length=box_size)
                    plotter.add_mesh(zone_mesh, color="lime", style="wireframe", opacity=0.1)

                    bolt_color = "lime" if (selected_gid == gid and highlight_selected) else "gold"
                    
                    if len(local_holes) > 0:
                        # --- 1. RENDER THE BOLTS (PANCAKES) ---
                        for idx, h in enumerate(local_holes):
                            bolt = pv.Cylinder(
                                center=(0,0,0), 
                                direction=h["dir"], 
                                radius=h["diam"]/2.0, 
                                height=h["length"]
                            )
                            
                            if ovr["rx"] != 0: bolt.rotate_x(ovr["rx"], inplace=True)
                            if ovr["ry"] != 0: bolt.rotate_y(ovr["ry"], inplace=True)
                            if ovr["rz"] != 0: bolt.rotate_z(ovr["rz"], inplace=True)
                            
                            bolt.translate((h["x"] + ovr["tx"]/1000.0, h["y"] + ovr["ty"]/1000.0, h["z"] + ovr["tz"]/1000.0), inplace=True)
                            plotter.add_mesh(bolt, color=bolt_color, smooth_shading=True)
                            recommended_fasteners += 1
                            
                            connection_table_data.append({
                                "GlobalId": f"{gid}-Bolt{idx+1}",
                                "Part Type": "Fastener (Bolt)",
                                "Name": f"Hole-Snapped Bolt {idx+1}",
                                "Base Loc X (m)": round(h["x"], 4), "Base Loc Y (m)": round(h["y"], 4), "Base Loc Z (m)": round(h["z"], 4),
                                "IFC Axis X": round(h["dir"][0], 4), "IFC Axis Y": round(h["dir"][1], 4), "IFC Axis Z": round(h["dir"][2], 4),
                                "Override Trans X (mm)": ovr["tx"], "Override Trans Y (mm)": ovr["ty"], "Override Trans Z (mm)": ovr["tz"],
                                "Override Rot X (deg)": ovr["rx"], "Override Rot Y (deg)": ovr["ry"], "Override Rot Z (deg)": ovr["rz"]
                            })

                        # ==========================================
                        # --- 2. DYNAMIC BRACKET GENERATION ---
                        # ==========================================
                        
                        # Group the holes based on which way they are pointing
                        x_holes = [h for h in local_holes if abs(h["dir"][0]) > 0.5]
                        y_holes = [h for h in local_holes if abs(h["dir"][1]) > 0.5]
                        z_holes = [h for h in local_holes if abs(h["dir"][2]) > 0.5]

                        t = 0.005 # 5mm sheet metal thickness
                        bracket_mesh = None
                        
                        # Build the faces of the "cube" that actually contain holes
                        if x_holes:
                            avg_x = sum(h["x"] for h in x_holes) / len(x_holes)
                            leg = pv.Cube(center=(avg_x - cx, 0, 0), x_length=t, y_length=box_size, z_length=box_size)
                            bracket_mesh = leg if bracket_mesh is None else bracket_mesh + leg
                            
                        if y_holes:
                            avg_y = sum(h["y"] for h in y_holes) / len(y_holes)
                            leg = pv.Cube(center=(0, avg_y - cy, 0), x_length=box_size, y_length=t, z_length=box_size)
                            bracket_mesh = leg if bracket_mesh is None else bracket_mesh + leg
                            
                        if z_holes:
                            avg_z = sum(h["z"] for h in z_holes) / len(z_holes)
                            leg = pv.Cube(center=(0, 0, avg_z - cz), x_length=box_size, y_length=box_size, z_length=t)
                            bracket_mesh = leg if bracket_mesh is None else bracket_mesh + leg

                        # Render and log the resulting bracket
                        if bracket_mesh is not None:
                            # Count how many planes were used to name the part correctly
                            plane_count = sum(1 for group in [x_holes, y_holes, z_holes] if group)
                            comp_type = "Perpendicular (Bracket)" if plane_count > 1 else "Parallel (Flat Splice)"

                            # Apply user's manual rotational overrides
                            if ovr["rx"] != 0: bracket_mesh.rotate_x(ovr["rx"], inplace=True)
                            if ovr["ry"] != 0: bracket_mesh.rotate_y(ovr["ry"], inplace=True)
                            if ovr["rz"] != 0: bracket_mesh.rotate_z(ovr["rz"], inplace=True)

                            # Move from local origin to the final 3D space
                            bracket_mesh.translate((cx + ovr["tx"]/1000.0, cy + ovr["ty"]/1000.0, cz + ovr["tz"]/1000.0), inplace=True)
                            
                            plotter.add_mesh(bracket_mesh, color="blue", smooth_shading=True)
                            
                            # Log the Connector for the CSV Exporter
                            connection_table_data.append({
                                "GlobalId": f"{gid}-Conn",
                                "Part Type": comp_type,
                                "Name": f"Generated Auto-Bracket",
                                "Base Loc X (m)": round(cx, 4), "Base Loc Y (m)": round(cy, 4), "Base Loc Z (m)": round(cz, 4),
                                "IFC Axis X": round(bolt_dir[0], 4), "IFC Axis Y": round(bolt_dir[1], 4), "IFC Axis Z": round(bolt_dir[2], 4),
                                "Override Trans X (mm)": ovr["tx"], "Override Trans Y (mm)": ovr["ty"], "Override Trans Z (mm)": ovr["tz"],
                                "Override Rot X (deg)": ovr["rx"], "Override Rot Y (deg)": ovr["ry"], "Override Rot Z (deg)": ovr["rz"]
                            })
                            
                    elif connection_type == "Welding":
                        # ... (Keep your existing Welding fallback code here exactly the same) ...
                        weld_dims = (0.005, box_size, box_size) if bolt_dir[0] != 0 else ((box_size, 0.005, box_size) if bolt_dir[1] != 0 else (box_size, box_size, 0.005))
                        weld_mesh = pv.Cube(center=(0,0,0), x_length=weld_dims[0], y_length=weld_dims[1], z_length=weld_dims[2])
                        
                        if ovr["rx"] != 0: weld_mesh.rotate_x(ovr["rx"], inplace=True)
                        if ovr["ry"] != 0: weld_mesh.rotate_y(ovr["ry"], inplace=True)
                        if ovr["rz"] != 0: weld_mesh.rotate_z(ovr["rz"], inplace=True)
                        
                        weld_mesh.translate((cx + ovr["tx"]/1000.0, cy + ovr["ty"]/1000.0, cz + ovr["tz"]/1000.0), inplace=True)
                        plotter.add_mesh(weld_mesh, color="purple", opacity=0.9, smooth_shading=True)
                        recommended_welds += 1
                        
                        connection_table_data.append({
                            "GlobalId": gid,
                            "Part Type": "Weld Bead",
                            "Name": f"Generated Weld",
                            "Base Loc X (m)": round(cx, 4),
                            "Base Loc Y (m)": round(cy, 4),
                            "Base Loc Z (m)": round(cz, 4),
                            "IFC Axis X": round(bolt_dir[0], 4),
                            "IFC Axis Y": round(bolt_dir[1], 4),
                            "IFC Axis Z": round(bolt_dir[2], 4),
                            "Override Trans X (mm)": ovr["tx"], "Override Trans Y (mm)": ovr["ty"], "Override Trans Z (mm)": ovr["tz"],
                            "Override Rot X (deg)": ovr["rx"], "Override Rot Y (deg)": ovr["ry"], "Override Rot Z (deg)": ovr["rz"]
                        })

                st.info(f"DfMA Analysis complete! Snapped **{recommended_fasteners} Fasteners** to pre-drilled holes and placed **{recommended_welds} Welds**.")
            # --- RENDER 3D MODEL ---
            stpyvista(plotter)
            
            # --- NEW: RENDER THE NATIVE DATA TABLE ---
            if 'as_designed_data' in locals() and len(as_designed_data) > 0:
                st.markdown("---")
                st.markdown("### Native Connection Data & Export")
                
                # Convert the tracked data into a Pandas DataFrame
                df_as_designed = pd.DataFrame(as_designed_data)
                
                # Display the interactive table on the screen
                st.dataframe(df_as_designed, use_container_width=True)
                
                # Generate the CSV for the Robot Programmer
                csv_native = df_as_designed.to_csv(index=False).encode('utf-8')
                
                st.download_button(
                    label="Download As-Designed Orientations & Coordinates (CSV)",
                    data=csv_native,
                    file_name='native_connections_bom.csv',
                    mime='text/csv',
                )
            
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