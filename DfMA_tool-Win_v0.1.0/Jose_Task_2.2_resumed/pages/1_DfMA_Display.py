"""
Description: 
    This script runs the DfMA tool through streamlit (Web Deployment Version)
    Extracts isolated IfcElementAssembly panels from massive building files.
    *UPDATED: Includes .ZIP STL Export for Robotics Simulation.*
"""

import streamlit as st
import os
import sys
import json
import pyvista as pv
from stpyvista import stpyvista
import platform
import tempfile
import zipfile
import io
from PIL import Image

# --- 1. PATH HACK FOR IMPORTS ---
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import Find_elements
import Constraints
import engine

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
images_dir = os.path.join(current_dir, "..", "..", "Images")

# Path hack to allow importing UI_Helpers from the parent directory
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
    page_title="DfMA Display",
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

st.title("3D Panel Visualizer")
assemble_flat = st.toggle("🔄 Evaluate Panel Laying Down (Rotate 90°)", value=False)

# --- 3. LOAD CLOUD-SAFE CONSTRAINTS ---
config_path = st.session_state.get('config_path', None)
params = st.session_state["design_params"]

# Defaults for rules
default_max_length = params["max_length"]
default_max_height = params["max_length"]
default_hole_tol = params["hole_tol"]
default_track_cont_tol = params["track_cont_tol"]
default_track_hole_tol = params["track_hole_tol"]
default_max_weight = params["max_weight"]
default_allowed_holes_mm = params["allowed_holes_mm"]
default_hole_size_tol_mm = params ["hole_size_tol_mm"]
default_part_max_length_mm = params["part_max_length_mm"]

if assemble_flat:
    max_length = params["max_height"]
    max_height = params["max_length"]
else:
    max_height = params["max_height"]
    max_length = params["max_length"]
    
hole_tol = params["hole_tol"]
track_hole_tol = params["track_hole_tol"]
track_cont_tol = params["track_cont_tol"]
allowed_holes_mm = params["allowed_holes_mm"]
hole_size_tol = params ["hole_size_tol_mm"]
max_weight = params["max_weight"]
max_parts = params["max_parts"]
stud_spacing_mm = params["stud_spacing_mm"]
stud_tol_mm = params["stud_tol_mm"]
joist_depth_tolerance_mm = params["joist_depth_tolerance_mm"]
part_max_length_mm = params["part_max_length_mm"]
part_max_height_mm = params["part_max_height_mm"]
part_max_depth_mm = params["part_max_depth_mm"]
hole_border_clearance_mm = params["hole_border_clearance_mm"]
slanted_beam_angle = params["slanted_beam_angle"]
total_assembly_payload_limit_kg = params["total_assembly_payload_limit_kg"]
CoG_radius_tolerance_mm = params["CoG_radius_tolerance_mm"]

# Pinned rules
pinned = st.session_state["pinned_rules"]

# --- 4. THE GATEWAY CHECK ---
if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']
    st.info("Scanning for physical parts...")
    
    try:
        all_elements = Find_elements.get_elements(ifcfile_path)
        summary, model = engine.analyse(ifcfile_path)
        
        if len(all_elements) > 0:
            st.markdown("---")
            
            # --- CREATE THE DASHBOARD LAYOUT ---
            left_col, right_col = st.columns([1, 3])
            
            with left_col:
                st.markdown("### Quick Access Parameters")
                pinned = st.session_state.get("pinned_rules", [])
                mini_left_col, mini_right_col = st.columns([2, 2])

                with mini_left_col:
                    if "max_length" in pinned:
                        params["max_length"] = st.number_input("Max Operational Length (m)", value=params["max_length"], step=0.5)
                    if "max_height" in pinned:
                        params["max_height"] = st.number_input("Max Operational Height (m)", value=params["max_height"], step=0.5)
                    if "total_assembly_payload_limit_kg" in pinned:
                        params["total_assembly_payload_limit_kg"] = st.number_input("Max Assembly Weight (kg)", value=params["total_assembly_payload_limit_kg"])
                    if "max_weight" in pinned:
                        params["max_weight"] = st.number_input("Max Element Weight (kg)", value=params["max_weight"], step=5.0)
                    if "part_max_length_mm" in pinned:
                        params["part_max_length_mm"] = st.number_input("Max Element Length (mm)", value=params["part_max_length_mm"])
                    if "part_max_height_mm" in pinned:
                        params["part_max_height_mm"] = st.number_input("Max Element Height (mm)", value=params["part_max_height_mm"])
                    if "part_max_depth_mm" in pinned:
                        params["part_max_depth_mm"] = st.number_input("Max Element Depth (mm)", value=params["part_max_depth_mm"])
                    if "max_parts" in pinned:
                        params["max_parts"] = st.number_input("Total Assembly Parts", value=params["max_parts"])
                    if "slanted_beam_angle" in pinned:
                        params["slanted_beam_angle"] = st.number_input("Slanted Beam Angle (°)", value=params["slanted_beam_angle"])

                with mini_right_col:
                    if "allowed_holes_mm" in pinned:
                        params["allowed_holes_mm"] = st.text_input("Allowed Hole Sizes (mm)", value=params["allowed_holes_mm"])
                    if "hole_size_tol_mm" in pinned:
                        params["hole_size_tol_mm"] = st.number_input("Hole Tolerance (mm)", value=params["hole_size_tol_mm"], step=0.5)
                    if "hole_tol" in pinned:
                        params["hole_tol"] = st.number_input("Stud Hole Alignment Tol", value=params["hole_tol"], step=0.005)
                    if "track_hole_tol" in pinned:
                        params["track_hole_tol"] = st.number_input("Vertical Drop Hole Tol", value=params["track_hole_tol"], step=0.005)
                    if "track_cont_tol" in pinned:
                        params["track_cont_tol"] = st.number_input("Track Continuity Length (m)", value=params["track_cont_tol"], step=0.005)
                    if "stud_spacing_mm" in pinned:
                        params["stud_spacing_mm"] = st.text_input("Stud Spacing (mm)", value=params["stud_spacing_mm"])
                    if "stud_tol_mm" in pinned:
                        params["stud_tol_mm"] = st.number_input("Stud Spacing Tolerance (mm)", value=params["stud_tol_mm"])
                    if "hole_border_clearance_mm" in pinned:
                        params["hole_border_clearance_mm"] = st.number_input("Hole-Border Clearance (mm)", value=params["hole_border_clearance_mm"])
                    if "CoG_radius_tolerance_mm" in pinned:
                        params["CoG_radius_tolerance_mm"] = st.number_input("Center of Gravity Tol (mm)", value=params["CoG_radius_tolerance_mm"])

                # -- RULES ENGINE --
                size_rule_report = Constraints.check_max_dimensions(all_elements, max_length_mm= max_length, max_height_mm= max_height)
                alignedhole_rule_report = Constraints.check_hole_alignment(all_elements, tolerance_m = hole_tol)
                customhole_rule_report = Constraints.check_custom_holes(all_elements)
                track_rule_report = Constraints.check_track_continuity(all_elements, tolerance_m = track_cont_tol)
                track_hole_report = Constraints.check_track_hole_alignment(all_elements, tolerance_m = track_hole_tol)
                weight_report = Constraints.check_max_weight(all_elements, max_weight_kg = max_weight)

                # Correction of Hole size Design Parameter:
                try:
                    allowed_sizes_list_m = [float(x.strip()) / 1000.0 for x in allowed_holes_mm.split(",")]
                except ValueError:
                    allowed_sizes_list_m = [0.034] 
                
                hole_size_tol_m = hole_size_tol / 1000.0
                hole_size_report = Constraints.check_hole_sizes(all_elements, allowed_sizes_m = allowed_sizes_list_m, tolerance_m = hole_size_tol_m)
                part_count_report = Constraints.check_part_count(all_elements, max_parts = max_parts)
                stud_spacing_report = Constraints.check_stud_spacing(all_elements, stud_spacing_mm, stud_tol_mm)
                joist_uniformity_report = Constraints.check_joist_uniformity(all_elements, joist_depth_tolerance_mm)
                part_size_report = Constraints.check_part_max_dimensions(all_elements, max_length_mm=params.get("part_max_length_mm", 1000.0), max_height_mm=params.get("part_max_height_mm", 1000.0), max_depth_mm=params.get("part_max_depth_mm", 300.0))
                cog_report = Constraints.check_center_of_gravity(all_elements, tolerance_mm=params.get("CoG_radius_tolerance_mm", 250.0))
                slanted_beam_report = Constraints.check_slanted_beam_angle(all_elements, 360.00)
                payload_report = Constraints.check_total_assembly_payload(all_elements, max_payload_kg=params.get("total_assembly_payload_limit_kg", 100.0))
                clearance_report = Constraints.check_hole_border_clearance(all_elements, min_clearance_mm=params.get("hole_border_clearance_mm", 20.0))

                # -- WARNINGS & ERROR PART PAINT--
                red_parts = (size_rule_report.get("violating_elements", []) 
                            + alignedhole_rule_report.get("violating_elements", [])
                            + track_rule_report.get("violating_elements", []) 
                            + track_hole_report.get("violating_elements", [])
                            + weight_report.get("violating_elements", [])
                            + hole_size_report.get("violating_elements", [])
                            + part_count_report.get("violating_elements", [])
                            + stud_spacing_report.get("violating_elements", [])
                            + joist_uniformity_report.get("violating_elements", [])
                            + part_size_report.get("violating_elements", [])
                            + cog_report.get("violating_elements", [])
                            + slanted_beam_report.get("violating_elements", [])
                            + payload_report.get("violating_elements", [])
                            + clearance_report.get("violating_elements", []))
                
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
                # 🛠️ FIX 1: Add off_screen=True and crank up the resolution!
                plotter = pv.Plotter(window_size=[800, 800], off_screen=True)

                panel_meshes = Find_elements.get_3d_meshes(all_elements)
                fasteners = engine.get_fasteners_table(summary)
                fastener_meshes = Find_elements.get_3d_meshes(fasteners)

                # Panel 3d Meshes
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

                with st.spinner("Extracting Fasteners & Ontology..."):
                    try:
                        summary, _ = engine.analyse(st.session_state['current_ifc_path'])
                        fasteners_and_connectors = [e for e in summary["elements"] if e["cls"] == "Fastener"]
                        
                        to_meters = 1000.0 
                        bolts_plotted = 0
                        
                        for f in fasteners_and_connectors:
                            pos = f.get("pos")
                            name = f.get("name", "").lower()
                            
                            if pos:
                                x = pos[0] / to_meters
                                y = pos[1] / to_meters
                                z = pos[2] / to_meters
                                
                                if "bolt" in name or "screw" in name:
                                    axis = f.get("axis")
                                    bolt_dir = (axis[0], axis[1], axis[2]) if axis else (0, 0, 1)
                                    bolt_diam = (f.get("width") or 12.0) / to_meters
                                    bolt_len = (f.get("length") or 30.0) / to_meters
                                    
                                    mesh = pv.Cylinder(
                                        center=(x, y, z), 
                                        direction=bolt_dir,
                                        radius=bolt_diam / 2.0, 
                                        height=bolt_len
                                    )
                                    
                                    plotter.add_mesh(mesh, color="gold", smooth_shading=True)
                                    bolts_plotted += 1
                            
                        st.success(f"Successfully rendered {bolts_plotted} bolts")

                    except Exception as e:
                        st.warning(f"Could not render semantic fasteners: {e}")
                
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
                            
                # --- DRAW CENTER OF GRAVITY (CoG) ---
                if "cog_coords" in cog_report and "geom_coords" in cog_report:
                    geom_center = cog_report["geom_coords"]
                    plotter.add_mesh(pv.Sphere(radius=0.03, center=geom_center), color="blue")
                    
                    cog_center = cog_report["cog_coords"]
                    cog_color = "green" if cog_report["passed"] else "red"
                    plotter.add_mesh(pv.Sphere(radius=0.04, center=cog_center), color=cog_color)
                    
                    line = pv.Line(geom_center, cog_center)
                    plotter.add_mesh(line, color="yellow", line_width=3)

                # --- DRAW TRACKERS FOR BORDER CLEARANCE FAILURES ---
                bad_clearance_locations = clearance_report.get("violating_hole_coords", [])
                for loc in bad_clearance_locations:
                    sphere = pv.Sphere(radius=0.025, center=(loc[0], loc[1], loc[2]))
                    plotter.add_mesh(sphere, color="red")
                                
                # --- DRAW THE RED TRACKERS FOR FAILED HOLES ---
                bad_hole_locations = hole_size_report.get("violating_hole_coords", [])
                for loc in bad_hole_locations:
                    sphere = pv.Sphere(radius=0.02, center=(loc[0], loc[1], loc[2]))
                    plotter.add_mesh(sphere, color="red")

                plotter.set_background([1.0, 0.99, 0.94])
                plotter.view_isometric()

                with st.spinner("Snapping High-Quality Screenshot..."):
                    try:
                        # Because off_screen=True is set, this will now work perfectly
                        img_array = plotter.screenshot(transparent_background=False, return_img=True)
                        render_img = Image.fromarray(img_array)
                        
                        img_buffer = io.BytesIO()
                        render_img.save(img_buffer, format="PNG")
                        img_buffer.seek(0)
                        
                        img_base_name = "Panel" 
                        if 'original_ifc_name' in st.session_state:
                            original_name = st.session_state['original_ifc_name']
                            img_base_name = original_name[:-4] if original_name.lower().endswith('.ifc') else original_name
                                
                        export_img_name = f"{img_base_name}_Render.png"
                        export_zip_name = f"{img_base_name}_STL_Members.zip"
                    except Exception as e:
                        img_buffer = None
                        st.error(f"Failed to capture image: {e}")

                backend_engine = "panel" if platform.system() == "Windows" else "trame"
                stpyvista(plotter, backend=backend_engine)

            # ==========================================
            # PREPARE SIMULATION STL ZIP FILE
            # ==========================================
            with st.spinner("Packaging Individual Parts for Simulation..."):
                zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for element, mesh in zip(all_elements, panel_meshes):
                        if mesh.n_points > 0:
                            sim_mesh = mesh.copy()
                            center_pt = sim_mesh.center
                            sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)
                            
                            el_name = str(element.Name).replace("/", "_").replace("\\", "_") if hasattr(element, 'Name') and element.Name else "Member"
                            el_id = str(element.GlobalId) if hasattr(element, 'GlobalId') else "UnknownID"
                            file_name = f"{el_name}_{el_id}.stl"
                            
                            with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
                                sim_mesh.save(tmp.name)
                                with open(tmp.name, "rb") as f:
                                    zip_file.writestr(file_name, f.read())
                            os.remove(tmp.name)

            # ==========================================
            # -- UI: EXPORTS & REPORTS --
            # ==========================================
            st.markdown("---")
            st.markdown("Panel Exports")
            
            export_col1, export_col2 = st.columns(2)
            
            with export_col1:
                st.info("The physics simulator needs each steel member to be an independent object. Download this ZIP to get perfectly centered, metric `.stl` files of every single element in this panel.")
                st.download_button(
                    label="Download All Individual Members (.ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name=export_zip_name,
                    mime="application/zip"
                )
                
            with export_col2:
                st.info("Download a high-resolution PNG image of the 3D visualizer, including all warning trackers and structural alignment lines.")
                # It will automatically find the img_buffer we created higher up!
                if img_buffer:
                    st.download_button(
                        label="Download High-Quality Render (.PNG)",
                        data=img_buffer,
                        file_name=export_img_name,
                        mime="image/png"
                    )
            
            st.markdown("---")
            st.markdown("### DfMA Report")
            
            if not size_rule_report["passed"]: st.error(size_rule_report["message"])
            else: st.success(size_rule_report["message"])
                
            if not alignedhole_rule_report["passed"]: st.error(alignedhole_rule_report["message"])
            else: st.success(alignedhole_rule_report["message"])
                
            if customhole_rule_report.get("has_holes"): st.warning(f"{customhole_rule_report['message']}")
            else: st.success(customhole_rule_report["message"])

            if not track_rule_report.get("has_tracks", True): st.warning(f"{track_rule_report['message']}")
            elif not track_rule_report["passed"]: st.error(track_rule_report["message"])
            else: st.success(track_rule_report["message"])

            if not track_hole_report["passed"]: st.error(track_hole_report["message"])
            else: st.success(track_hole_report["message"])  

            if not weight_report["passed"]: st.error(weight_report["message"])
            else: st.success(weight_report["message"])
            
            if not hole_size_report["passed"]: st.error(hole_size_report["message"])
            else: st.success(hole_size_report["message"])

            if not part_count_report["passed"]: st.error(part_count_report["message"])
            else: st.success(part_count_report["message"]) 
            
            if not stud_spacing_report["passed"]: st.error(stud_spacing_report["message"])
            else: st.success(stud_spacing_report["message"])

            if not joist_uniformity_report["passed"]: st.error(joist_uniformity_report["message"])
            else: st.success(joist_uniformity_report["message"]) 

            if not part_size_report["passed"]: st.error(part_size_report["message"])
            else: st.success(part_size_report["message"])

            if not cog_report["passed"]: st.error(cog_report["message"])
            else: st.success(cog_report["message"])

            if not slanted_beam_report["passed"]: st.error(slanted_beam_report["message"])
            else: st.success(slanted_beam_report["message"])

            if not payload_report["passed"]: st.error(payload_report["message"])
            else: st.success(payload_report["message"])

            if not clearance_report["passed"]: st.error(clearance_report["message"])
            else: st.success(clearance_report["message"])

    except Exception as e:
        st.error(f"Oops, something went wrong reading the IFC: {e}")

else:
    st.warning("No IFC file found! Please upload a file on the Start page first.")