import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pyvista as pv

def get_elements(file_path):
    # 1. Open the file
    model = ifcopenshell.open(file_path)
    
    # 2. Grab the vertical studs and horizontal tracks
    vertical_studs = model.by_type("IfcColumn")
    horizontal_tracks = model.by_type("IfcBeam")
    
    # 3. Combine both lists together
    all_framing = vertical_studs + horizontal_tracks
    
    # 4. If they are still zero check for miscellaneous elements, unclasified elements safety net
    if len(all_framing) == 0:
        all_framing = model.by_type("IfcBuildingElementProxy")
        
    return all_framing

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

def get_stud_coordinates(elements):
    """Extracts raw X, Y, Z locations from the IFC pointer trail."""
    coordinates_list = []
    
    for element in elements:
        try:
            placement = element.ObjectPlacement
            relative_placement = placement.RelativePlacement
            location = relative_placement.Location
            xyz = location.Coordinates
            
            coordinates_list.append({
                "Name": element.Name,
                "X": xyz[0],
                "Y": xyz[1],
                "Z": xyz[2]
            })
        except Exception:
            pass 
            
    return coordinates_list

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

