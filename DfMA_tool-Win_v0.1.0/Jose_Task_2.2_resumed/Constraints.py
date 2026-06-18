import numpy as np
import ifcopenshell.geom
import json
import os
import pyvista as pv
import ifcopenshell.util.element

#RULE 1
def check_max_dimensions(elements, max_length_mm=6.00, max_height_mm=3.00):
    """
    Checks if the overall wall panel exceeds the allowed manufacturing dimensions.
    Constraints are passed directly from the main UI script to avoid local file dependencies.
    
    Returns:
        dict: A report containing the pass/fail status and the violating elements.
    """
    # --- 1. RUN THE MATH ---
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    violating_elements = []
    
    # Find the absolute min and max coordinates of the ENTIRE panel
    global_min_x = float('inf')
    global_max_x = float('-inf')
    global_min_z = float('inf')
    global_max_z = float('-inf')

    # Analyze every element to find the global boundaries
    for element in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = shape.geometry.verts
            vertices = np.array(verts).reshape((-1, 3))
            
            min_coords = vertices.min(axis=0) # [X, Y, Z]
            max_coords = vertices.max(axis=0) # [X, Y, Z]
            
            if min_coords[0] < global_min_x: global_min_x = min_coords[0]
            if max_coords[0] > global_max_x: global_max_x = max_coords[0]
            if min_coords[2] < global_min_z: global_min_z = min_coords[2]
            if max_coords[2] > global_max_z: global_max_z = max_coords[2]
            
        except Exception:
            pass

    # Calculate the total physical size of the panel
    actual_length = global_max_x - global_min_x
    actual_height = global_max_z - global_min_z

    # Check against the constraints
    passed = True
    message = "Panel meets size constraints."
    
    if actual_length > max_length_mm or actual_height > max_height_mm:
        passed = False
        message = f"Panel exceeds limits! Actual: {actual_length:.1f}mm L x {actual_height:.1f}mm H. (Limits: {max_length_mm}mm x {max_height_mm}mm)"
        
        # Find exactly WHICH elements are sticking out
        for element in elements:
             try:
                 shape = ifcopenshell.geom.create_shape(settings, element)
                 verts = shape.geometry.verts
                 vertices = np.array(verts).reshape((-1, 3))
                 max_coords = vertices.max(axis=0)
                 
                 if (max_coords[0] - global_min_x) > max_length_mm or \
                    (max_coords[2] - global_min_z) > max_height_mm:
                     violating_elements.append(element)
             except Exception:
                 pass

    return {
        "passed": passed,
        "message": message,
        "actual_length": actual_length,
        "actual_height": actual_height,
        "violating_elements": violating_elements
    }
#RULE 2
def check_hole_alignment(elements, tolerance_m = 0.01):
    """
    Checks if the service holes (IfcOpeningElement) in the panel are horizontally aligned.
    Groups holes by their Z-elevation. If a hole does not align with any others, it fails.
    
    Args:
        elements: The raw IFC elements.
        tolerance_m: The allowed vertical deviation (in meters) to still be considered "aligned". Default is 10mm.
        
    Returns:
        dict: A report containing the pass/fail status and the violating elements.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    holes_data = []
    violating_elements = [] 

    # 1. Extract all holes and their Z-elevations
    for element in elements:
        # Check if the element has associated voids/openings
        if hasattr(element, 'HasOpenings'):
            for rel_voids in element.HasOpenings:
                # Ensure it is actually a void relationship
                if rel_voids.is_a("IfcRelVoidsElement"):
                    opening = rel_voids.RelatedOpeningElement
                    try:
                        # Generate the 3D geometry of the invisible hole
                        shape = ifcopenshell.geom.create_shape(settings, opening)
                        verts = np.array(shape.geometry.verts).reshape((-1, 3))
                        
                        # Find the exact 3D center of the hole (Z is the vertical axis)
                        center_z = verts[:, 2].mean() 
                        
                        holes_data.append({
                            "host_element": element,  # The stud containing the hole
                            "opening_id": opening.GlobalId,
                            "z_height": center_z
                        })
                    except Exception:
                        pass

    # Safety check: Did we actually find any holes?
    if len(holes_data) == 0:
        return {
            "passed": True,
            "message": "No explicit service holes (IfcOpeningElement) found in this panel.",
            "violating_elements": []
        }

    # 2. Group the holes into horizontal "Rows" using the tolerance
    rows = [] 
    for hole in holes_data:
        matched_row = False
        for row in rows:
            # Compare this hole to the first hole in an existing row
            if abs(hole["z_height"] - row[0]["z_height"]) <= tolerance_m:
                row.append(hole)
                matched_row = True
                break
        
        # If it didn't match any existing rows, create a new row for it
        if not matched_row:
            rows.append([hole])

    # 3. Determine if any hole is an orphan
    passed = True
    misaligned_holes_count = 0

    for row in rows:
        # A valid row of holes must pass through at least 2 studs.
        # If a row only has 1 hole, it is misaligned with the rest of the panel.
        if len(row) < 2:
            passed = False
            misaligned_holes_count += len(row)
            
            # Add the stud containing the bad hole to the red-paint list
            for hole in row:
                if hole["host_element"] not in violating_elements:
                    violating_elements.append(hole["host_element"])

    if passed:
        message = f"Passed: All {len(holes_data)} holes are properly aligned across {len(rows)} horizontal rows."
    else:
        message = f"Failed: Found {misaligned_holes_count} unaligned orphan hole(s) that do not match any horizontal row!"

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "rows": rows
    }

#RULE 3
def check_custom_holes(elements):
    """
    Geometrically analyzes 3D meshes to find custom service holes.
    Instead of checking for horizontal alignment, it simply returns their locations
    as a warning for the user.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    holes_data = []
    warning_elements = [] 

    # 1. GEOMETRIC MESH SCANNING
    for element in elements:
        try:
            # Generate the raw geometry
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            # Convert to PyVista PolyData format
            faces = shape.geometry.faces
            num_triangles = len(faces) // 3
            pv_faces = np.empty((num_triangles, 4), dtype=int)
            pv_faces[:, 0] = 3
            pv_faces[:, 1:] = np.array(faces).reshape((-1, 3))
            
            mesh = pv.PolyData(verts, pv_faces.flatten())
            
            # Extract sharp corners/edges (Holes create sharp edges through the web)
            edges = mesh.extract_feature_edges(feature_angle=45)
            
            if edges.n_points == 0:
                continue

            # Get the Z coordinates of all sharp edges
            z_coords = edges.points[:, 2]
            
            stud_min_z = z_coords.min()
            stud_max_z = z_coords.max()
            
            # Filter out the top and bottom cuts (leaving a 50mm / 0.05m buffer)
            buffer = 0.05 
            internal_z = z_coords[(z_coords > stud_min_z + buffer) & (z_coords < stud_max_z - buffer)]
            
            if len(internal_z) == 0:
                continue
                
            # Cluster the remaining Z coordinates to find individual holes
            internal_z.sort()
            current_hole_cluster = [internal_z[0]]
            
            for z in internal_z[1:]:
                # If the next edge point is within 100mm, it belongs to the same hole
                if z - current_hole_cluster[-1] < 0.10: 
                    current_hole_cluster.append(z)
                else:
                    # Gap is larger than 100mm, new hole found!
                    center_z = np.mean(current_hole_cluster)
                    holes_data.append({"element": element, "z_height": center_z})
                    if element not in warning_elements: warning_elements.append(element)
                    
                    current_hole_cluster = [z] # Reset for next hole
            
            # Append the very last hole found in this stud
            holes_data.append({"element": element, "z_height": np.mean(current_hole_cluster)})
            if element not in warning_elements: warning_elements.append(element)

        except Exception:
            pass

    # 2. FORMATTING THE WARNING REPORT
    if len(holes_data) == 0:
        return {
            "has_holes": False,
            "message": "No internal custom holes detected.",
            "warning_elements": []
        }

    message = f"Found {len(holes_data)} custom hole(s) spread across {len(warning_elements)} stud(s)."
    
    return {
        "has_holes": True,
        "message": message,
        "warning_elements": warning_elements,
        "holes_data": holes_data
    }

#RULE 4
def check_track_continuity(elements, tolerance_m=0.02):
    """
    Checks if the primary Top and Bottom tracks are continuous.
    Identifies tracks geometrically, ignores noggings/bridging, and ensures 
    the tracks span the full horizontal length of the panel.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    violating_elements = []
    element_bounds = []
    
    global_min_x = float('inf')
    global_max_x = float('-inf')
    global_min_z = float('inf')
    global_max_z = float('-inf')

    # 1. SCAN THE ENTIRE PANEL AND SAVE BOUNDARIES
    for element in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            min_c = verts.min(axis=0)
            max_c = verts.max(axis=0)
            
            # Update global boundaries
            if min_c[0] < global_min_x: global_min_x = min_c[0]
            if max_c[0] > global_max_x: global_max_x = max_c[0]
            if min_c[2] < global_min_z: global_min_z = min_c[2]
            if max_c[2] > global_max_z: global_max_z = max_c[2]
            
            # Save the local boundaries of this specific piece of steel
            element_bounds.append({
                "element": element,
                "min_x": min_c[0], "max_x": max_c[0],
                "min_z": min_c[2], "max_z": max_c[2],
                "dx": max_c[0] - min_c[0], # Length
                "dz": max_c[2] - min_c[2]  # Height
            })
        except Exception:
            pass

    panel_length = global_max_x - global_min_x
    
    if len(element_bounds) == 0:
        return {"passed": True, "message": "No valid geometry found.", "violating_elements": []}

    # 2. FILTER AND CHECK THE TRACKS
    passed = True
    tracks_found = 0
    splices_found = 0

    for item in element_bounds:
        # Check if it's horizontal steel (Length is significantly greater than Height)
        if item["dx"] > item["dz"]:
            
            # Is it a Top Track or Bottom Track? (Within 20mm of the absolute top/bottom)
            is_bottom_track = abs(item["min_z"] - global_min_z) <= tolerance_m
            is_top_track = abs(item["max_z"] - global_max_z) <= tolerance_m
            
            if is_bottom_track or is_top_track:
                tracks_found += 1
                
                # The Rule: Does this specific track span the whole panel?
                if item["dx"] < (panel_length - tolerance_m):
                    passed = False
                    splices_found += 1
                    if item["element"] not in violating_elements:
                        violating_elements.append(item["element"])

    # 3. FORMAT THE REPORT
    if tracks_found == 0:
        return {
            "passed": True,  # Keep true so it doesn't paint the whole panel red
            "has_tracks": False, # New flag to trigger the UI warning
            "message": "Could not identify any boundary tracks. Tolerance may be too tight.",
            "violating_elements": violating_elements
        }
        
    if passed:
        message = f"Passed: All {tracks_found} boundary tracks are continuous."
    else:
        message = f"Failed: Found {splices_found} spliced/broken tracks! Tracks must be continuous."

    return {
        "passed": passed,
        "has_tracks": True,
        "message": message,
        "violating_elements": violating_elements
    }

#RULE 5
def check_track_hole_alignment(elements, tolerance_m=0.02):
    """
    Checks if standard service holes in horizontal tracks are vertically aligned.
    Filters out single holes located in the bottom track (assumes they are anchor bolt holes).
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    holes_data = []
    violating_elements = []
    
    global_min_z = float('inf')

    # 1. FIND TRACKS, PANEL BOTTOM, AND HOLE COORDINATES
    for element in elements:
        try:
            # Generate geometry to get boundaries and find the absolute bottom of the panel
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            min_c = verts.min(axis=0)
            max_c = verts.max(axis=0)
            
            if min_c[2] < global_min_z: 
                global_min_z = min_c[2]
            
            dx = max_c[0] - min_c[0] # Length
            dz = max_c[2] - min_c[2] # Height

            # Filter: If Length > Height, it is horizontal steel
            if dx > dz: 
                if hasattr(element, 'HasOpenings'):
                    for rel in element.HasOpenings:
                        if rel.is_a("IfcRelVoidsElement"):
                            opening = rel.RelatedOpeningElement
                            
                            try:
                                # Get the 3D center of the hole
                                o_shape = ifcopenshell.geom.create_shape(settings, opening)
                                o_verts = np.array(o_shape.geometry.verts).reshape((-1, 3))
                                
                                center_x = o_verts[:, 0].mean() 
                                center_z = o_verts[:, 2].mean() # Grab Z-height to check for anchors

                                holes_data.append({
                                    "host_element": element,
                                    "opening_id": opening.GlobalId,
                                    "x_pos": center_x,
                                    "z_pos": center_z
                                })
                            except Exception:
                                # Fallback to raw text coordinates
                                try:
                                    placement = opening.ObjectPlacement.RelativePlacement.Location.Coordinates
                                    holes_data.append({
                                        "host_element": element,
                                        "opening_id": opening.GlobalId,
                                        "x_pos": placement[0],
                                        "z_pos": placement[2]
                                    })
                                except Exception: 
                                    pass
        except Exception:
            pass

    if len(holes_data) == 0:
        return {"passed": True, "message": "No standard service holes found in tracks.", "violating_elements": []}

    # 2. GROUP HOLES INTO VERTICAL "COLUMNS"
    columns = []
    for hole in holes_data:
        matched_col = False
        for col in columns:
            if abs(hole["x_pos"] - col[0]["x_pos"]) <= tolerance_m:
                col.append(hole)
                matched_col = True
                break
        
        if not matched_col:
            columns.append([hole])

    # 3. DETECT ORPHANS AND FILTER ANCHORS
    passed = True
    misaligned_holes_count = 0
    anchor_holes_count = 0

    for col in columns:
        if len(col) < 2:
            # We found a single hole. Is it an anchor bolt at the bottom?
            # We add a 50mm (0.05m) buffer to account for the track's physical thickness
            single_hole = col[0]
            if single_hole["z_pos"] <= (global_min_z + 0.05):
                anchor_holes_count += 1
            else:
                # It's a single hole floating somewhere else. This is a real error!
                passed = False
                misaligned_holes_count += 1
                if single_hole["host_element"] not in violating_elements:
                    violating_elements.append(single_hole["host_element"])

    # 4. FORMAT THE REPORT
    if passed:
        message = f"Passed: {len(holes_data)} track holes processed. Found {len(columns) - anchor_holes_count} plumb drops and {anchor_holes_count} bottom anchor holes."
    else:
        message = f"Failed: Found {misaligned_holes_count} unaligned orphan hole(s) in the tracks! (Ignored {anchor_holes_count} bottom anchors)."

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "columns": columns
    }

# Rule 6: Check for max individual element weight. 
def check_max_weight(elements, max_weight_kg=50.0, density_kg_m3=7850):
    """
    Calculates the mass of each steel element (Volume * Density).
    Checks IFC Property Sets first, then falls back to PyVista geometric volume.
    Fails any element that exceeds the manual lifting limit.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    violating_elements = []
    weight_data = []

    for element in elements:
        vol_m3 = None
        
        # --- PATH A: Try to find "Smart Data" (IFC Quantities) ---
        try:
            psets = ifcopenshell.util.element.get_psets(element)
            # Look in standard Quantity Take-Off (QTO) sets
            if "BaseQuantities" in psets and "NetVolume" in psets["BaseQuantities"]:
                vol_m3 = psets["BaseQuantities"]["NetVolume"]
            elif "Qto_WallBaseQuantities" in psets and "NetVolume" in psets["Qto_WallBaseQuantities"]:
                vol_m3 = psets["Qto_WallBaseQuantities"]["NetVolume"]
        except Exception:
            pass

        # --- PATH B: Fallback to "Dumb Geometry" (PyVista) ---
        if vol_m3 is None:
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
                verts = np.array(shape.geometry.verts).reshape((-1, 3))
                faces = shape.geometry.faces
                
                num_triangles = len(faces) // 3
                pv_faces = np.empty((num_triangles, 4), dtype=int)
                pv_faces[:, 0] = 3
                pv_faces[:, 1:] = np.array(faces).reshape((-1, 3))
                
                # Create a cleaned, closed mesh and calculate its spatial volume
                mesh = pv.PolyData(verts, pv_faces.flatten()).clean()
                vol_m3 = mesh.volume
            except Exception:
                pass

        # --- CALCULATE MASS ---
        if vol_m3 is not None:
            mass_kg = vol_m3 * density_kg_m3
            weight_data.append({"element": element, "mass_kg": mass_kg})
            
            if mass_kg > max_weight_kg:
                if element not in violating_elements:
                    violating_elements.append(element)

    # FORMAT THE REPORT
    if len(weight_data) == 0:
        return {"passed": True, "message": "Could not calculate volume for any elements.", "violating_elements": []}

    # Find the heaviest piece for the report
    heaviest_piece = max(weight_data, key=lambda x: x["mass_kg"])
    max_mass = heaviest_piece["mass_kg"]

    if len(violating_elements) == 0:
        message = f"Passed: Heaviest piece is {max_mass:.1f} kg (Limit: {max_weight_kg} kg)."
        passed = True
    else:
        message = f"Failed: Found {len(violating_elements)} oversized piece(s)! Heaviest is {max_mass:.1f} kg."
        passed = False

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements
    }

def check_hole_sizes(elements, allowed_sizes_m=[0.014, 0.034], tolerance_m=0.002):
    """
    Measures the diameter of every standard service hole.
    Returns pass/fail status, table data, and 3D coords ONLY for violating holes.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    violating_elements = []
    hole_details = [] 
    violating_hole_coords = [] # NEW: Only tracks coordinates for holes that FAIL
    invalid_holes_count = 0
    total_holes = 0

    # --- BULLETPROOF UI PARSING ---
    if isinstance(allowed_sizes_m, str):
        try:
            allowed_sizes_m = [float(x.strip()) for x in allowed_sizes_m.split(",")]
        except ValueError:
            allowed_sizes_m = [0.034] 
    elif not isinstance(allowed_sizes_m, list):
        allowed_sizes_m = [float(allowed_sizes_m)]

    for element in elements:
        try:
            if hasattr(element, 'HasOpenings'):
                for rel in element.HasOpenings:
                    if rel.is_a("IfcRelVoidsElement"):
                        opening = rel.RelatedOpeningElement
                        
                        hole_diameter = None
                        geom_diameter = None
                        center_point = None 
                        
                        # --- STEP 1: Attempt 3D Geometry ---
                        try:
                            o_shape = ifcopenshell.geom.create_shape(settings, opening)
                            o_verts = np.array(o_shape.geometry.verts).reshape((-1, 3))
                            min_c = o_verts.min(axis=0)
                            max_c = o_verts.max(axis=0)
                            
                            center_point = (max_c + min_c) / 2.0 # Grab the 3D center
                            geom_diameter = np.sort(max_c - min_c)[1]
                        except Exception:
                            pass 
                        
                        # --- STEP 1.5: Fallback Location for Ghost Holes ---
                        if center_point is None:
                            try:
                                placement = opening.ObjectPlacement.RelativePlacement.Location.Coordinates
                                center_point = (placement[0], placement[1], placement[2])
                            except Exception:
                                pass

                        # --- STEP 2: Attempt Smart Data ---
                        try:
                            if hasattr(opening, 'Representation') and opening.Representation:
                                for rep in opening.Representation.Representations:
                                    for item in rep.Items:
                                        if item.is_a("IfcExtrudedAreaSolid"):
                                            profile = item.SweptArea
                                            raw_dim = None
                                            if profile.is_a("IfcCircleProfileDef"):
                                                raw_dim = profile.Radius * 2
                                            elif profile.is_a("IfcRectangleProfileDef"):
                                                raw_dim = profile.XDim
                        except Exception:
                            pass
                        
                        # --- STEP 3: Resolve & Evaluate ---
                        if hole_diameter is None:
                            hole_diameter = geom_diameter
                                
                        if hole_diameter is not None:
                            total_holes += 1
                            
                            is_valid = False
                            for allowed in allowed_sizes_m:
                                if abs(hole_diameter - allowed) <= tolerance_m:
                                    is_valid = True
                                    break
                                    
                            # --- THE FIX: ONLY TRACK IF IT FAILS ---
                            if not is_valid:
                                invalid_holes_count += 1
                                if element not in violating_elements:
                                    violating_elements.append(element)
                                    
                                # Save the location of this specific BAD hole
                                if center_point is not None:
                                    violating_hole_coords.append(center_point)

                            # --- RECORD THE DATA ---
                            hole_details.append({
                                "Host Type": "Track" if "Track" in element.Name else "Stud", 
                                "Element ID": element.GlobalId,
                                "Diameter (mm)": round(hole_diameter * 1000, 2), 
                                "Status": "✅ Pass" if is_valid else "❌ Fail"
                            })
                                    
        except Exception:
            pass

    passed = (invalid_holes_count == 0)
    
    if passed:
        message = f"Passed: All {total_holes} holes perfectly match allowed sizes."
    else:
        message = f"Failed: Found {invalid_holes_count} out of {total_holes} hole(s) with non-standard dimensions!"

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "hole_details": hole_details, 
        "violating_hole_coords": violating_hole_coords # Return ONLY the bad ones
    }