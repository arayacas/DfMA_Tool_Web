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

# --- 2. PAGE SETUP ---
st.set_page_config(page_title="3D Visualizer", layout="wide")

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

st.title("3D Panel Visualizer")

# --- 3. LOAD CLOUD-SAFE CONSTRAINTS ---
# Instead of a hardcoded folder, we grab the unique temp file path generated on Start.py
config_path = st.session_state.get('config_path', None)

default_max_length = 6.00
default_max_height = 3.00
default_hole_tol = 0.010
default_track_cont_tol = 0.020
default_track_hole_tol = 0.020
default_max_weight = 50.0

# Defaults for the Hole Sizer (in millimeters!)
default_allowed_holes_mm = "14, 34"
default_hole_size_tol_mm = 2.0

if config_path and os.path.exists(config_path):
    try:
        with open(config_path, "r") as f:
            saved_data = json.load(f)
            default_max_length = float(saved_data.get("max_length", 6.00))
            default_max_height = float(saved_data.get("max_height", 3.00))
            default_hole_tol = float(saved_data.get("hole_tol", 0.010))
            default_track_cont_tol = float(saved_data.get("track_cont_tol", 0.020))
            default_track_hole_tol = float(saved_data.get("track_hole_tol", 0.020))
            default_max_weight = float(saved_data.get("max_weight", 50.0))
            
            # Load our new mm variables
            default_allowed_holes_mm = str(saved_data.get("allowed_holes_mm", "14, 34"))
            default_hole_size_tol_mm = float(saved_data.get("hole_size_tol_mm", 2.0))
    except Exception:
        pass 

# --- 4. THE GATEWAY CHECK ---
if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']
    st.info("Scanning for physical parts...")
    
    try:
        all_elements = Find_elements.get_elements(ifcfile_path)
        
        if len(all_elements) > 0:
            st.markdown("---")
            
            # --- CREATE THE DASHBOARD LAYOUT ---
            left_col, right_col = st.columns([1, 3])
            
            with left_col:
                st.markdown("### Design Parameters")
                mini_left_col, mini_right_col = st.columns([2, 2])

                with mini_left_col:
                    hole_tol = st.number_input("Stud Hole Alignment (m)", value=default_hole_tol, step=0.005, format="%.3f")
                    track_cont_tol = st.number_input("Track Continuity (m)", value=default_track_cont_tol, step=0.005, format="%.3f")
                    track_hole_tol = st.number_input("Plumb Drop Alignment (m)", value=default_track_hole_tol, step=0.005, format="%.3f")

                with mini_right_col:
                    max_weight = st.number_input("Max Element Weight (kg)", value=default_max_weight, step=5.0, format="%.1f")
                    allowed_holes_str_mm = st.text_input("Allowed Hole Sizes (mm)", value=default_allowed_holes_mm, help="e.g., 14, 34")
                    hole_size_tol_mm = st.number_input("Hole Size Tolerance (mm)", value=default_hole_size_tol_mm, step=0.01, format="%.2f")

                # Overwrite the Cloud JSON file dynamically
                if config_path:
                    new_config = {
                        "max_length": default_max_length, 
                        "max_height": default_max_height, 
                        "hole_tol": hole_tol,
                        "track_cont_tol": track_cont_tol,
                        "track_hole_tol": track_hole_tol,
                        "max_weight": max_weight,
                        "allowed_holes_mm": allowed_holes_str_mm,
                        "hole_size_tol_mm": hole_size_tol_mm
                    }
                    try:
                        with open(config_path, "w") as f:
                            json.dump(new_config, f, indent=4)
                    except Exception as e:
                        st.error(f"Failed to save constraints: {e}")

                # --- Convert UI mm to Engine meters ---
                try:
                    allowed_sizes_list_m = [float(x.strip()) / 1000.0 for x in allowed_holes_str_mm.split(",")]
                except ValueError:
                    allowed_sizes_list_m = [0.034] 
                
                hole_size_tol_m = hole_size_tol_mm / 1000.0

                # -- RULES ENGINE --
                # Notice we are now explicitly passing the parameters here!
                size_rule_report = Constraints.check_max_dimensions(all_elements, max_length_mm=default_max_length, max_height_mm=default_max_height)
                
                alignedhole_rule_report = Constraints.check_hole_alignment(all_elements, tolerance_m=hole_tol)
                customhole_rule_report = Constraints.check_custom_holes(all_elements)
                track_rule_report = Constraints.check_track_continuity(all_elements, tolerance_m=track_cont_tol)
                track_hole_report = Constraints.check_track_hole_alignment(all_elements, tolerance_m=track_hole_tol)
                weight_report = Constraints.check_max_weight(all_elements, max_weight_kg=max_weight)
                
                hole_size_report = Constraints.check_hole_sizes(
                    all_elements, 
                    allowed_sizes_m=allowed_sizes_list_m, 
                    tolerance_m=hole_size_tol_m
                )

                # -- WARNINGS & ERROR PART PAINT--
                red_parts = (size_rule_report.get("violating_elements", []) 
                            + alignedhole_rule_report.get("violating_elements", [])
                            + track_rule_report.get("violating_elements", []) 
                            + track_hole_report.get("violating_elements", [])
                            + weight_report.get("violating_elements", [])
                            + hole_size_report.get("violating_elements", []) 
                            )
                
                orange_parts = customhole_rule_report.get("warning_elements", [])     

            # ==========================================
            # RIGHT COLUMN: 3D VIEWER
            # ==========================================
            with right_col:
                header_col1, header_col2 = st.columns([3, 1])
                with header_col1:
                    st.markdown("### 3D Panel Viewer")
                with header_col2:
                    show_alignment = st.toggle("Show Alignment Lines", value=False)
                
                plotter = pv.Plotter(window_size=[800, 800])
                panel_meshes = Find_elements.get_3d_meshes(all_elements)
                
                for element, mesh in zip(all_elements, panel_meshes):
                    if element in red_parts: part_color = "red"
                    elif element in orange_parts: part_color = "orange"
                    else: part_color = "lightgrey"
                    
                    plotter.add_mesh(
                        mesh,
                        color=part_color,
                        show_edges=True,
                        edge_color="grey",
                        ambient=0.2,
                    )

                # --- DRAW LASER ALIGNMENT LINES ---
                if show_alignment:
                    bounds = plotter.bounds 
                    xmin, xmax, ymin, ymax, zmin, zmax = bounds
                    y_center = (ymin + ymax) / 2  
                    
                    if "rows" in alignedhole_rule_report:
                        for row in alignedhole_rule_report["rows"]:
                            if len(row) > 0:
                                z_val = row[0].get("z_height", 0)
                                line = pv.Line((xmin, y_center, z_val), (xmax, y_center, z_val))
                                plotter.add_mesh(line, color="blue", line_width=4, render_lines_as_tubes=True)

                    if "columns" in track_hole_report:
                        for col in track_hole_report["columns"]:
                            if len(col) > 0:
                                x_val = col[0].get("x_pos", 0)
                                line = pv.Line((x_val, y_center, zmin), (x_val, y_center, zmax))
                                plotter.add_mesh(line, color="magenta", line_width=4, render_lines_as_tubes=True)
                                
                # --- DRAW THE RED TRACKERS FOR FAILED HOLES ---
                bad_hole_locations = hole_size_report.get("violating_hole_coords", [])
                for loc in bad_hole_locations:
                    sphere = pv.Sphere(radius=0.02, center=(loc[0], loc[1], loc[2]))
                    plotter.add_mesh(sphere, color="red")

                plotter.set_background([1.0, 0.99, 0.94])
                plotter.view_isometric()

                backend_engine = "panel" if platform.system() == "Windows" else "trame"

                stpyvista(plotter, backend=backend_engine)

            # -- UI: PRINT THE REPORTS --
            st.markdown("---")
            st.markdown("### DfMA Report")
            
            if not size_rule_report["passed"]: st.error(size_rule_report["message"])
            else: st.success(size_rule_report["message"])
                
            if not alignedhole_rule_report["passed"]: st.error(alignedhole_rule_report["message"])
            else: st.success(alignedhole_rule_report["message"])
                
            if customhole_rule_report.get("has_holes"): st.warning(f"⚠️ {customhole_rule_report['message']}")
            else: st.success(customhole_rule_report["message"])

            if not track_rule_report.get("has_tracks", True): st.warning(f"⚠️ {track_rule_report['message']}")
            elif not track_rule_report["passed"]: st.error(track_rule_report["message"])
            else: st.success(track_rule_report["message"])

            if not track_hole_report["passed"]: st.error(track_hole_report["message"])
            else: st.success(track_hole_report["message"])  

            if not weight_report["passed"]: st.error(weight_report["message"])
            else: st.success(weight_report["message"])
            
            if not hole_size_report["passed"]: st.error(hole_size_report["message"])
            else: st.success(hole_size_report["message"])

    except Exception as e:
        st.error(f"Oops, something went wrong reading the IFC: {e}")

else:
    st.warning("⚠️ No IFC file found! Please upload a file on the Start page first.")