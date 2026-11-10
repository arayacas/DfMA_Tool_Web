import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv

def get_elements(file_path):
    # 1. Open the file
    model = ifcopenshell.open(file_path)
    
    # 2. Grab the vertical studs and horizontal tracks
    beams = model.by_type("IfcBeam")
    columns = model.by_type("IfcColumn")
    members = model.by_type("IfcMember") # The new file uses this!

    all_framing = beams + columns + members
    
    # 4. If they are still zero check for miscellaneous elements, unclasified elements safety net
    if len(all_framing) == 0:
        all_framing = model.by_type("IfcBuildingElementProxy")
        
    return all_framing

def get_ifc_panel_origin(panel_meshes):
    """
    Get the minimum XYZ coordinate of the IFC panel meshes.
    This becomes the (0, 0, 0) LOCAL ORIGIN of the panel.
    """
    valid_bounds = [
        mesh.bounds
        for mesh in panel_meshes
        if mesh is not None and mesh.n_points > 0
    ]

    if not valid_bounds:
        return (0.0, 0.0, 0.0)

    min_x = min(b[0] for b in valid_bounds)
    min_y = min(b[2] for b in valid_bounds)
    min_z = min(b[4] for b in valid_bounds)

    return (min_x, min_y, min_z)

def get_stud_coordinates(elements, panel_meshes=None):
    """
    Extracts local member center coordinates (X, Y, Z) normalized to the
    exact same (0, 0, 0) panel origin used in Panel_Connections.py, along
    with each member's 3D unit orientation vector.
    """
    if panel_meshes is None:
        panel_meshes = get_3d_meshes(elements)

    ox, oy, oz = get_ifc_panel_origin(panel_meshes)
    coordinates_list = []

    for idx, (element, mesh) in enumerate(zip(elements, panel_meshes)):
        if mesh is None or mesh.n_points == 0:
            continue

        b = mesh.bounds
        # Bounding-box midpoint in Global IFC space
        cx_global = (b[0] + b[1]) / 2.0
        cy_global = (b[2] + b[3]) / 2.0
        cz_global = (b[4] + b[5]) / 2.0

        # Shift to Local Panel Origin (0, 0, 0) to match Panel_Connections.py
        local_x = cx_global - ox
        local_y = cy_global - oy
        local_z = cz_global - oz

        # Extract 3D orientation vector and structural type
        vx, vy, vz, orientation_type = get_member_orientation_from_mesh(mesh, element)

        raw_name = getattr(element, "Name", None) or f"Member_{idx+1}"
        gid = getattr(element, "GlobalId", "Unknown_GID")
        short_gid = gid[-4:] if len(gid) >= 4 else gid

        # Build a unique display name if Option 1 isn't already applied
        unique_name = raw_name if str(raw_name).endswith(f"[{short_gid}]") else f"{raw_name} [{short_gid}]"

        coordinates_list.append({
            "Member ID (Short)": unique_name,
            "Profile Name": str(raw_name),
            "GlobalId (IFC)": str(gid),
            "Ontology GID": str(gid).replace("$", "_"),  # Matches .ttl sanitized IDs
            "Orientation": orientation_type,
            "X (m)": round(local_x, 4),
            "Y (m)": round(local_y, 4),
            "Z (m)": round(local_z, 4),
            "Vector X": vx,
            "Vector Y": vy,
            "Vector Z": vz
        })

    return coordinates_list
def sort_framing_by_orientation(elements):
    """Sorts steel members into vertical and horizontal lists based on their 3D proportions."""
    vertical_studs = []
    horizontal_tracks = []
    
    # We need the geometry engine to measure the parts in world coordinates
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    for element in elements:
        try:
            # 1. Generate the raw geometry points
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = shape.geometry.verts
            vertices = np.array(verts).reshape((-1, 3))
            
            # 2. Calculate the Bounding Box (Min and Max points)
            min_coords = vertices.min(axis=0) # [min_X, min_Y, min_Z]
            max_coords = vertices.max(axis=0) # [max_X, max_Y, max_Z]
            
            # 3. Find the physical dimensions in millimeters
            dimensions = max_coords - min_coords
            dx = dimensions[0] # Length along X axis
            dy = dimensions[1] # Length along Y axis
            dz = dimensions[2] # Height along Z axis
            
            # 4. Sorting Logic
            # If its height (Z) is strictly greater than its width (X) AND depth (Y)...
            if dz > dx and dz > dy:
                vertical_studs.append(element)
            else:
                horizontal_tracks.append(element)
                
        except Exception:
            # If a proxy object has no geometry, we ignore it
            pass
            
    return vertical_studs, horizontal_tracks

def get_3d_meshes(elements):
    """Takes a list of IFC elements and converts them into PyVista 3D meshes."""
    
    # Turn on the geometry engine
    settings = ifcopenshell.geom.settings()
    
    # This forces the engine to move the studs from (0,0,0) to their real world coordinates
    settings.set(settings.USE_WORLD_COORDS, True) 
    
    mesh_list = []
    
    for element in elements:
        try:
            # Let the engine calculate the 3D shape
            shape = ifcopenshell.geom.create_shape(settings, element)
            
            # Extract the raw X,Y,Z points (Vertices) and Triangles (Faces)
            verts = shape.geometry.verts
            faces = shape.geometry.faces
            
            # Math formatting: Group the long lists into X,Y,Z coordinates
            vertices = np.array(verts).reshape((-1, 3))
            faces_np = np.array(faces).reshape((-1, 3))
            
            # PyVista quirk: It needs a '3' in front of every triangle
            padding = np.full((faces_np.shape[0], 1), 3)
            pv_faces = np.hstack((padding, faces_np)).flatten()
            
            # Create the PyVista 3D object and add it to our list
            poly_data = pv.PolyData(vertices, pv_faces)
            mesh_list.append(poly_data)
            
        except Exception:
            pass
            
    return mesh_list
def get_member_orientation_from_mesh(mesh, element=None):
    """
    Calculates the longitudinal unit vector (Vector X, Vector Y, Vector Z)
    and structural orientation of a member.
    Uses Principal Component Analysis (SVD) on the 3D mesh points so it is
    immune to inconsistent CAD drawing axes, with an IFC matrix fallback.
    """
    try:
        if mesh is not None and mesh.n_points >= 3:
            pts = np.asarray(mesh.points, dtype=float)
            centered_pts = pts - pts.mean(axis=0)
            
            # SVD: The first principal component (vh[0]) is the longest physical axis
            _, _, vh = np.linalg.svd(centered_pts, full_matrices=False)
            vec = vh[0]
            
            # Standardize vector sign so Vertical vectors always point Up (+Z)
            # and Horizontal vectors point consistently in +X / +Y
            if abs(vec[2]) > 0.7:
                if vec[2] < 0:
                    vec = -vec
            elif abs(vec[0]) > 1e-4:
                if vec[0] < 0:
                    vec = -vec
            elif vec[1] < 0:
                vec = -vec

            vx, vy, vz = float(vec[0]), float(vec[1]), float(vec[2])
        else:
            # Fallback to IFC Local Placement Z-axis
            matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
            vx, vy, vz = float(matrix[0][2]), float(matrix[1][2]), float(matrix[2][2])

        # Classify human-readable orientation using the vertical Z component
        if abs(vz) >= 0.85:
            role = "Vertical (Stud)"
        elif abs(vz) <= 0.15:
            role = "Horizontal (Track)"
        else:
            role = "Slanted / Diagonal"

        return round(vx, 4), round(vy, 4), round(vz, 4), role

    except Exception:
        return 0.0, 0.0, 1.0, "Unknown"
