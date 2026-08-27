import streamlit as st
import os
import sys
import numpy as np
import pandas as pd
import pyvista as pv
import ifcopenshell

from PIL import Image
from stpyvista import stpyvista


# ============================================================
# 1. PATH SETUP
# ============================================================

current_dir = os.path.dirname(os.path.abspath(__file__))

parent_dir = os.path.abspath(
    os.path.join(current_dir, "..")
)

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

images_dir = os.path.abspath(
    os.path.join(current_dir, "..", "..", "Images")
)

import Find_elements
import UI_Helpers


# ============================================================
# 2. PAGE CONFIGURATION
# ============================================================

logo_path = os.path.join(
    images_dir,
    "smart_logo.jpeg"
)

try:
    logo_img = Image.open(logo_path)
except Exception:
    logo_img = "🏗️"

st.set_page_config(
    layout="wide",
    page_title="Panel Connections",
    page_icon=logo_img
)

lablogo_path = os.path.join(
    images_dir,
    "horizontal_smart.png"
)

try:
    UI_Helpers.add_floating_lab_logo(
        lablogo_path,
        url="https://rafiqahmads.com/"
    )
except Exception:
    pass


# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================


def get_element_name(element, fallback):
    """
    Return a useful IFC element name.
    """

    if element is None:
        return fallback

    name = getattr(
        element,
        "Name",
        None
    )

    if name:
        return str(name)

    return fallback


def get_element_guid(element):
    """
    Return IFC GlobalId.
    """

    if element is None:
        return ""

    guid = getattr(
        element,
        "GlobalId",
        None
    )

    if guid:
        return str(guid)

    return ""


# ============================================================
# 4. GEOMETRIC BOUNDING BOX FUNCTIONS
# ============================================================

def get_overlap_center(
    min1,
    max1,
    min2,
    max2,
    buffer
):
    """
    Determine the center of the overlap between two
    one-dimensional bounding boxes.

    Returns None when there is no overlap.
    """

    a_min = min1 - buffer
    a_max = max1 + buffer

    b_min = min2 - buffer
    b_max = max2 + buffer

    overlap_min = max(
        a_min,
        b_min
    )

    overlap_max = min(
        a_max,
        b_max
    )

    if overlap_min <= overlap_max:

        return (
            overlap_min
            +
            overlap_max
        ) / 2.0

    return None

# ============================================================
# NEW: DIMPLE DETECTION ENGINE
# ============================================================

def find_dimples_in_mesh(mesh, joint_bounds):
    """
    Search a member mesh for shallow dimples or creases
    representing fasteners inside a connection zone.
    """
    try:
        # feature_angle=20 catches the gentle slope of a dimple!
        # feature_edges=True forces it to look at surface creases, not just open holes.
        edges = mesh.extract_feature_edges(
            feature_angle=20, 
            feature_edges=True, 
            boundary_edges=True
        )
        
        if edges.n_points == 0:
            return []

        connected = edges.connectivity()
        found = []

        if "RegionId" not in connected.point_data:
            return found

        region_ids = np.unique(connected.point_data["RegionId"])

        for region_id in region_ids:
            loop = connected.threshold([region_id, region_id], scalars="RegionId")
            if loop.n_points == 0:
                continue

            hx, hy, hz = loop.center

            # Check whether the dimple lies inside the specific connection zone
            if not (joint_bounds[0] <= hx <= joint_bounds[1] and
                    joint_bounds[2] <= hy <= joint_bounds[3] and
                    joint_bounds[4] <= hz <= joint_bounds[5]):
                continue

            bounds = loop.bounds
            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]

            max_dim = max(dx, dy, dz)

            # SIZE FILTER: Dimples are small! (1mm to 25mm)
            # This instantly rejects the massive 90-degree corner folds of the C-Studs.
            if not (0.001 < max_dim < 0.025):
                continue

            min_dim = min(dx, dy, dz)

            # Determine the drilling axis based on the shortest dimension of the dimple
            if min_dim == dx:
                hole_direction = (1, 0, 0)
            elif min_dim == dy:
                hole_direction = (0, 1, 0)
            else:
                hole_direction = (0, 0, 1)

            found.append({
                "x": hx,
                "y": hy,
                "z": hz,
                "dir": hole_direction,
                "diam": max_dim,
                "length": 0.04 # Standard 40mm cylinder length for the viewer
            })
            
        return found
        
    except Exception:
        return []


def attach_dimples_to_geometric_connections(geometric_connections, panel_meshes):
    """
    Search the corresponding connection zone for physical dimples.
    """
    for connection in geometric_connections:
        cx = connection["X"]
        cy = connection["Y"]
        cz = connection["Z"]
        sx = connection["Zone X"]
        sy = connection["Zone Y"]
        sz = connection["Zone Z"]

        joint_bounds = [
            cx - sx / 2.0, cx + sx / 2.0,
            cy - sy / 2.0, cy + sy / 2.0,
            cz - sz / 2.0, cz + sz / 2.0
        ]

        raw_holes = []
        for mesh in panel_meshes:
            if mesh is not None and mesh.n_points > 0:
                raw_holes.extend(find_dimples_in_mesh(mesh, joint_bounds))

        # Deduplicate dimples (both front and back faces of the metal might trigger)
        unique_holes = []
        for hole in raw_holes:
            duplicate = False
            for existing in unique_holes:
                distance = ((hole["x"] - existing["x"]) ** 2 +
                            (hole["y"] - existing["y"]) ** 2 +
                            (hole["z"] - existing["z"]) ** 2) ** 0.5
                if distance < 0.005:
                    duplicate = True
                    break
            if not duplicate:
                unique_holes.append(hole)

        connection["Holes"] = unique_holes
        connection["Hole Count"] = len(unique_holes)
        
    return geometric_connections


def get_connection_direction(
    b1,
    b2,
    tol_x,
    tol_y,
    tol_z
):
    """
    Estimate the connection direction from the smallest
    overlap dimension.
    """

    ox = max(
        0.0001,
        min(
            b1[1] + tol_x,
            b2[1] + tol_x
        )
        -
        max(
            b1[0] - tol_x,
            b2[0] - tol_x
        )
    )

    oy = max(
        0.0001,
        min(
            b1[3] + tol_y,
            b2[3] + tol_y
        )
        -
        max(
            b1[2] - tol_y,
            b2[2] - tol_y
        )
    )

    oz = max(
        0.0001,
        min(
            b1[5] + tol_z,
            b2[5] + tol_z
        )
        -
        max(
            b1[4] - tol_z,
            b2[4] - tol_z
        )
    )

    overlaps = [
        ox,
        oy,
        oz
    ]

    smallest = np.argmin(
        overlaps
    )

    if smallest == 0:

        direction = (
            1.0,
            0.0,
            0.0
        )

    elif smallest == 1:

        direction = (
            0.0,
            1.0,
            0.0
        )

    else:

        direction = (
            0.0,
            0.0,
            1.0
        )

    return (
        direction,
        (
            ox,
            oy,
            oz
        )
    )


# ============================================================
# 5. GEOMETRIC CONNECTION EXTRACTION
# ============================================================

def extract_geometric_connections(
    elements,
    panel_meshes,
    tol_x,
    tol_y,
    tol_z
):
    """
    Detect geometric connection candidates using member
    bounding boxes.

    IMPORTANT:

    This function does not attempt to determine whether the
    connection is a bolt, screw, bracket, etc.

    It simply identifies a geometric connection location
    between two different IFC members.
    """

    connections = []

    bounds_list = []

    for mesh in panel_meshes:

        if mesh is None:

            bounds_list.append(None)

            continue

        if mesh.n_points == 0:

            bounds_list.append(None)

            continue

        bounds_list.append(
            mesh.bounds
        )

    connection_number = 1

    for i in range(
        len(bounds_list)
    ):

        b1 = bounds_list[i]

        if b1 is None:
            continue

        for j in range(
            i + 1,
            len(bounds_list)
        ):

            b2 = bounds_list[j]

            if b2 is None:
                continue

            # ------------------------------------------------
            # Calculate overlap
            # ------------------------------------------------

            cx = get_overlap_center(
                b1[0],
                b1[1],
                b2[0],
                b2[1],
                tol_x / 2.0
            )

            cy = get_overlap_center(
                b1[2],
                b1[3],
                b2[2],
                b2[3],
                tol_y / 2.0
            )

            cz = get_overlap_center(
                b1[4],
                b1[5],
                b2[4],
                b2[5],
                tol_z / 2.0
            )

            if (
                cx is None
                or
                cy is None
                or
                cz is None
            ):
                continue

            # ------------------------------------------------
            # IFC element information
            # ------------------------------------------------

            element_1 = (
                elements[i]
                if i < len(elements)
                else None
            )

            element_2 = (
                elements[j]
                if j < len(elements)
                else None
            )

            name_1 = get_element_name(
                element_1,
                f"Member_{i}"
            )

            name_2 = get_element_name(
                element_2,
                f"Member_{j}"
            )

            guid_1 = get_element_guid(
                element_1
            )

            guid_2 = get_element_guid(
                element_2
            )

            # ------------------------------------------------
            # IMPORTANT:
            # Do not allow the same IFC element to connect
            # to itself.
            # ------------------------------------------------

            if guid_1 and guid_2:

                if guid_1 == guid_2:
                    continue

            # ------------------------------------------------
            # Direction
            # ------------------------------------------------

            direction, overlap = (
                get_connection_direction(
                    b1,
                    b2,
                    tol_x,
                    tol_y,
                    tol_z
                )
            )

            # ------------------------------------------------
            # Connection zone
            # ------------------------------------------------

            zone_x = max(
                0.06,
                tol_x * 2.0
            )

            zone_y = max(
                0.06,
                tol_y * 2.0
            )

            zone_z = max(
                0.06,
                tol_z * 2.0
            )

            connections.append(
                {
                    "ID":
                        f"G-{connection_number:03d}",

                    "Source":
                        "Geometry",

                    "Member 1":
                        name_1,

                    "Member 1 GUID":
                        guid_1,

                    "Member 2":
                        name_2,

                    "Member 2 GUID":
                        guid_2,

                    "X":
                        float(cx),

                    "Y":
                        float(cy),

                    "Z":
                        float(cz),

                    "Direction X":
                        direction[0],

                    "Direction Y":
                        direction[1],

                    "Direction Z":
                        direction[2],

                    "Overlap X":
                        overlap[0],

                    "Overlap Y":
                        overlap[1],

                    "Overlap Z":
                        overlap[2],

                    "Zone X":
                        zone_x,

                    "Zone Y":
                        zone_y,

                    "Zone Z":
                        zone_z,
                }
            )

            connection_number += 1

    return connections


# ============================================================
# 6. ONTOLOGY CONNECTION EXTRACTION
# ============================================================

def extract_ontology_connections(
    ontology_path
):
    """
    Extract connections from the TTL ontology.

    The ontology coordinates are assumed to be LOCAL PANEL
    coordinates.

    They are not converted here. Coordinate normalization
    happens later.
    """

    connections = []

    if not ontology_path:
        return connections

    if not os.path.exists(
        ontology_path
    ):
        return connections

    try:

        from rdflib import (
            Graph,
            RDF
        )

        graph = Graph()

        graph.parse(
            ontology_path,
            format="turtle"
        )

        all_classes = set(
            graph.objects(
                None,
                RDF.type
            )
        )

        connection_classes = [
            cls
            for cls in all_classes
            if "Connection" in str(cls)
        ]

        connection_number = 1

        for cls in connection_classes:

            for instance in graph.subjects(
                RDF.type,
                cls
            ):

                instance_string = str(
                    instance
                )

                if "#" in instance_string:

                    instance_name = (
                        instance_string
                        .split("#")[-1]
                    )

                else:

                    instance_name = (
                        instance_string
                        .split("/")[-1]
                    )

                # --------------------------------------------
                # Default values
                # --------------------------------------------

                x = 0.0
                y = 0.0
                z = 0.0

                dx = 0.0
                dy = 1.0
                dz = 0.0

                length_mm = 40.0
                diameter_mm = 4.8

                # --------------------------------------------
                # Read predicates
                # --------------------------------------------

                for predicate, obj in (
                    graph.predicate_objects(
                        instance
                    )
                ):

                    predicate_string = str(
                        predicate
                    )

                    if "#" in predicate_string:

                        predicate_name = (
                            predicate_string
                            .split("#")[-1]
                        )

                    else:

                        predicate_name = (
                            predicate_string
                            .split("/")[-1]
                        )

                    try:

                        value = float(
                            obj
                        )

                    except (
                        ValueError,
                        TypeError
                    ):

                        continue

                    # Coordinates

                    if predicate_name == "hasContactX":
                        x = value

                    elif predicate_name == "hasContactY":
                        y = value

                    elif predicate_name == "hasContactZ":
                        z = value

                    elif predicate_name == "hasX":
                        x = value

                    elif predicate_name == "hasY":
                        y = value

                    elif predicate_name == "hasZ":
                        z = value

                    # Direction

                    elif predicate_name == "hasDirX":
                        dx = value

                    elif predicate_name == "hasDirY":
                        dy = value

                    elif predicate_name == "hasDirZ":
                        dz = value

                    # Dimensions

                    elif predicate_name == "hasLength":
                        length_mm = value

                    elif predicate_name == "hasDiameter":
                        diameter_mm = value

                connections.append(
                    {
                        "ID":
                            f"O-{connection_number:03d}",

                        "Ontology Instance":
                            instance_name,

                        "Source":
                            "Ontology",

                        "X":
                            float(x),

                        "Y":
                            float(y),

                        "Z":
                            float(z),

                        "Direction X":
                            dx,

                        "Direction Y":
                            dy,

                        "Direction Z":
                            dz,

                        "Diameter mm":
                            diameter_mm,

                        "Length mm":
                            length_mm,
                    }
                )

                connection_number += 1

    except Exception as error:

        st.error(
            f"Error reading ontology: {error}"
        )

    return connections


# ============================================================
# 7. FIND PANEL ORIGIN
# ============================================================

def get_ifc_panel_origin(
    panel_meshes
):
    """
    Get the minimum XYZ coordinate of the IFC panel.

    This becomes the LOCAL ORIGIN of the panel.

    Example:

        IFC:
        X = 3.319 ... 3.939
        Y = 8.049 ... 8.669
        Z = 5.385 ... 5.689

    becomes:

        Local:
        X = 0.000 ... 0.620
        Y = 0.000 ... 0.620
        Z = 0.000 ... 0.304
    """

    valid_bounds = [
        mesh.bounds
        for mesh in panel_meshes
        if mesh is not None
        and mesh.n_points > 0
    ]

    if not valid_bounds:

        return (
            0.0,
            0.0,
            0.0
        )

    min_x = min(
        b[0]
        for b in valid_bounds
    )

    min_y = min(
        b[2]
        for b in valid_bounds
    )

    min_z = min(
        b[4]
        for b in valid_bounds
    )

    return (
        min_x,
        min_y,
        min_z
    )


# ============================================================
# 8. GET ONTOLOGY ORIGIN
# ============================================================

def get_ontology_origin(
    ontology_connections
):
    """
    Determine the minimum XYZ coordinates of the ontology
    connection set.

    Because the ontology is already in a local panel
    coordinate system, this gives us the ontology's local
    origin reference.
    """

    if not ontology_connections:

        return (
            0.0,
            0.0,
            0.0
        )

    min_x = min(
        c["X"]
        for c in ontology_connections
    )

    min_y = min(
        c["Y"]
        for c in ontology_connections
    )

    min_z = min(
        c["Z"]
        for c in ontology_connections
    )

    return (
        min_x,
        min_y,
        min_z
    )


# ============================================================
# 9. NORMALIZE GEOMETRIC CONNECTIONS
# ============================================================

def normalize_geometric_connections(connections, origin):
    ox, oy, oz = origin
    normalized = []

    for connection in connections:
        c = connection.copy()

        c["Original X"] = c["X"]
        c["Original Y"] = c["Y"]
        c["Original Z"] = c["Z"]

        c["X"] = c["X"] - ox
        c["Y"] = c["Y"] - oy
        c["Z"] = c["Z"] - oz

        # --- NEW: Shift the Dimples to local (0,0,0) ---
        if "Holes" in c:
            norm_holes = []
            for h in c["Holes"]:
                nh = h.copy()
                nh["x"] = nh["x"] - ox
                nh["y"] = nh["y"] - oy
                nh["z"] = nh["z"] - oz
                norm_holes.append(nh)
            c["Holes"] = norm_holes

        normalized.append(c)

    return normalized


# ============================================================
# 10. NORMALIZE ONTOLOGY CONNECTIONS
# ============================================================

def normalize_ontology_connections(moveox, moveoy, moveoz,
    connections,
    origin
):
    """
    Translate ontology coordinates into a local panel
    coordinate system.

    The ontology is already local, so its own minimum
    coordinate is used as the origin.
    """

    ox, oy, oz = origin

    ox = ox + (moveox*0.1)
    oy = oy + (moveoy*0.1)
    oz = oz + (moveoz*0.1)
    normalized = []

    for connection in connections:

        c = connection.copy()

        c["Original X"] = c["X"]
        c["Original Y"] = c["Y"]
        c["Original Z"] = c["Z"]

        c["X"] = (
            c["X"] - ox
        )

        c["Y"] = (
            c["Y"] - oy
        )

        c["Z"] = (
            c["Z"] - oz
        )

        normalized.append(c)

    return normalized


# ============================================================
# 11. MATCH CONNECTIONS
# ============================================================

def match_connections(
    geometric_connections,
    ontology_connections,
    tolerance
):
    """
    Match normalized geometric and ontology connections.

    The matching is based primarily on XYZ distance.

    Each ontology connection can only be matched once.

    Returns:

        matched_pairs
        unmatched_geometry
        unmatched_ontology
    """

    matched_pairs = []

    unmatched_geometry = []
    unmatched_ontology = []

    used_ontology = set()

    for geometric in geometric_connections:

        g_position = np.array(
            [
                geometric["X"],
                geometric["Y"],
                geometric["Z"]
            ],
            dtype=float
        )

        best_match = None
        best_distance = float("inf")

        for ontology_index, ontology in enumerate(
            ontology_connections
        ):

            if ontology_index in used_ontology:
                continue

            o_position = np.array(
                [
                    ontology["X"],
                    ontology["Y"],
                    ontology["Z"]
                ],
                dtype=float
            )

            distance = np.linalg.norm(
                g_position - o_position
            )

            if (
                distance < best_distance
                and
                distance <= tolerance
            ):

                best_distance = distance
                best_match = ontology_index

        if best_match is not None:

            ontology = (
                ontology_connections[
                    best_match
                ]
            )

            used_ontology.add(
                best_match
            )

            matched_pairs.append(
                {
                    "geometry":
                        geometric,

                    "ontology":
                        ontology,

                    "distance":
                        best_distance
                }
            )

        else:

            unmatched_geometry.append(
                geometric
            )

    # --------------------------------------------------------
    # Remaining ontology connections
    # --------------------------------------------------------

    for ontology_index, ontology in enumerate(
        ontology_connections
    ):

        if ontology_index not in used_ontology:

            unmatched_ontology.append(
                ontology
            )

    return (
        matched_pairs,
        unmatched_geometry,
        unmatched_ontology
    )


# ============================================================
# 12. CONSOLIDATE MATCHED CONNECTIONS
# ============================================================

def consolidate_connections(
    matched_pairs,
    unmatched_geometry,
    unmatched_ontology,
    keep_unmatched_geometry,
    keep_unmatched_ontology
):
    """
    Create the final consolidated connection list.

    Matched connections are represented ONCE.

    Unmatched connections are optionally preserved.
    """

    consolidated = []

    connection_number = 1


    # ========================================================
    # MATCHED CONNECTIONS
    # ========================================================

    for pair in matched_pairs:

        geometry = pair["geometry"]
        ontology = pair["ontology"]

        # --- NEW: CALCULATE UNIT VECTOR (Geometry -> Ontology) ---
        vx = ontology["X"] - geometry["X"]
        vy = ontology["Y"] - geometry["Y"]
        vz = ontology["Z"] - geometry["Z"]
        magnitude = np.sqrt(vx**2 + vy**2 + vz**2)

        if magnitude > 1e-6:
            ux, uy, uz = vx / magnitude, vy / magnitude, vz / magnitude
        else:
            ux, uy, uz = 0.0, 0.0, 1.0  # Fallback if points perfectly overlap

        # --------------------------------------------
        # Use the average position of both sources.

        x = (
            geometry["X"]
            +
            ontology["X"]
        ) / 2.0

        y = (
            geometry["Y"]
            +
            ontology["Y"]
        ) / 2.0

        z = (
            geometry["Z"]
            +
            ontology["Z"]
        ) / 2.0

        # --------------------------------------------
        # Use ontology direction when available.
        # --------------------------------------------

        dx = ontology[
            "Direction X"
        ]

        dy = ontology[
            "Direction Y"
        ]

        dz = ontology[
            "Direction Z"
        ]

        consolidated.append(
            {
                "Connection ID":
                    f"C-{connection_number:03d}",

                "Source":
                    "Both",

                "Geometry ID":
                    geometry["ID"],

                "Ontology ID":
                    ontology["ID"],

                "Member 1":
                    geometry["Member 1"],

                "Member 2":
                    geometry["Member 2"],

                "Ontology Instance":
                    ontology[
                        "Ontology Instance"
                    ],

                "X":
                    x,

                "Y":
                    y,

                "Z":
                    z,

                "Direction X":
                    dx,

                "Direction Y":
                    dy,

                "Direction Z":
                    dz,
                # --- NEW: PASS VECTOR TO PLOTTER ---
                "Plane Normal X": ux,
                "Plane Normal Y": uy,
                "Plane Normal Z": uz,

                "Match Distance mm":
                    pair["distance"] * 1000.0,

                "Diameter mm":
                    ontology[
                        "Diameter mm"
                    ],

                "Length mm":
                    ontology[
                        "Length mm"
                    ],

                "Status":
                    "Matched"
            }
        )

        connection_number += 1

    # ========================================================
    # UNMATCHED GEOMETRIC CONNECTIONS
    # ========================================================

    if keep_unmatched_geometry:

        for geometry in unmatched_geometry:

            consolidated.append(
                {
                    "Connection ID":
                        f"C-{connection_number:03d}",

                    "Source":
                        "Geometry",

                    "Geometry ID":
                        geometry["ID"],

                    "Ontology ID":
                        "",

                    "Member 1":
                        geometry["Member 1"],

                    "Member 2":
                        geometry["Member 2"],

                    "Ontology Instance":
                        "",

                    "X":
                        geometry["X"],

                    "Y":
                        geometry["Y"],

                    "Z":
                        geometry["Z"],

                    "Direction X":
                        geometry[
                            "Direction X"
                        ],

                    "Direction Y":
                        geometry[
                            "Direction Y"
                        ],

                    "Direction Z":
                        geometry[
                            "Direction Z"
                        ],

                    "Match Distance mm":
                        np.nan,

                    "Diameter mm":
                        np.nan,

                    "Length mm":
                        np.nan,

                    "Status":
                        "Geometry only"
                }
            )

            connection_number += 1

    # ========================================================
    # UNMATCHED ONTOLOGY CONNECTIONS
    # ========================================================

    if keep_unmatched_ontology:

        for ontology in unmatched_ontology:

            consolidated.append(
                {
                    "Connection ID":
                        f"C-{connection_number:03d}",

                    "Source":
                        "Ontology",

                    "Geometry ID":
                        "",

                    "Ontology ID":
                        ontology["ID"],

                    "Member 1":
                        "",

                    "Member 2":
                        "",

                    "Ontology Instance":
                        ontology[
                            "Ontology Instance"
                        ],

                    "X":
                        ontology["X"],

                    "Y":
                        ontology["Y"],

                    "Z":
                        ontology["Z"],

                    "Direction X":
                        ontology[
                            "Direction X"
                        ],

                    "Direction Y":
                        ontology[
                            "Direction Y"
                        ],

                    "Direction Z":
                        ontology[
                            "Direction Z"
                        ],

                    "Match Distance mm":
                        np.nan,

                    "Diameter mm":
                        ontology[
                            "Diameter mm"
                        ],

                    "Length mm":
                        ontology[
                            "Length mm"
                        ],

                    "Status":
                        "Ontology only"
                }
            )

            connection_number += 1

    return consolidated


# ============================================================
# 13. MAIN APPLICATION
# ============================================================

if (
    "current_ifc_path" in st.session_state
    and
    os.path.exists(
        st.session_state[
            "current_ifc_path"
        ]
    )
):

    ifcfile_path = (
        st.session_state[
            "current_ifc_path"
        ]
    )

    ontology_path = st.session_state.get(
        "current_ontology_path",
        None
    )

    has_ontology = (
        ontology_path is not None
        and
        os.path.exists(
            ontology_path
        )
    )

    # ========================================================
    # TITLE
    # ========================================================

    st.title(
        "Panel Connections"
    )

    st.markdown(
        """
        Connection information is extracted independently from
        the IFC geometry and the ontology. Matching connections
        are then consolidated into a single connection.
        """
    )

    # ========================================================
    # PARAMETERS
    # ========================================================

    st.markdown(
        "---"
    )

    st.markdown(
        "## Connection Matching"
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        tolerance_mm = st.number_input(
            "Matching Tolerance (mm)",
            min_value=-100.0,
            max_value=1000.0,
            value=100.0,
            step=0.5
        )
        moveox = st.number_input(
            "Move Ontology ox (mm)",
            min_value=-100.0,
            max_value=100.0,
            value=-0.25,
            step=0.5
        )
    

    with col2:

        inflate_x_mm = st.number_input(
            "Geometric X Tolerance (mm)",
            min_value=-100.0,
            value=25.0,
            step=5.0
        )

        moveoy = st.number_input(
            "Move Ontology oy (mm)",
            min_value=-100.0,
            max_value=100.0,
            value=0.0,
            step=0.5
        )

    with col3:

        inflate_y_mm = st.number_input(
            "Geometric Y Tolerance (mm)",
            min_value=-100.0,
            value=25.0,
            step=5.0
        )

        inflate_z_mm = st.number_input(
            "Geometric Z Tolerance (mm)",
            min_value=-100.0,
            value=-25.0,
            step=5.0
        )

        moveoz = st.number_input(
            "Move Ontology oz (mm)",
            min_value=-100.0,
            max_value=100.0,
            value=-0.25,
            step=0.5
        )

    # ========================================================
    # UNMATCHED CONNECTION OPTIONS
    # ========================================================

    st.markdown(
        "### Unmatched Connections"
    )

    keep_unmatched_geometry = st.checkbox(
        "Keep unmatched geometric connections",
        value=False,
        help=(
            "If disabled, geometric connections that do "
            "not have an ontology match will be removed "
            "from the final consolidated result."
        )
    )

    keep_unmatched_ontology = st.checkbox(
        "Keep unmatched ontology connections",
        value=False,
        help=(
            "If disabled, ontology connections that do "
            "not have a geometric match will be removed "
            "from the final consolidated result."
        )
    )

    # ========================================================
    # VIEW OPTIONS
    # ========================================================

    st.markdown(
        "### 3D View"
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        show_panel = st.checkbox(
            "Show Panel",
            value=True
        )

    with col2:

        show_raw_geometry = st.checkbox(
            "Show Raw Geometry Connections",
            value=False
        )

    with col3:

        show_raw_ontology = st.checkbox(
            "Show Raw Ontology Connections",
            value=False
        )

    with col4:

        show_consolidated = st.checkbox(
            "Show Consolidated Connections",
            value=True
        )

    # ========================================================
    # RUN ANALYSIS
    # ========================================================

    with st.spinner(
        "Analyzing panel connections..."
    ):

        try:

            # =================================================
            # LOAD IFC
            # =================================================

            all_elements = (
                Find_elements.get_elements(
                    ifcfile_path
                )
            )

            panel_meshes = (
                Find_elements.get_3d_meshes(
                    all_elements
                )
            )

            # =================================================
            # EXTRACT GEOMETRY
            # =================================================

            geometric_connections = (
                extract_geometric_connections(
                    all_elements,
                    panel_meshes,
                    inflate_x_mm / 1000.0,
                    inflate_y_mm / 1000.0,
                    inflate_z_mm / 1000.0
                )
            )

            # --- NEW: ATTACH DIMPLES ---
            geometric_connections = attach_dimples_to_geometric_connections(
                geometric_connections, panel_meshes
            )

            # =================================================
            # EXTRACT ONTOLOGY
            # =================================================

            ontology_connections = []

            if has_ontology:

                ontology_connections = (
                    extract_ontology_connections(
                        ontology_path
                    )
                )

            # =================================================
            # DETERMINE ORIGINS
            # =================================================

            ifc_origin = (
                get_ifc_panel_origin(
                    panel_meshes
                )
            )

            ontology_origin = (
                get_ontology_origin(
                    ontology_connections
                )
            )

            # =================================================
            # NORMALIZE BOTH DATASETS
            # =================================================

            normalized_geometry = (
                normalize_geometric_connections(
                    geometric_connections,
                    ifc_origin
                )
            )

            normalized_ontology = (
                normalize_ontology_connections(
                    moveox,
                    moveoy,
                    moveoz,
                    ontology_connections,
                    ontology_origin
                )
            )

            # =================================================
            # MATCH
            # =================================================

            (
                matched_pairs,
                unmatched_geometry,
                unmatched_ontology
            ) = match_connections(
                normalized_geometry,
                normalized_ontology,
                tolerance_mm / 1000.0
            )

            # =================================================
            # CONSOLIDATE
            # =================================================

            consolidated_connections = (
                consolidate_connections(
                    matched_pairs,
                    unmatched_geometry,
                    unmatched_ontology,
                    keep_unmatched_geometry,
                    keep_unmatched_ontology
                )
            )

            # =================================================
            # 3D PLOTTER
            # =================================================

            plotter = pv.Plotter(
                window_size=[
                    850,
                    800
                ]
            )

            plotter.set_background(
                "white"
            )

            plotter.add_axes(
                line_width=5,
                labels_off=False,
                color="black"
            )

            # =================================================
            # PANEL
            # =================================================

            if show_panel:

                for mesh in panel_meshes:

                    if mesh is None:
                        continue

                    if mesh.n_points == 0:
                        continue

                    # Move panel itself to local origin
                    mesh_local = mesh.copy()

                    mesh_local.translate(
                        (
                            -ifc_origin[0],
                            -ifc_origin[1],
                            -ifc_origin[2]
                        ),
                        inplace=True
                    )

                    plotter.add_mesh(
                        mesh_local,
                        color="lightgray",
                        opacity=0.65,
                        smooth_shading=True
                    )

                    # --- NEW: BLUE ORIGIN SPHERE ---
                origin_sphere = pv.Sphere(radius=0.03, center=(0.0, 0.0, 0.0))
                plotter.add_mesh(origin_sphere, color="blue", smooth_shading=True)
            # -------------------------------

            # =================================================
            # RAW GEOMETRIC CONNECTIONS
            # =================================================

            if show_raw_geometry:

                for connection in normalized_geometry:

                    for hole in connection.get("Holes", []):
                        hole_mesh = pv.Cylinder(
                            center=(hole["x"], hole["y"], hole["z"]),
                            direction=hole["dir"],
                            radius=hole["diam"] / 2.0,
                            height=hole["length"]
                        )
                        plotter.add_mesh(hole_mesh, color="red", smooth_shading=True)

                    center = (
                        connection["X"],
                        connection["Y"],
                        connection["Z"]
                    )

                    # ALWAYS display the sphere
                    plotter.add_mesh(
                        pv.Sphere(radius=0.012, center=center),
                        color="yellow", 
                        smooth_shading=True
                    )

                    # --- NEW: Check if this connection was matched ---
                    matched_consolidation = next(
                        (c for c in consolidated_connections if c.get("Geometry ID") == connection["ID"] and c.get("Source") == "Both"), 
                        None
                    )

                    # ONLY draw the cube if a unit vector was calculated from a match
                    if matched_consolidation:
                        ux = matched_consolidation.get("Plane Normal X", 0.0)
                        uy = matched_consolidation.get("Plane Normal Y", 0.0)
                        uz = matched_consolidation.get("Plane Normal Z", 1.0)

                        safe_uz = np.clip(uz, -1.0, 1.0)
                        theta_y = np.degrees(np.arccos(safe_uz))
                        phi_z = np.degrees(np.arctan2(uy, ux))

                        cube = pv.Cube(
                            center=(0.0, 0.0, 0.0),
                            x_length=0.035, 
                            y_length=0.035, 
                            z_length=0.005
                        )
                        cube.rotate_y(theta_y, inplace=True)
                        cube.rotate_z(phi_z, inplace=True)
                        cube.translate(center, inplace=True)

                        plotter.add_mesh(cube, color="yellow", smooth_shading=True)
            # =================================================
            # RAW ONTOLOGY CONNECTIONS
            # =================================================

            # =================================================
            # RAW ONTOLOGY CONNECTIONS
            # =================================================

            if show_raw_ontology:

                for connection in normalized_ontology:

                    center = (
                        connection["X"],
                        connection["Y"],
                        connection["Z"]
                    )

                    # ALWAYS display the sphere
                    plotter.add_mesh(
                        pv.Sphere(radius=0.010, center=center),
                        color="green",
                        smooth_shading=True
                    )

                    # --- NEW: Check if this connection was matched ---
                    matched_consolidation = next(
                        (c for c in consolidated_connections if c.get("Ontology ID") == connection["ID"] and c.get("Source") == "Both"), 
                        None
                    )

                    # ONLY draw the cube if a unit vector was calculated from a match
                    if matched_consolidation:
                        ux = matched_consolidation.get("Plane Normal X", 0.0)
                        uy = matched_consolidation.get("Plane Normal Y", 0.0)
                        uz = matched_consolidation.get("Plane Normal Z", 1.0)

                        safe_uz = np.clip(uz, -1.0, 1.0)
                        theta_y = np.degrees(np.arccos(safe_uz))
                        phi_z = np.degrees(np.arctan2(uy, ux))

                        cube = pv.Cube(
                            center=(0.0, 0.0, 0.0),
                            x_length=0.035, 
                            y_length=0.035, 
                            z_length=0.005
                        )
                        cube.rotate_y(theta_y, inplace=True)
                        cube.rotate_z(phi_z, inplace=True)
                        cube.translate(center, inplace=True)

                        plotter.add_mesh(cube, color="green", smooth_shading=True)

            # =================================================
            # CONSOLIDATED CONNECTIONS
            # =================================================

            if show_consolidated:

                for connection in consolidated_connections:

                    for hole in connection.get("Holes", []):
                        hole_mesh = pv.Cylinder(
                            center=(hole["x"], hole["y"], hole["z"]),
                            direction=hole["dir"],
                            radius=hole["diam"] / 2.0,
                            height=hole["length"]
                        )
                        plotter.add_mesh(hole_mesh, color="red", smooth_shading=True)

                    center = (
                        connection["X"],
                        connection["Y"],
                        connection["Z"]
                    )

                    source = connection[
                        "Source"
                    ]

                    # -----------------------------------------
                    # Matched
                    # -----------------------------------------

                    if source == "Both":
                        
                        # 1. Fetch the normal vector we calculated
                        ux = connection.get("Plane Normal X", 0.0)
                        uy = connection.get("Plane Normal Y", 0.0)
                        uz = connection.get("Plane Normal Z", 1.0)

                        # 2. Create a flat plate (thin along the Z-axis) at the origin
                        cube = pv.Cube(
                            center=(0.0, 0.0, 0.0),
                            x_length=0.035, 
                            y_length=0.035, 
                            z_length=0.005  # The thin plane axis
                        )

                        # 3. Calculate rotation angles to point the Z-axis toward the vector
                        # (We clip 'uz' to strictly stay between -1 and 1 to prevent NumPy NaN errors)
                        safe_uz = np.clip(uz, -1.0, 1.0)
                        theta_y = np.degrees(np.arccos(safe_uz))
                        phi_z = np.degrees(np.arctan2(uy, ux))

                        # 4. Apply rotations mathematically, then slide it into position
                        cube.rotate_y(theta_y, inplace=True)
                        cube.rotate_z(phi_z, inplace=True)
                        cube.translate(center, inplace=True)

                        plotter.add_mesh(
                            cube,
                            color="red",
                            smooth_shading=True
                        )

                    # -----------------------------------------
                    # Geometry only
                    # -----------------------------------------

                    elif source == "Geometry":

                        sphere = pv.Sphere(
                            radius=0.012,
                            center=center
                        )

                        plotter.add_mesh(
                            sphere,
                            color="orange",
                            smooth_shading=True
                        )

                    # -----------------------------------------
                    # Ontology only
                    # -----------------------------------------

                    elif source == "Ontology":

                        sphere = pv.Sphere(
                            radius=0.012,
                            center=center
                        )

                        plotter.add_mesh(
                            sphere,
                            color="green",
                            smooth_shading=True
                        )

            # =================================================
            # DISPLAY VIEWER
            # =================================================

            st.markdown(
                "---"
            )

            st.markdown(
                "## Consolidated Connection Model"
            )

            stpyvista(
                plotter
            )

            # =================================================
            # SUMMARY
            # =================================================

            st.markdown(
                "---"
            )

            st.markdown(
                "## Connection Summary"
            )

            col1, col2, col3, col4 = st.columns(4)

            with col1:

                st.metric(
                    "Geometric",
                    len(
                        normalized_geometry
                    )
                )

            with col2:

                st.metric(
                    "Ontology",
                    len(
                        normalized_ontology
                    )
                )

            with col3:

                st.metric(
                    "Matched",
                    len(
                        matched_pairs
                    )
                )

            with col4:

                st.metric(
                    "Final",
                    len(
                        consolidated_connections
                    )
                )

            # =================================================
            # COORDINATE SYSTEM INFORMATION
            # =================================================

            st.markdown(
                "## Coordinate Systems"
            )

            st.info(
                f"""
                **IFC world origin of this panel**

                X = {ifc_origin[0]:.4f} m  
                Y = {ifc_origin[1]:.4f} m  
                Z = {ifc_origin[2]:.4f} m

                Both datasets are now represented in a local
                panel coordinate system.

                The panel therefore starts approximately at:

                **(0, 0, 0)**
                """
            )

            # =================================================
            # MATCHING RESULTS
            # =================================================

            st.markdown(
                "---"
            )

            st.markdown(
                "## Matched Connections"
            )

            if matched_pairs:

                matched_table = []

                for pair in matched_pairs:

                    geometry = pair["geometry"]
                    ontology = pair["ontology"]

                    # --- NEW: CALCULATE UNIT VECTOR (Geometry -> Ontology) ---
                    vx = ontology["X"] - geometry["X"]
                    vy = ontology["Y"] - geometry["Y"]
                    vz = ontology["Z"] - geometry["Z"]
                    magnitude = np.sqrt(vx**2 + vy**2 + vz**2)

                    if magnitude > 1e-6:
                        ux, uy, uz = vx / magnitude, vy / magnitude, vz / magnitude
                    else:
                        ux, uy, uz = 0.0, 0.0, 1.0  # Fallback if points perfectly overlap

                    # --------------------------------------------
                    # Use the average position of both sources.

                    matched_table.append(
                    {
                            "Geometry ID":
                                geometry["ID"],

                            "Ontology ID":
                                ontology["ID"],

                            "X (m)":
                                round(
                                    (
                                        geometry["X"]
                                        +
                                        ontology["X"]
                                    ) / 2.0,
                                    4
                                ),

                            "Y (m)":
                                round(
                                    (
                                        geometry["Y"]
                                        +
                                        ontology["Y"]
                                    ) / 2.0,
                                    4
                                ),

                            "Z (m)":
                                round(
                                    (
                                        geometry["Z"]
                                        +
                                        ontology["Z"]
                                    ) / 2.0,
                                    4
                                ),

                            "Match Error (mm)":
                                round(
                                    pair[
                                        "distance"
                                    ] * 100.0,
                                    3
                                ),

                            "Ontology Instance":
                                ontology[
                                    "Ontology Instance"
                                ]
                        }
                    )

                df_matched = pd.DataFrame(
                    matched_table
                )

                st.dataframe(
                    df_matched,
                    use_container_width=True
                )

            else:

                st.warning(
                    "No geometric/ontology matches were found."
                )

            # =================================================
            # FINAL CONNECTION TABLE
            # =================================================

            st.markdown(
                "---"
            )

            st.markdown(
                "## Final Consolidated Connections"
            )

            if consolidated_connections:

                final_table = []

                for connection in (
                    consolidated_connections
                ):

                    final_table.append(
                        {
                            "Connection ID":
                                connection[
                                    "Connection ID"
                                ],

                            "Source":
                                connection[
                                    "Source"
                                ],

                            "Geometry ID":
                                connection[
                                    "Geometry ID"
                                ],

                            "Ontology ID":
                                connection[
                                    "Ontology ID"
                                ],

                            "Member 1":
                                connection[
                                    "Member 1"
                                ],

                            "Member 2":
                                connection[
                                    "Member 2"
                                ],

                            "Ontology Instance":
                                connection[
                                    "Ontology Instance"
                                ],

                            "X (m)":
                                round(
                                    connection["X"],
                                    4
                                ),

                            "Y (m)":
                                round(
                                    connection["Y"],
                                    4
                                ),

                            "Z (m)":
                                round(
                                    connection["Z"],
                                    4
                                ),

                            # --- NEW: UNIT VECTOR COLUMNS ---
                            "Vector X":
                                round(
                                    connection.get("Plane Normal X", connection.get("Direction X", 0.0)), 
                                    4
                                ),

                            "Vector Y":
                                round(
                                    connection.get("Plane Normal Y", connection.get("Direction Y", 0.0)), 
                                    4
                                ),

                            "Vector Z":
                                round(
                                    connection.get("Plane Normal Z", connection.get("Direction Z", 1.0)), 
                                    4
                                ),
                            # --------------------------------

                            "Match Error (mm)":
                                (
                                    round(
                                        connection[
                                            "Match Distance mm"
                                        ],
                                        3
                                    )
                                    if not pd.isna(
                                        connection[
                                            "Match Distance mm"
                                        ]
                                    )
                                    else ""
                                ),

                            "Diameter (mm)":
                                (
                                    connection[
                                        "Diameter mm"
                                    ]
                                    if not pd.isna(
                                        connection[
                                            "Diameter mm"
                                        ]
                                    )
                                    else ""
                                ),

                            "Length (mm)":
                                (
                                    connection[
                                        "Length mm"
                                    ]
                                    if not pd.isna(
                                        connection[
                                            "Length mm"
                                        ]
                                    )
                                    else ""
                                ),

                            "Status":
                                connection[
                                    "Status"
                                ]
                        }
                    )

                df_final = pd.DataFrame(
                    final_table
                )

                st.dataframe(
                    df_final,
                    use_container_width=True
                )

                # --------------------------------------------
                # CSV EXPORT
                # --------------------------------------------

                st.download_button(
                    "Download Consolidated Connections CSV",
                    df_final.to_csv(
                        index=False
                    ).encode("utf-8"),
                    "consolidated_connections.csv",
                    "text/csv"
                )

            else:

                st.warning(
                    "There are no connections in the final model."
                )

            # =================================================
            # UNMATCHED INFORMATION
            # =================================================

            st.markdown(
                "---"
            )

            st.markdown(
                "## Unmatched Connections"
            )

            unmatched_col1, unmatched_col2 = (
                st.columns(2)
            )

            with unmatched_col1:

                st.write(
                    f"Geometric only: "
                    f"**{len(unmatched_geometry)}**"
                )

                if unmatched_geometry:

                    geometry_unmatched_table = []

                    for connection in (
                        unmatched_geometry
                    ):

                        geometry_unmatched_table.append(
                            {
                                "ID":
                                    connection["ID"],

                                "X (m)":
                                    round(
                                        connection["X"],
                                        4
                                    ),

                                "Y (m)":
                                    round(
                                        connection["Y"],
                                        4
                                    ),

                                "Z (m)":
                                    round(
                                        connection["Z"],
                                        4
                                    ),

                                "Member 1":
                                    connection[
                                        "Member 1"
                                    ],

                                "Member 2":
                                    connection[
                                        "Member 2"
                                    ]
                            }
                        )

                    st.dataframe(
                        pd.DataFrame(
                            geometry_unmatched_table
                        ),
                        use_container_width=True
                    )

            with unmatched_col2:

                st.write(
                    f"Ontology only: "
                    f"**{len(unmatched_ontology)}**"
                )

                if unmatched_ontology:

                    ontology_unmatched_table = []

                    for connection in (
                        unmatched_ontology
                    ):

                        ontology_unmatched_table.append(
                            {
                                "ID":
                                    connection["ID"],

                                "Instance":
                                    connection[
                                        "Ontology Instance"
                                    ],

                                "X (m)":
                                    round(
                                        connection["X"],
                                        4
                                    ),

                                "Y (m)":
                                    round(
                                        connection["Y"],
                                        4
                                    ),

                                "Z (m)":
                                    round(
                                        connection["Z"],
                                        4
                                    )
                            }
                        )

                    st.dataframe(
                        pd.DataFrame(
                            ontology_unmatched_table
                        ),
                        use_container_width=True
                    )

        except Exception as error:

            st.error(
                f"Error during connection analysis: {error}"
            )

            st.exception(
                error
            )

else:

    st.warning(
        "⚠️ No IFC file loaded. "
        "Please upload a model on the Start page."
    )