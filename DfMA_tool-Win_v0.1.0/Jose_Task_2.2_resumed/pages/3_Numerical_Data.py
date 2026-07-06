import streamlit as st
import pandas as pd
import os
import sys
import json
import UI_Helpers
from rdflib import Graph 

# --- PATH HACK FOR PARENT FOLDER IMPORTS ---
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import Find_elements
import Constraints

# --- PAGE SETUP ---
st.set_page_config(page_title="Numerical Data", layout="wide")

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

st.set_page_config(
    layout="wide",
    page_title="Numerical Data",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.title("Raw Panel Data")
st.write("Extracting and analyzing spatial coordinates and dimensions from the IFC file.")

#Get the Design Parameters:

params = st.session_state["design_params"]

#Defaults for rules, avoid crash if params is not loaded.
default_max_length = params["max_length"]
default_max_height = params["max_length"]
default_hole_tol = params["hole_tol"]
default_track_cont_tol = params["track_cont_tol"]
default_track_hole_tol = params["track_hole_tol"]
default_max_weight = params["max_weight"]

# Defaults for the Hole Sizer (in millimeters)
default_allowed_holes_mm = params["allowed_holes_mm"]
default_hole_size_tol_mm = params ["hole_size_tol_mm"]
default_part_max_length_mm = params["part_max_length_mm"]


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
hole_border_clearance_mm = params["hole_border_clearance_mm"]

#Pinned[] has the pinned rules from page#2.
pinned = st.session_state["pinned_rules"]

# --- 4. THE GATEWAY CHECK ---
if 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path']):
    ifcfile_path = st.session_state['current_ifc_path']
    st.info("Scanning for physical parts...")

# ==========================================
# 1. THE BODY: IFC GEOMETRY DATA
# ==========================================
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


        """
        Table Display, each tab has a different table tracking different rules numerically. 
        """
        
        tab1, tab2, tab3, tab4 = st.tabs(["Spatial Coordinates and Sizes", "Identified Holes and Alignments", "Gaps and Depth", "Ontology"])


        with tab1:
            # 1. The Coordinate Table
            st.write("### Spatial Coordinates")
            coords = Find_elements.get_stud_coordinates(all_elements)
            st.dataframe(coords, use_container_width=True)

            # ==========================================
            # 3. The Individual Part Dimension Table
            # ==========================================
            st.markdown("---")
            st.write("### Extracted Part Dimensions (Robotic Handling)")
            
            # Pull parameters from the cloud
            params = st.session_state.get("design_params", {})
            
            # Run the updated rule
            part_size_report = Constraints.check_part_max_dimensions(
                all_elements, 
                max_length_mm=params.get("part_max_length_mm", 1000.0),
                max_height_mm=params.get("part_max_height_mm", 1000.0),
                max_depth_mm=params.get("part_max_depth_mm", 300.0)
            )
            
            if "part_details" in part_size_report and len(part_size_report["part_details"]) > 0:
                # Convert list of dictionaries to a Pandas DataFrame
                df_parts = pd.DataFrame(part_size_report["part_details"])
                st.dataframe(df_parts, use_container_width=True)
                
                # Print a quick summary message above the table
                if part_size_report["passed"]:
                    st.success(part_size_report["message"])
                else:
                    st.error(part_size_report["message"])
            else:
                st.info("No physical dimensions could be extracted for these parts.")

            # ==========================================
            # 9. Assembly Payload & Weight Table
            # ==========================================
            st.markdown("---")
            st.write("### Total Assembly Payload Breakdown")
            
            payload_report = Constraints.check_total_assembly_payload(
                all_elements, 
                max_payload_kg=params.get("total_assembly_payload_limit_kg", 100.0)
            )
            
            if "payload_details" in payload_report and len(payload_report["payload_details"]) > 0:
                df_payload = pd.DataFrame(payload_report["payload_details"])
                st.dataframe(df_payload, use_container_width=True)
                
                # Print total summary below the table
                if payload_report["passed"]: 
                    st.success(payload_report["message"])
                else: 
                    st.error(payload_report["message"])
            else:
                st.info("No weight or geometry data could be extracted to calculate panel payload.")
                
        with tab2:

            # 2. The Hole Dimension Table
            st.write("### Extracted Hole Dimensions")
            
            # --- CLOUD SAFE MEMORY READ ---
            # Pull the allowed sizes from session memory so Pass/Fail is accurate
            # Convert to meters for the engine
            try:
                allowed_sizes_list_m = [float(x.strip()) / 1000.0 for x in allowed_holes_mm.split(",")]
            except ValueError:
                allowed_sizes_list_m = [0.034] 
                
            hole_size_tol_m = hole_size_tol / 1000.0

            hole_size_tol_m = hole_size_tol / 1000.0

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

            # ==========================================
            # 10. Hole Edge Clearance Table
            # ==========================================
            st.markdown("---")
            st.write("### Punched Hole Edge Clearances")
            
            clearance_report = Constraints.check_hole_border_clearance(
                all_elements, 
                min_clearance_mm=params.get("hole_border_clearance_mm", 20.0)
            )
            
            if "clearance_details" in clearance_report and len(clearance_report["clearance_details"]) > 0:
                df_clearance = pd.DataFrame(clearance_report["clearance_details"])
                st.dataframe(df_clearance, use_container_width=True)
                
                if clearance_report["passed"]: 
                    st.success(clearance_report["message"])
                else: 
                    st.error(clearance_report["message"])
            else:
                st.info("No service holes were detected in the model.")
            
            # ==========================================
            # 6. The Track Continuity Table
            # ==========================================
            st.markdown("---")
            st.write("### Top & Bottom Track Continuity")
            
            # Run the updated rule using parameters from the cloud
            track_rule_report = Constraints.check_track_continuity(
                all_elements, 
                tolerance_m=params.get("track_cont_tol", 0.020)
            )
            
            if "track_details" in track_rule_report and len(track_rule_report["track_details"]) > 0:
                df_tracks = pd.DataFrame(track_rule_report["track_details"])
                st.dataframe(df_tracks, use_container_width=True)
                
                if not track_rule_report.get("has_tracks", True):
                    st.warning(f"⚠️ {track_rule_report['message']}")
                elif track_rule_report["passed"]: 
                    st.success(track_rule_report["message"])
                else: 
                    st.error(track_rule_report["message"])
            else:
                st.info("No top or bottom tracks were detected by the continuity scanner.")

            # ==========================================
            # 7. Center of Gravity Details
            # ==========================================
            st.markdown("---")
            st.write("### Center of Gravity & Balance")
            
            cog_report = Constraints.check_center_of_gravity(
                all_elements, 
                tolerance_mm=params.get("CoG_radius_tolerance_mm", 250.0)
            )
            
            if "cog_details" in cog_report and len(cog_report["cog_details"]) > 0:
                df_cog = pd.DataFrame(cog_report["cog_details"])
                st.dataframe(df_cog, use_container_width=True)
                
                if cog_report["passed"]: st.success(cog_report["message"])
                else: st.error(cog_report["message"])

            # ==========================================
            # 8. Slanted Beam Pitch Angles
            # ==========================================
            st.markdown("---")
            st.write("### Slanted Beam Angles (Roof & Brace Pitch)")
            
            slanted_report = Constraints.check_slanted_beam_angle(
                all_elements, 
                max_angle_degrees=params.get("slanted_beam_angle", 45.0)
            )
            
            if "angle_details" in slanted_report and len(slanted_report["angle_details"]) > 0:
                df_angles = pd.DataFrame(slanted_report["angle_details"])
                st.dataframe(df_angles, use_container_width=True)
                
                if slanted_report["passed"]: st.success(slanted_report["message"])
                else: st.error(slanted_report["message"])
            else:
                st.info("No slanted beams (angles between 5° and 85°) were detected in this panel.")
        
    except Exception as e:
        st.error(f"Something went wrong extracting the data: {e}")

    with tab3:
        # ==========================================
        # 4. The Stud Spacing Table
        # ==========================================
        st.markdown("---")
        st.write("### Stud Spacing Distances")
        
        stud_spacing_report = Constraints.check_stud_spacing(
        all_elements, 
        target_spacings_mms=params.get("stud_spacing_mm", "600, 100"), # <-- FIXED (Plural)
        tolerance_mm=params.get("stud_tol_mm", 10.0)
        )
        
        if "spacing_details" in stud_spacing_report and len(stud_spacing_report["spacing_details"]) > 0:
            df_spacing = pd.DataFrame(stud_spacing_report["spacing_details"])
            st.dataframe(df_spacing, use_container_width=True)
            
            if stud_spacing_report["passed"]: st.success(stud_spacing_report["message"])
            else: st.error(stud_spacing_report["message"])
        else:
            st.info("Not enough studs found to measure gap spacing.")

        # ==========================================
        # 5. The Joist Uniformity Table
        # ==========================================
        st.markdown("---")
        st.write("### Horizontal Track / Joist Depths")
        
        joist_report = Constraints.check_joist_uniformity(
            all_elements, 
            tolerance_mm=params.get("joist_depth_tolerance_mm", 100)
        )
        
        if "joist_details" in joist_report and len(joist_report["joist_details"]) > 0:
            df_joists = pd.DataFrame(joist_report["joist_details"])
            st.dataframe(df_joists, use_container_width=True)
            
            if joist_report["passed"]: st.success(joist_report["message"])
            else: st.error(joist_report["message"])
        else:
            st.info("No horizontal tracks found to evaluate for depth uniformity.")

else:
    st.warning("⚠️ Please upload an IFC file on the Start page first!")

# ==========================================
# 2. ONTOLOGY SEMANTIC DATA
# ==========================================

# Check if the ontology file is in web memory (loaded from Start.py)
if 'current_ontology_path' in st.session_state and os.path.exists(st.session_state['current_ontology_path']):
    ontology_path = st.session_state['current_ontology_path']
    
    try:

        # Load the Graph
        bim_graph = Graph()
        file_extension = ontology_path.split('.')[-1]
        parse_format = "json-ld" if file_extension == "jsonld" else "turtle" if file_extension == "ttl" else "xml"
        bim_graph.parse(ontology_path, format=parse_format)
        
        # Extract Data using a SPARQL Query (Filtering for your lab's specific data)
        query = """
            SELECT ?subject ?predicate ?object 
            WHERE {
                ?subject ?predicate ?object .
                FILTER (STRSTARTS(str(?subject), "http://www.semanticweb.org/mmari/ontologies/2026/0/BIM_Ontology#"))
            }
        """
        results = bim_graph.query(query)
        
        # Clean the Data for the Table (Stripping the long web URLs)
        table_data = []
        for row in results:
            subj = str(row.subject).split('#')[-1]
            pred = str(row.predicate).split('#')[-1]
            
            # Objects can be URLs (other nodes) or literal values (like the number 90.0)
            if '#' in str(row.object):
                obj = str(row.object).split('#')[-1]
            else:
                obj = str(row.object) # It's a literal value
                
            table_data.append({
                "Subject": subj, 
                "Relationship": pred, 
                "Value": obj
            })
        
        with tab4:
            st.markdown("---")
            st.markdown("Semantic Knowledge Graph Data")
            # Display as an interactive Pandas DataFrame
            if table_data:
                df_ontology = pd.DataFrame(table_data)
                
                st.info(f"Successfully extracted **{len(df_ontology)}** semantic rules and relationships.")
                
                # Add a search bar so you can look up specific Panel GlobalIds!
                search_term = st.text_input("🔍 Search for a specific Panel ID, Rule, or Connection:")
                
                if search_term:
                    # Filter the dataframe based on the search term
                    filtered_df = df_ontology[df_ontology.apply(lambda row: row.astype(str).str.contains(search_term, case=False).any(), axis=1)]
                    st.dataframe(filtered_df, use_container_width=True)
                else:
                    # Show full dataframe
                    st.dataframe(df_ontology, use_container_width=True)
                    
            else:
                st.warning("Graph loaded, but no custom BIM rules were found.")

    except Exception as e:
        st.error(f"Error parsing Ontology for data table: {e}")
else:
    st.info("No Ontology file loaded. Upload one on the Start page to view the semantic data.")