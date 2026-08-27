import streamlit as st
import os
import sys
import pandas as pd
import pyvista as pv
import numpy as np
import io
import zipfile
import tempfile
from PIL import Image
import platform

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
images_dir = os.path.join(current_dir, "..", "..", "Images")
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import UI_Helpers
import Find_elements
import engine

from stpyvista import stpyvista

# --- PAGE SETUP ---
logo_path = os.path.join(images_dir, "smart_logo.jpeg")
try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = "🏗️"

st.set_page_config(
    layout="wide",
    page_title="Manufacturing Instructions",
    page_icon=logo_img
)

lablogo_path = os.path.join(images_dir, "horizontal_smart.png")
try:
    UI_Helpers.add_floating_lab_logo(lablogo_path, url="https://rafiqahmads.com/")
except Exception:
    pass

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] span { font-size: 30px !important; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("CNC & Robotic Manufacturing Instructions")
st.write("Extracting local drill coordinates for individual LGS members based on Semantic Ontology Connections and Mesh Analysis.")

# ============================================================
# EXTRACTION & NORMALIZATION HELPER FUNCTIONS
# ============================================================

def extract_ontology_connections(ontology_path):
    connections = []
    if not ontology_path or not os.path.exists(ontology_path):
        return connections
    try:
        from rdflib import Graph, RDF
        graph = Graph()
        graph.parse(ontology_path, format="turtle")
        all_classes = set(graph.objects(None, RDF.type))
        connection_classes = [cls for cls in all_classes if "Connection" in str(cls) or "Angled" in str(cls) or "Crossing" in str(cls) or "Lateral" in str(cls)]
        
        connection_number = 1
        for cls in connection_classes:
            for instance in graph.subjects(RDF.type, cls):
                instance_string = str(instance)
                instance_name = instance_string.split("#")[-1] if "#" in instance_string else instance_string.split("/")[-1]
                
                x, y, z = 0.0, 0.0, 0.0
                
                for predicate, obj in graph.predicate_objects(instance):
                    predicate_string = str(predicate)
                    predicate_name = predicate_string.split("#")[-1] if "#" in predicate_string else predicate_string.split("/")[-1]
                    try:
                        value = float(obj)
                    except (ValueError, TypeError):
                        continue
                        
                    if predicate_name in ["hasContactX", "hasX"]: x = value
                    elif predicate_name in ["hasContactY", "hasY"]: y = value
                    elif predicate_name in ["hasContactZ", "hasZ"]: z = value

                connections.append({
                    "ID": f"O-{connection_number:03d}",
                    "Ontology Instance": instance_name,
                    "X": float(x),
                    "Y": float(y),
                    "Z": float(z),
                })
                connection_number += 1
    except Exception as error:
        st.error(f"Error reading ontology: {error}")
    return connections

def get_ifc_panel_origin(panel_meshes):
    valid_bounds = [mesh.bounds for mesh in panel_meshes if mesh is not None and mesh.n_points > 0]
    if not valid_bounds: return (0.0, 0.0, 0.0)
    return (min(b[0] for b in valid_bounds), min(b[2] for b in valid_bounds), min(b[4] for b in valid_bounds))

def get_ontology_origin(ontology_connections):
    if not ontology_connections: return (0.0, 0.0, 0.0)
    return (min(c["X"] for c in ontology_connections), min(c["Y"] for c in ontology_connections), min(c["Z"] for c in ontology_connections))

def normalize_ontology_connections(moveox, moveoy, moveoz, connections, origin):
    ox, oy, oz = origin
    ox = ox + (moveox * 0.1)
    oy = oy + (moveoy * 0.1)
    oz = oz + (moveoz * 0.1)
    
    normalized = []
    for connection in connections:
        c = connection.copy()
        c["X"] = c["X"] - ox
        c["Y"] = c["Y"] - oy
        c["Z"] = c["Z"] - oz
        normalized.append(c)
    return normalized

# ============================================================
# CUSTOM MESH HOLE SCANNER
# ============================================================
def find_custom_holes_in_mesh(mesh):
    """
    Scans a PyVista mesh for sharp topological edges, groups them, 
    and returns the local (X, Y, Z) center points of the custom service holes.
    """
    holes_coords = []
    try:
        edges = mesh.extract_feature_edges(feature_angle=45)
        if edges.n_points == 0: return holes_coords
            
        pts = np.array(edges.points)
        z_coords = pts[:, 2]
        
        stud_min_z, stud_max_z = z_coords.min(), z_coords.max()
        buffer = 0.05 
        valid_mask = (z_coords > stud_min_z + buffer) & (z_coords < stud_max_z - buffer)
        valid_pts = pts[valid_mask]
        
        if len(valid_pts) == 0: return holes_coords
            
        sorted_indices = np.argsort(valid_pts[:, 2])
        valid_pts = valid_pts[sorted_indices]
        current_cluster = [valid_pts[0]]
        
        for pt in valid_pts[1:]:
            if pt[2] - current_cluster[-1][2] < 0.10: 
                current_cluster.append(pt)
            else:
                holes_coords.append(np.mean(current_cluster, axis=0))
                current_cluster = [pt] 
        
        if current_cluster:
            holes_coords.append(np.mean(current_cluster, axis=0))
            
    except Exception:
        pass
        
    return holes_coords

# ============================================================
# MAIN APPLICATION
# ============================================================

has_ifc = 'current_ifc_path' in st.session_state and os.path.exists(st.session_state['current_ifc_path'])
has_ont = 'current_ontology_path' in st.session_state and os.path.exists(st.session_state['current_ontology_path'])

if has_ifc and has_ont:
    ifcfile_path = st.session_state['current_ifc_path']
    ontology_path = st.session_state['current_ontology_path']
    
    st.markdown("### Ontology Alignment Calibration")
    st.info("Input the exact offset parameters you used in the Panel Connections page to ensure the ontology maps perfectly to the IFC mesh bounds.")
    
    col1, col2, col3 = st.columns(3)
    with col1: moveox = st.number_input("Move Ontology ox (mm)", min_value=-100.0, max_value=100.0, value=-0.25, step=0.5)
    with col2: moveoy = st.number_input("Move Ontology oy (mm)", min_value=-100.0, max_value=100.0, value=0.0, step=0.5)
    with col3: moveoz = st.number_input("Move Ontology oz (mm)", min_value=-100.0, max_value=100.0, value=-0.25, step=0.5)
    
    with st.spinner("Aligning coordinates and mapping local drill locations..."):
        try:
            # 1. LOAD IFC GEOMETRY & ONTOLOGY
            all_elements = Find_elements.get_elements(ifcfile_path)
            panel_meshes = Find_elements.get_3d_meshes(all_elements)
            raw_ontology_connections = extract_ontology_connections(ontology_path)
            
            # 2. ALIGNMENT TO LOCAL ORIGIN (0,0,0)
            ifc_origin = get_ifc_panel_origin(panel_meshes)
            ontology_origin = get_ontology_origin(raw_ontology_connections)
            
            normalized_ontology = normalize_ontology_connections(moveox, moveoy, moveoz, raw_ontology_connections, ontology_origin)
            
            # 3. CALCULATE LOCAL DRILL COORDINATES ON MEMBERS
            manufacturing_instructions = []
            tol = 0.02 # 20mm surface matching tolerance
            
            for element, raw_mesh in zip(all_elements, panel_meshes):
                if raw_mesh is None or raw_mesh.n_points == 0:
                    continue
                    
                el_name = getattr(element, 'Name', 'Unknown')
                el_id = getattr(element, 'GlobalId', 'UnknownID')
                
                # A. Shift the raw mesh to its own center
                sim_mesh = raw_mesh.copy()
                center_pt = sim_mesh.center
                sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)
                
                # B. Extract Custom Service Holes
                custom_holes = find_custom_holes_in_mesh(sim_mesh)
                for ch in custom_holes:
                    manufacturing_instructions.append({
                        "Member Name": el_name,
                        "Member GlobalId": el_id,
                        "Operation": "Service Hole (Custom)",
                        "Joint ID": "N/A",
                        "Ontology Instance": "N/A",
                        "Local Drill X (m)": round(ch[0], 4),
                        "Local Drill Y (m)": round(ch[1], 4),
                        "Local Drill Z (m)": round(ch[2], 4),
                        "Panel Coordinate X": round(ch[0] + center_pt[0] - ifc_origin[0], 4),
                        "Panel Coordinate Y": round(ch[1] + center_pt[1] - ifc_origin[1], 4),
                        "Panel Coordinate Z": round(ch[2] + center_pt[2] - ifc_origin[2], 4)
                    })
                
                # C. Shift mesh to Panel Origin
                mesh_panel_local = raw_mesh.copy()
                mesh_panel_local.translate((-ifc_origin[0], -ifc_origin[1], -ifc_origin[2]), inplace=True)
                b = mesh_panel_local.bounds
                
                # D. Map Ontology Connections
                for conn in normalized_ontology:
                    cx, cy, cz = conn['X'], conn['Y'], conn['Z']
                    if (b[0]-tol <= cx <= b[1]+tol) and (b[2]-tol <= cy <= b[3]+tol) and (b[4]-tol <= cz <= b[5]+tol):
                        local_x = cx - (center_pt[0] - ifc_origin[0])
                        local_y = cy - (center_pt[1] - ifc_origin[1])
                        local_z = cz - (center_pt[2] - ifc_origin[2])
                        
                        manufacturing_instructions.append({
                            "Member Name": el_name,
                            "Member GlobalId": el_id,
                            "Operation": "Drilling",
                            "Joint ID": conn['ID'],
                            "Ontology Instance": conn['Ontology Instance'],
                            "Local Drill X (m)": round(local_x, 4),
                            "Local Drill Y (m)": round(local_y, 4),
                            "Local Drill Z (m)": round(local_z, 4),
                            "Panel Coordinate X": round(cx, 4),
                            "Panel Coordinate Y": round(cy, 4),
                            "Panel Coordinate Z": round(cz, 4)
                        })

            # ==========================================
            # 4. RENDER DASHBOARD & EXPORTS
            # ==========================================
            if manufacturing_instructions:
                st.success(f"Successfully extracted {len(manufacturing_instructions)} toolpath operations for individual members!")
                df_instructions = pd.DataFrame(manufacturing_instructions)
                
                left_col, right_col = st.columns([1.5, 1])
                
                with left_col:
                    total_members = df_instructions['Member GlobalId'].nunique()
                    total_drills = len(df_instructions[df_instructions["Operation"] == "Drilling"])
                    total_services = len(df_instructions[df_instructions["Operation"] == "Service Hole (Custom)"])
                    
                    st.write(f"### Production Summary")
                    st.write(f"* **Total Members Requiring Work:** {total_members}")
                    st.write(f"* **Total Joint Drill Targets:** {total_drills}")
                    st.write(f"* **Total Service Hole Targets:** {total_services}")
                    
                    st.markdown("---")
                    st.markdown("### CNC Coordinates Table (Local Member Origins)")
                    st.dataframe(df_instructions, use_container_width=True)
                    
                    with st.spinner("Packaging Manufacturing ZIP File..."):
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            csv_data = df_instructions.to_csv(index=False).encode('utf-8')
                            zip_file.writestr("Drill_Coordinates_BOM.csv", csv_data)
                            
                            for element, raw_mesh in zip(all_elements, panel_meshes):
                                if raw_mesh is None or raw_mesh.n_points == 0: continue
                                
                                sim_mesh = raw_mesh.copy()
                                center_pt = sim_mesh.center
                                sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)
                                
                                clean_name = str(element.Name).replace("/", "_").replace("\\", "_") if hasattr(element, 'Name') and element.Name else "Member"
                                clean_id = str(element.GlobalId) if hasattr(element, 'GlobalId') else "UnknownID"
                                file_name = f"STLs/{clean_name}_{clean_id}.stl"
                                
                                with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
                                    sim_mesh.save(tmp.name)
                                    with open(tmp.name, "rb") as f:
                                        zip_file.writestr(file_name, f.read())
                                os.remove(tmp.name)
                                    
                    st.markdown("---")
                    st.markdown("### Export to Fabrication")
                    st.info("Download a complete manufacturing package containing the CSV drill targets and individual centered `.stl` files.")
                    st.download_button(
                        label="Download Manufacturing Package (.ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name="LGS_Manufacturing_Package.zip",
                        mime="application/zip"
                    )

                with right_col:
                    st.markdown("### Individual Member QA Viewer")
                    st.info("Blue = Local Origin (0,0,0). Green = Ontology Drill Targets. Yellow = Custom Service Holes.")
                    
                    valid_members = [(e, m) for e, m in zip(all_elements, panel_meshes) if m is not None and m.n_points > 0]
                    member_options = {f"{getattr(e, 'Name', 'Member')} ({getattr(e, 'GlobalId', 'ID')})": (e, m) for e, m in valid_members}
                    
                    selected_label = st.selectbox("Inspect Member:", list(member_options.keys()))
                    
                    if selected_label:
                        sel_element, sel_mesh_raw = member_options[selected_label]
                        
                        plotter = pv.Plotter(window_size=[600, 600])
                        plotter.background_color = "white"
                        
                        sim_mesh = sel_mesh_raw.copy()
                        center_pt = sim_mesh.center
                        sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)
                        plotter.add_mesh(sim_mesh, color="lightgrey", show_edges=True, edge_color="grey")
                        
                        # --- NEW: ORIGIN MARKER ---
                        origin_marker = pv.Sphere(radius=0.020, center=(0, 0, 0))
                        plotter.add_mesh(origin_marker, color="blue", smooth_shading=True)
                        
                        member_instructions = [inst for inst in manufacturing_instructions if inst["Member GlobalId"] == sel_element.GlobalId]
                        
                        if member_instructions:
                            for inst in member_instructions:
                                lx = inst["Local Drill X (m)"]
                                ly = inst["Local Drill Y (m)"]
                                lz = inst["Local Drill Z (m)"]
                                
                                if inst["Operation"] == "Drilling":
                                    sphere = pv.Sphere(radius=0.015, center=(lx, ly, lz))
                                    plotter.add_mesh(sphere, color="green", smooth_shading=True)
                                elif inst["Operation"] == "Service Hole (Custom)":
                                    sphere = pv.Sphere(radius=0.020, center=(lx, ly, lz))
                                    plotter.add_mesh(sphere, color="yellow", smooth_shading=True)
                        else:
                            st.warning("No drill operations or holes required for this specific member.")
                            
                        plotter.view_isometric()
                        backend_engine = "panel" if platform.system() == "Windows" else "trame"
                        stpyvista(plotter, key=f"viewer_{sel_element.GlobalId}", backend=backend_engine)

            else:
                st.warning("No connections fell within the bounds of the panel members. Try adjusting your Calibration offsets above.")
                
        except Exception as e:
            st.error(f"Error processing manufacturing instructions: {e}")
            
else:
    st.warning("Missing Files! Please ensure both an IFC file and an Ontology file are uploaded on the Start page.")