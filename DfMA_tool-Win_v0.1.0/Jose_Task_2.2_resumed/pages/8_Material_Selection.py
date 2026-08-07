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
import pyvista as pv
from stpyvista import stpyvista
import os
from PIL import Image
import sys
import Find_elements
import Constraints
import engine
import pandas as pd
import numpy as np
import ifcopenshell.geom
import ifcopenshell.util.element

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
    page_title="Objective Functions",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

"""
Description: 
    Page 8 - Material Selection and Injection
    Reads a material-less IFC file loaded in Start.py, checks member thickness, 
    and dynamically injects Grade 50 (Orange Members) or Grade 33 (Blue Members) Steel materials.
"""

import streamlit as st
import os
import tempfile
import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element

# --- PAGE SETUP ---
st.set_page_config(layout="wide", page_title="Material Selection", page_icon="🏗️")

st.title("Material Selection & Injection")
st.markdown("Inject **Grade 50** (thickness ≥ 0.045in) and **Grade 33** (thickness < 0.045in) steel materials into your IFC building model.")

# --- HELPER FUNCTION: Calculate THICKNESS ---
import pandas as pd
import ifcopenshell.util.element

def calculate_geometric_thickness(member):
    """
    Bypasses missing text data by physically measuring the 3D geometry of the member.
    Generates a bounding box and returns the absolute smallest dimension (the thickness).
    """
    try:
        # 1. Initialize the geometry engine
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)
        
        # 2. Generate the physical 3D shape in memory
        shape = ifcopenshell.geom.create_shape(settings, member)
        
        # 3. Extract the raw vertices and group them into (X, Y, Z) coordinates
        verts = np.array(shape.geometry.verts).reshape((-1, 3))
        
        # 4. Calculate the bounding box dimensions (Max point minus Min point)
        # This returns an array of [Width, Depth, Height]
        dimensions = verts.max(axis=0) - verts.min(axis=0)
        
        # 5. The material thickness is inherently the smallest physical dimension of the bounding box
        thickness = np.min(dimensions)
        
        # Clean up microscopic floating point errors (e.g., turning 0.04510003 into 0.0451)
        return round(thickness, 4)
        
    except Exception as e:
        # If the member has no physical 3D geometry (like a virtual group), return None
        return None

# --- HELPER FUNCTION: EXTRACT THICKNESS ---
def get_thickness(member):
    """
    Hunts for thickness text. If missing, calculates it from raw 3D geometry.
    Note: Returns the raw unit of the file (inches for this specific file).
    """
    # 1. Try to read the text Property Sets first (fastest)
    try:
        psets = ifcopenshell.util.element.get_psets(member)
        for pset_name, properties in psets.items():
            for prop_name, prop_val in properties.items():
                if 'thickness' in prop_name.lower():
                    if isinstance(prop_val, str):
                        clean_val = ''.join(c for c in prop_val if c.isdigit() or c == '.')
                        return float(clean_val)
                    return float(prop_val)
    except Exception: pass
    
    # 2. If text is wiped out (Anonymized), calculate via Hardcore Math!
    calculated_thickness = calculate_geometric_thickness(member)
    if calculated_thickness is not None:
        return calculated_thickness
        
    return None

def detect_imperial_units(ifc_file):
    """
    Scans the IFC file's Unit Assignment to see if the primary length unit is in inches or feet.
    Returns True if Imperial, False if Metric (or assumed Metric).
    """
    try:
        # Grab the main project definition
        projects = ifc_file.by_type("IfcProject")
        if not projects:
            return False
            
        project = projects[0]
        
        # Look through the units assigned to the context
        if hasattr(project, 'UnitsInContext') and project.UnitsInContext:
            for unit in project.UnitsInContext.Units:
                # We only care about Length conversions (like inches)
                if unit.is_a('IfcConversionBasedUnit') and unit.UnitType == 'LENGTHUNIT':
                    unit_name = unit.Name.lower()
                    if 'inch' in unit_name or 'foot' in unit_name:
                        return True
    except Exception as e:
        pass # If it fails, default to metric
        
    return False

# --- 4. THE GATEWAY CHECK ---
if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']
    st.info("Scanning for physical parts and project units...")

    # ==========================================
    # 1. THE BODY: IFC GEOMETRY DATA
    # ==========================================
    try:
        # Load the raw IFC file using ifcopenshell to check units
        raw_ifc = ifcopenshell.open(ifcfile_path)
        
        # Check and set the unit flag in session state!
        if 'is_imperial' not in st.session_state:
            st.session_state['is_imperial'] = detect_imperial_units(raw_ifc)
            
        # Display a warning so the user knows what's happening
        if st.session_state['is_imperial']:
            st.warning("**Imperial Units Detected (Inches).**DfMA checks will adapt accordingly.")
        else:
            st.success("**Metric Units Detected (mm/m).**")

        # Load the elements (Assuming 'engine' is defined earlier in your script)
        summary, model = engine.analyse(ifcfile_path)
        all_elements = Find_elements.get_elements(ifcfile_path)
        vertical_studs, horizontal_tracks = Find_elements.sort_framing_by_orientation(all_elements)
        
        # Summary Metrics
        st.write(f"### Panel Composition")
        st.write(f"Total Structural Members: **{len(all_elements)}**")
        st.write(f"Vertical Studs: **{len(vertical_studs)}** | Horizontal Tracks: **{len(horizontal_tracks)}**")
        
        st.markdown("---")

        """
        Table Display, each tab has a different table tracking different rules numerically. 
        """

        # ==========================================
        # 1. The Thickness Table (Replaced Coordinates)
        # ==========================================
        st.write("### Member Thickness Data")
        
        thickness_data = []
        for member in all_elements:
            # Safely get the name and GlobalId
            name = member.Name if hasattr(member, 'Name') and member.Name else "Unnamed Member"
            guid = member.GlobalId if hasattr(member, 'GlobalId') else "N/A"
            ifc_type = member.is_a()
            
            # Extract thickness
            thickness = get_thickness(member)
            
            thickness_data.append({
                "GlobalId": guid,
                "Name": name,
                "Type": ifc_type,
                "Thickness Metric/Imperial": thickness if thickness is not None else "Not Found"
            })
        
        # Convert to DataFrame and display
        df_thickness = pd.DataFrame(thickness_data)
        st.dataframe(df_thickness, use_container_width=True)

    # ==========================================
        # 2. THE VISUALIZER: THICKNESS HIGHLIGHTING
        # ==========================================
        st.markdown("---")
        
        # We need two columns just like your sample
        left_col, right_col = st.columns([1, 2])
        
        # Determine our threshold based on the file units
        if st.session_state.get('is_imperial', False):
            threshold = 0.045
            unit_label = "in"
        else:
            threshold = 1.143
            unit_label = "mm"

        # Sort the members into groups for coloring
        thick_parts = [] # Grade 50 (Orange)
        thin_parts = []  # Grade 33 (Blue)
        unknown_parts = [] # Error/Grey
        
        for member in all_elements:
            thickness = get_thickness(member)
            if thickness is None:
                unknown_parts.append(member)
            elif thickness >= threshold:
                thick_parts.append(member)
            else:
                thin_parts.append(member)

        # Left Column: The Legend and Stats
        with left_col:
            st.markdown("### Structural Material Grades")
            st.write(f"The 3D viewer highlights members based on their physical thickness (Threshold: **{threshold} {unit_label}**).")
            
            # A visual legend
            st.markdown(f"🟧 **Thick Members (≥ {threshold} {unit_label})**")
            st.write(f"*Predicted Grade 50 Steel* — Count: {len(thick_parts)}")
            
            st.markdown(f"🟦 **Thin Members (< {threshold} {unit_label})**")
            st.write(f"*Predicted Grade 33 Steel* — Count: {len(thin_parts)}")
            
            if unknown_parts:
                st.markdown("⬜ **Unknown Thickness**")
                st.write(f"*Missing 3D Geometry* — Count: {len(unknown_parts)}")

        # Right Column: The 3D Viewer
        with right_col:
            header_col1, header_col2 = st.columns([3, 1])
            with header_col1:
                st.markdown("### 3D Panel Viewer")
            with header_col2:
                show_edges = st.toggle("Show Part Edges", value=True)
            
            # Initialize the plotter
            plotter = pv.Plotter(window_size=[800, 800])
            
            # Fetch the PyVista meshes (Assuming Find_elements is imported and working)
            panel_meshes = Find_elements.get_3d_meshes(all_elements)

            # Map the meshes and apply the color logic
            for element, mesh in zip(all_elements, panel_meshes):
                if element in thick_parts: 
                    part_color = "orange"
                elif element in thin_parts: 
                    part_color = "lightblue"
                else: 
                    part_color = "lightgrey"
                                
                plotter.add_mesh(
                    mesh,
                    color=part_color,
                    show_edges=show_edges,
                    edge_color="grey" if part_color == "lightgrey" else "black",
                    ambient=0.2,
                )
            
            # Reset camera and render via stpyvista
            plotter.view_isometric()
            stpyvista(plotter, key="thickness_viewer")

        
                # --- MAIN INJECTION LOGIC ---
        if 'current_ifc_path' not in st.session_state or not st.session_state['current_ifc_path']:
            st.warning("⚠️ No IFC file detected. Please go back to the Start page and upload a model.")
        else:
            st.success("✅ Global IFC Model loaded.")
            
            if st.button("Inject Steel Materials", type="primary"):
                with st.spinner("Calculating 3D geometry and injecting materials... This may take a minute for large buildings."):
                    try:
                        # 1. Load the model
                        ifc_file = ifcopenshell.open(st.session_state['current_ifc_path'])
                        
                        # --- NEW FIX: GRAB THE EXISTING OWNER HISTORY ---
                        # IFC2X3 requires an OwnerHistory for all new relationships. 
                        # We will just borrow the first one found in the file.
                        histories = ifc_file.by_type("IfcOwnerHistory")
                        owner_history = histories[0] if histories else None
                        # ------------------------------------------------

                        # Determine Units and Threshold
                        is_imperial = detect_imperial_units(ifc_file)
                        if is_imperial:
                            THRESHOLD = 0.045
                            unit_label = "inches"
                        else:
                            THRESHOLD = 1.143
                            unit_label = "mm"
                        
                        st.info(f"Units detected: **{unit_label}**. Using Threshold: **{THRESHOLD}**")

                        # Create the two Material entities
                        grade_50_mat = ifc_file.createIfcMaterial("Steel - Grade 50")
                        grade_33_mat = ifc_file.createIfcMaterial("Steel - Grade 33")

                        # Find all physical elements
                        members = ifc_file.by_type("IfcElement")
                        
                        grade_50_list = []
                        grade_33_list = []
                        unknown_list = []

                        # Sort members based on geometric thickness
                        for member in members:
                            if member.is_a("IfcElementAssembly") or member.is_a("IfcVirtualElement"):
                                continue
                                
                            thickness = get_thickness(member)
                            
                            if thickness is None:
                                unknown_list.append(member)
                            elif thickness >= THRESHOLD:
                                grade_50_list.append(member)
                            else:
                                grade_33_list.append(member)

                        # Link Grade 50 (Thick Parts)
                        if grade_50_list:
                            ifc_file.createIfcRelAssociatesMaterial(
                                GlobalId=ifcopenshell.guid.new(),
                                OwnerHistory=owner_history, # <-- APPLIED HERE
                                Name="Grade50_Link",
                                RelatedObjects=grade_50_list,
                                RelatingMaterial=grade_50_mat
                            )

                        # Link Grade 33 (Thin Parts)
                        if grade_33_list:
                            ifc_file.createIfcRelAssociatesMaterial(
                                GlobalId=ifcopenshell.guid.new(),
                                OwnerHistory=owner_history, # <-- APPLIED HERE
                                Name="Grade33_Link",
                                RelatedObjects=grade_33_list,
                                RelatingMaterial=grade_33_mat
                            )
        # Write to a temporary file
                        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix="_Materials.ifc")
                        ifc_file.write(temp_output.name)
                        st.session_state['injected_ifc_path'] = temp_output.name
                        
                        # --- NEW: USE ORIGINAL FILENAME FOR DOWNLOAD ---
                        base_name = "Panel" # Fallback just in case
                        
                        # Grab the original filename saved in Start.py (e.g., "E2-26.ifc")
                        if 'original_ifc_name' in st.session_state:
                            original_name = st.session_state['original_ifc_name']
                            # Strip off the ".ifc" extension so we don't get "E2-26.ifc_injected.ifc"
                            if original_name.lower().endswith('.ifc'):
                                base_name = original_name[:-4]
                            else:
                                base_name = original_name
                        
                        st.session_state['injected_panel_name'] = base_name
                        
                        # --------------------------------------------
                        
                        # DISPLAY STATS
                        st.success("Materials successfully classified and injected!")
                        col1, col2, col3 = st.columns(3)
                        col1.metric(f"🟧 Grade 50 (≥ {THRESHOLD}{unit_label})", len(grade_50_list))
                        col2.metric(f"🟦 Grade 33 (< {THRESHOLD}{unit_label})", len(grade_33_list))
                        col3.metric("⬜ Unknown / Skipped", len(unknown_list), help="Virtual elements or missing geometry.")

                    except Exception as e:
                        st.error(f"An error occurred during injection: {e}")

            # --- DOWNLOAD BUTTON ---
            if 'injected_ifc_path' in st.session_state and os.path.exists(st.session_state['injected_ifc_path']):
                st.markdown("---")
                
                # Retrieve the dynamically extracted panel name
                panel_name = st.session_state.get('injected_panel_name', 'Panel')
                download_filename = f"{panel_name}_injected.ifc"
                
                with open(st.session_state['injected_ifc_path'], "rb") as file:
                    st.download_button(
                        label=f"Download {download_filename}",
                        data=file,
                        file_name=download_filename,
                        mime="application/octet-stream"
                    )
    except Exception as e:
        st.error(f"Error analyzing IFC data: {e}")

        