"""
Description: 
    This script runs the DfMA tool through streamlit (Web Deployment Version)
    Extracts isolated IfcElementAssembly panels from massive building files.
    *UPDATED: Fixes @st.cache_data cache-key freezing across different IFC uploads
    and refreshes stPyVista keys dynamically.*

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
import vtk

# --- DYNAMIC PATH RESOLUTION (FOR NESTED PAGES) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
images_dir = os.path.join(current_dir, "..", "..", "Images")

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
    try:
        patched_model = ifcpatch.execute({
            "file": model,
            "recipe": "ConvertLengthUnit",
            "arguments": ["METER"] 
        })
        return patched_model if patched_model else model
    except Exception:
        return model


def is_valid_structural_member(entity):
    """
    Returns True only for physical 3D framing members (IfcBeam, IfcMember, 
    IfcColumn, IfcPlate, or 3D IfcBuildingElementPart) and excludes 
    non-structural proxies like FASTENER ('RS_PATTERN2') and SERVICEHOLELINE.
    """
    if entity.is_a("IfcElementAssembly"):
        return False

    if entity.is_a("IfcBuildingElementProxy"):
        obj_type = (getattr(entity, "ObjectType", "") or "").upper()
        name = (getattr(entity, "Name", "") or "").upper()
        if obj_type in ("FASTENER", "SERVICEHOLELINE") or "PATTERN" in name:
            return False

    return getattr(entity, "Representation", None) is not None


def get_assembly_parts(entity, visited=None):
    """
    Recursively traverses the native IfcRelAggregates (IsDecomposedBy) tree:
    Works for both 1-level (624McRobert) and 2-level (IslandBreez2) assemblies.
    """
    if visited is None:
        visited = set()
    if entity.id() in visited:
        return []
    visited.add(entity.id())

    parts = []
    if is_valid_structural_member(entity):
        parts.append(entity)

    if hasattr(entity, "IsDecomposedBy"):
        for rel in entity.IsDecomposedBy:
            for child in rel.RelatedObjects:
                parts.extend(get_assembly_parts(child, visited))

    return parts


# 🛠️ FIX: Pass `file_path` WITHOUT a leading underscore so Streamlit hashes it!
# When you upload a new IFC file, `file_path` changes and forces a fresh Ghost Building calculation.
@st.cache_data(show_spinner="Calculating Ghost Building Layout. This may take a few moments...")
def get_all_panel_bounds(file_path, _model, _panel_names_dict): 
    """Calculates the global bounding box for every panel to create the Ghost Building."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    bounds_dict = {}
    for name, panel in _panel_names_dict.items():
        parts = get_assembly_parts(panel)
                
        min_pt = [float('inf'), float('inf'), float('inf')]
        max_pt = [float('-inf'), float('-inf'), float('-inf')]
        
        valid_geometry = False
        for part in parts:
            try:
                shape = ifcopenshell.geom.create_shape(settings, part)
                verts = np.array(shape.geometry.verts).reshape((-1, 3))
                if verts.size > 0:
                    min_pt = np.minimum(min_pt, verts.min(axis=0))
                    max_pt = np.maximum(max_pt, verts.max(axis=0))
                    valid_geometry = True
            except Exception:
                pass
                
        if valid_geometry:
            bounds_dict[name] = (
                float(min_pt[0]), float(max_pt[0]),
                float(min_pt[1]), float(max_pt[1]),
                float(min_pt[2]), float(max_pt[2])
            )
            
    return bounds_dict


def extract_panel_to_ifc_string(original_model, panel, panel_members):
    """
    Creates a clean, self-contained IFC file for the selected panel.
    """
    new_ifc = ifcopenshell.file(schema=original_model.schema)
    
    # 1. Copy Spatial Context and Aggregation Tree (Project -> Site -> Building -> Storeys)
    for context_class in ["IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey"]:
        for entity in original_model.by_type(context_class):
            new_ifc.add(entity)
            if hasattr(entity, "IsDecomposedBy"):
                for rel in entity.IsDecomposedBy:
                    new_ifc.add(rel)

    # 2. Link the panel to its specific IfcBuildingStorey
    owner_histories = new_ifc.by_type("IfcOwnerHistory")
    oh = owner_histories[0] if owner_histories else None
    new_panel = new_ifc.add(panel)

    for rel in original_model.by_type("IfcRelContainedInSpatialStructure"):
        if panel in rel.RelatedElements:
            new_storey = new_ifc.add(rel.RelatingStructure)
            new_ifc.create_entity(
                "IfcRelContainedInSpatialStructure",
                ifcopenshell.guid.new(),
                oh,
                rel.Name,
                rel.Description,
                [new_panel],
                new_storey
            )

    # 3. Recursively copy all native IfcRelAggregates levels under this panel
    def copy_decomposition_recursive(entity, visited=None):
        if visited is None:
            visited = set()
        if entity.id() in visited:
            return
        visited.add(entity.id())
        if hasattr(entity, "IsDecomposedBy"):
            for rel in entity.IsDecomposedBy:
                new_ifc.add(rel)
                for child in rel.RelatedObjects:
                    copy_decomposition_recursive(child, visited)

    copy_decomposition_recursive(panel)

    # 4. Copy openings, materials, and property sets scoped strictly to this panel's members
    for member in panel_members:
        new_m = new_ifc.add(member)

        if hasattr(member, "HasOpenings"):
            for void_rel in member.HasOpenings:
                new_ifc.add(void_rel)

        if hasattr(member, "HasAssociations"):
            for assoc in member.HasAssociations:
                if assoc.is_a("IfcRelAssociatesMaterial"):
                    new_mat = new_ifc.add(assoc.RelatingMaterial)
                    new_ifc.create_entity(
                        "IfcRelAssociatesMaterial",
                        ifcopenshell.guid.new(),
                        oh,
                        assoc.Name,
                        assoc.Description,
                        [new_m],
                        new_mat
                    )

        if hasattr(member, "IsDefinedBy"):
            for def_rel in member.IsDefinedBy:
                if def_rel.is_a("IfcRelDefinesByProperties"):
                    pdef = def_rel.RelatingPropertyDefinition
                    if getattr(pdef, "Name", "") == "Pset_NRC_RPanelGeometricMembership":
                        continue
                    new_pdef = new_ifc.add(pdef)
                    new_ifc.create_entity(
                        "IfcRelDefinesByProperties",
                        ifcopenshell.guid.new(),
                        oh,
                        def_rel.Name,
                        def_rel.Description,
                        [new_m],
                        new_pdef
                    )
# 5. Copy IfcFastener / IfcMechanicalFastener linked to this panel (624McRobert V2)
    member_ids = {m.id() for m in panel_members}
    panel_guid = getattr(panel, "GlobalId", None)
    copied_fasteners = set()

    # 5a. Check IfcRelConnectsElements connected to any stud/track in this panel
    for rel in original_model.by_type("IfcRelConnectsElements"):
        rel_el = rel.RelatingElement
        related_el = rel.RelatedElement
        if not rel_el or not related_el:
            continue
        if rel_el.is_a("IfcFastener") and related_el.id() in member_ids:
            new_f = new_ifc.add(rel_el)
            new_ifc.add(rel)
            copied_fasteners.add(rel_el.id())
        elif related_el.is_a("IfcFastener") and rel_el.id() in member_ids:
            new_f = new_ifc.add(related_el)
            new_ifc.add(rel)
            copied_fasteners.add(related_el.id())

    # 5b. Copy Pset_NRC_FastenerEnrichment for copied fasteners (or fasteners matching AssemblyGlobalId)
    for fast in original_model.by_type("IfcFastener") + original_model.by_type("IfcMechanicalFastener"):
        include_fast = fast.id() in copied_fasteners
        if hasattr(fast, "IsDefinedBy"):
            for def_rel in fast.IsDefinedBy:
                if def_rel.is_a("IfcRelDefinesByProperties"):
                    pdef = def_rel.RelatingPropertyDefinition
                    if pdef.is_a("IfcPropertySet") and getattr(pdef, "Name", "") == "Pset_NRC_FastenerEnrichment":
                        for prop in getattr(pdef, "HasProperties", []):
                            if getattr(prop, "Name", "") == "AssemblyGlobalId" and prop.NominalValue:
                                if prop.NominalValue.wrappedValue == panel_guid:
                                    include_fast = True
        if include_fast:
            new_f = new_ifc.add(fast)
            if hasattr(fast, "IsDefinedBy"):
                for def_rel in fast.IsDefinedBy:
                    if def_rel.is_a("IfcRelDefinesByProperties"):
                        new_pdef = new_ifc.add(def_rel.RelatingPropertyDefinition)
                        new_ifc.create_entity(
                            "IfcRelDefinesByProperties",
                            ifcopenshell.guid.new(),
                            oh,
                            def_rel.Name,
                            def_rel.Description,
                            [new_f],
                            new_pdef
                        )

    return new_ifc.to_string()


# --- UPLOAD & RENDER LOGIC ---
if 'current_ifcbig_path' in st.session_state and os.path.exists(st.session_state['current_ifcbig_path']):
    current_file_path = st.session_state['current_ifcbig_path']
    file_tag = os.path.basename(current_file_path)
    st.success("Big IFC Loaded Successfully and Patched to Metric!")
    
    if st.button("Upload Different Big IFC"):
        try:
            os.remove(current_file_path) 
        except Exception: 
            pass
        del st.session_state['current_ifcbig_path']
        # 🛠️ Clear cached Ghost Building bounds, IFC model, and extracted progress
        st.session_state['extracted_panels'] = []
        load_ifc.clear()
        get_all_panel_bounds.clear()
        st.rerun()  

    try:
        ifc_model = load_ifc(current_file_path)
        
        # --- 3. EXTRACT PANELS ---
        all_panels = ifc_model.by_type("IfcElementAssembly")
        panel_dict = {panel.Name: panel for panel in all_panels if panel.Name}
        
        if not panel_dict:
            st.warning("No 'IfcElementAssembly' groupings found in this file.")
        else:
            # --- 4. STREAMLIT UI ---
            st.sidebar.markdown("### Panel Selection")
            selected_panel_name = st.sidebar.selectbox(
                "Select a panel to inspect:", 
                options=list(panel_dict.keys())
            )

            active_panel = panel_dict[selected_panel_name]

            # --- 5. EXTRACTION ENGINE ---
            panel_members = get_assembly_parts(active_panel)

            # Pre-calculate data for UX (passing current_file_path so cache updates per file!)
            isolated_ifc_data = extract_panel_to_ifc_string(ifc_model, active_panel, panel_members)
            panel_bounds = get_all_panel_bounds(current_file_path, ifc_model, panel_dict)

            # ==========================================
            # 🛠️ 5.5 GENERATE COMBINED MESH FOR VIEWER & STL
            # ==========================================
            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)
            
            combined_mesh = pv.PolyData()
            thickness_m = 1.37 / 1000.0  # 1.37 mm fallback for open 2D sheet models
            
            for part in panel_members:
                try:
                    shape = ifcopenshell.geom.create_shape(settings, part)
                    verts = shape.geometry.verts
                    faces = shape.geometry.faces
                    if not verts or not faces:
                        continue

                    vertices = np.array(verts, dtype=np.float32).reshape((-1, 3))
                    faces_raw = np.array(faces, dtype=np.int32).reshape((-1, 3))
                    padding = np.full((faces_raw.shape[0], 1), 3, dtype=np.int32) 
                    faces_pv = np.hstack((padding, faces_raw)).flatten()
                    
                    mesh = pv.PolyData(vertices, faces_pv).clean()
                    
                    if mesh.n_open_edges > 0:
                        mesh.compute_normals(
                            cell_normals=False, 
                            point_normals=True, 
                            consistent_normals=True, 
                            inplace=True
                        )
                        
                        extruder = vtk.vtkLinearExtrusionFilter()
                        extruder.SetInputData(mesh)
                        extruder.SetExtrusionTypeToNormalExtrusion()
                        extruder.SetScaleFactor(thickness_m)
                        extruder.CappingOn()
                        extruder.Update()
                        
                        mesh = pv.wrap(extruder.GetOutput()).triangulate().clean()
                    
                    mesh.compute_normals(
                        consistent_normals=True, 
                        auto_orient_normals=True, 
                        inplace=True
                    )

                    combined_mesh = combined_mesh.merge(mesh) if combined_mesh.n_points > 0 else mesh
                except Exception: 
                    pass

            # PROCESS FOR PHYSICS SIMULATION (Center only)
            stl_data = None
            if combined_mesh.n_points > 0:
                sim_mesh = combined_mesh.copy()
                center_pt = sim_mesh.center
                sim_mesh.translate([-center_pt[0], -center_pt[1], -center_pt[2]], inplace=True)

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
                
                progress = len(st.session_state['extracted_panels'])
                total = len(panel_dict)
                st.progress(min(progress / max(total, 1), 1.0), text=f"Extraction Progress: {progress}/{total} Panels")
                
                def mark_extracted(panel_id):
                    if panel_id not in st.session_state['extracted_panels']:
                        st.session_state['extracted_panels'].append(panel_id)

                st.markdown("#### Exports")
                
                st.download_button(
                    label=f"📦 Download {selected_panel_name}.ifc (Metric)",
                    data=isolated_ifc_data,
                    file_name=f"{selected_panel_name}.ifc",
                    mime="application/octet-stream",
                    on_click=mark_extracted,
                    args=(selected_panel_name,) 
                )

                if stl_data:
                    st.download_button(
                        label="🤖 Download STL for Simulation (Centered)",
                        data=stl_data,
                        file_name=f"{selected_panel_name}_Sim.stl",
                        mime="application/octet-stream",
                        help="Exports a centered, metric (meters) STL perfect for Gazebo, MuJoCo, or Isaac Sim."
                    )

            with right_col:
                st.markdown("### Isolated Panel View")
                plotter_iso = pv.Plotter(window_size=[800, 800])
                
                if combined_mesh.n_points > 0:
                    plotter_iso.add_mesh(combined_mesh, color="lightblue", show_edges=True)

                plotter_iso.view_isometric()
                backend_engine = "panel" if platform.system() == "Windows" else "trame"
                stpyvista(
                    plotter_iso,
                    key=f"isolated_viewer_{file_tag}_{selected_panel_name}",
                    backend=backend_engine
                )

            st.markdown("---")
            
            # ==========================================
            # BOTTOM ROW: MACRO GHOST BUILDING
            # ==========================================
            st.markdown("### Whole Building Context")
            st.info("Macro View: Rotate the building below to see where your active panel (blue) fits into the overall structure. Extracted panels are marked in green.")
            
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
            stpyvista(
                plotter_macro,
                key=f"macro_viewer_{file_tag}_{selected_panel_name}_{len(st.session_state['extracted_panels'])}",
                backend=backend_engine
            )

    except Exception as e:
        st.error(f"Error loading IFC file: {e}")

else:
    # --- IF NO FILE IS UPLOADED YET ---
    ifcbigfile = st.file_uploader("Drop a Big IFC file here", type=["ifc"]) 

    if ifcbigfile is not None:
        st.info("Saving, Patching, and processing Geometry... Please wait.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp_file:
            tmp_file.write(ifcbigfile.getbuffer())
            st.session_state['current_ifcbig_path'] = tmp_file.name
        st.session_state['extracted_panels'] = []
        st.rerun()