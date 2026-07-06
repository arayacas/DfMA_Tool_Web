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
        message = f"Panel exceeds limits! Actual: {actual_length:.1f}mm L x {actual_height:.1f}mm H. (Limits: {max_length_mm}mm x {max_height_mm}mm). This panel might be too big for your current work station, consider spliting the panel in smaller parts or assemble a smaller panel instead."
        
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
        message = f"Failed: Found {misaligned_holes_count} unaligned orphan hole(s) that do not match any horizontal row. Make sure that any holes in the panel are well aligned in Revit or equivalent software. Otherwise, mark the violating element as a CustomHole to override this violation (a warning will be displayed instead)."

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

    message = f"Found {len(holes_data)} custom hole(s) spread across {len(warning_elements)} stud(s). These holes are not being tracked by the tool, make sure they are correctly aligned and in correct position"
    
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
    Now exports table data for Numerical Data debugging.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    violating_elements = []
    element_bounds = []
    track_details = [] # NEW: List to hold our table data
    
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
        return {"passed": True, "message": "No valid geometry found.", "violating_elements": [], "track_details": []}

    # 2. FILTER AND CHECK THE TRACKS
    passed = True
    tracks_found = 0
    splices_found = 0

    for item in element_bounds:
        # Check if it's horizontal steel (Length is significantly greater than Height)
        if item["dx"] > item["dz"]:
            
            # Is it a Top Track or Bottom Track? (Within tolerance of the absolute top/bottom)
            is_bottom_track = abs(item["min_z"] - global_min_z) <= tolerance_m
            is_top_track = abs(item["max_z"] - global_max_z) <= tolerance_m
            
            if is_bottom_track or is_top_track:
                tracks_found += 1
                
                # The Rule: Does this specific track span the whole panel?
                is_valid = item["dx"] >= (panel_length - tolerance_m)
                
                if not is_valid:
                    passed = False
                    splices_found += 1
                    if item["element"] not in violating_elements:
                        violating_elements.append(item["element"])

                # --- RECORD RAW DATA FOR THE TABLE ---
                position_label = "Top Track" if is_top_track else "Bottom Track"
                track_details.append({
                    "Position": position_label,
                    "Element ID": item["element"].GlobalId,
                    "Actual Track Length": round(item["dx"], 3),
                    "Full Panel Length": round(panel_length, 3),
                    "Gap Deficit": round(panel_length - item["dx"], 3),
                    "Status": "✅ Pass" if is_valid else "❌ Fail"
                })

    # 3. FORMAT THE REPORT
    if tracks_found == 0:
        return {
            "passed": True,  # Keep true so it doesn't paint the whole panel red
            "has_tracks": False, # New flag to trigger the UI warning
            "message": "Could not identify any boundary tracks. Tolerance may be too tight.",
            "violating_elements": violating_elements,
            "track_details": track_details
        }
        
    if passed:
        message = f"Passed: All {tracks_found} boundary tracks are continuous."
    else:
        message = f"Failed: Found {splices_found} spliced/broken tracks! Tracks must be continuous. If you consider this is a mistake, increase the Track Continuity (m) parameter in Design Parameters to a desired length."

    return {
        "passed": passed,
        "has_tracks": True,
        "message": message,
        "violating_elements": violating_elements,
        "track_details": track_details # Export the table!
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
        message = f"Failed: Found {misaligned_holes_count} unaligned orphan hole(s) in the tracks! (Ignored {anchor_holes_count} bottom anchors). You can mark the violating element as a CustomHole to override this violation (a warning will be displayed instead). "

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
        message = f"Failed: Found {len(violating_elements)} oversized piece(s)! Heaviest is {max_mass:.1f} kg. Your parts are too heavy for your robot to carry, consider using shorter parts or spiting a member into smaller members for assembly (increases number of parts)."
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
        message = f"Failed: Found {invalid_holes_count} out of {total_holes} hole(s) with non-standard dimensions. Make sure you have correctly entered your expected hole sizes and tolerance in the hole size design parameters. If you think this is a mistake, you can mark the hole member as a CustomHole to stop tracking it (A warning will be displayed instead)."

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "hole_details": hole_details, 
        "violating_hole_coords": violating_hole_coords # Return ONLY the bad ones
    }

def check_part_count(elements, max_parts=50):
    """Rule 12: Part Count Complexity"""
    count = len(elements)
    passed = count <= max_parts
    
    if passed:
        message = f"Passed: Panel contains {count} total structural parts. (Limit: {max_parts})"
    else:
        message = f"Failed: Panel is too complex! Contains {count} parts. (Limit: {max_parts}). Consider reducing the number of parts by making a simpler panel, spliting the panel or incresing the number of parts your robot can process in the Design Parameters page"
        
    return {
        "passed": passed,
        "message": message,
        "violating_elements": [] if passed else elements # Flags whole panel if too complex
    }

def check_stud_spacing(elements, target_spacings_mms="600, 100", tolerance_mm=10.0):
    """
    Rule 3 (DfRA): Standardized Stud Spacing.
    Checks spacing against MULTIPLE allowed target gaps (e.g. standard 600mm and junction 100mm).
    Dynamically adjusts to the IFC file's native length units.
    """
    if not elements:
        return {"passed": True, "message": "No elements provided.", "violating_elements": [], "spacing_details": []}

    # --- 1. STRING PARSER (Like the Holes Rule) ---
    if isinstance(target_spacings_mms, str):
        try:
            allowed_spacings = [float(x.strip()) for x in target_spacings_mms.split(",")]
        except ValueError:
            allowed_spacings = [600.0] 
    elif not isinstance(target_spacings_mms, list):
        allowed_spacings = [float(target_spacings_mms)]
    else:
        allowed_spacings = target_spacings_mms

    # --- 2. DYNAMIC UNIT CONVERSION ---
    try:
        model = elements[0].file
        length_unit = [u for u in model.by_type("IfcUnitAssignment")[0].Units if u.is_a("IfcSIUnit") and u.UnitType == "LENGTHUNIT"][0]
        if length_unit.Prefix == "MILLI": to_mm_factor = 1.0
        elif length_unit.Prefix == "CENTI": to_mm_factor = 10.0
        else: to_mm_factor = 1000.0
    except Exception:
        to_mm_factor = 1000.0

    # --- 3. FILTER & MEASURE ---
    studs = [e for e in elements if e.Name and "stud" in e.Name.lower()]
    stud_data = []
    
    for s in studs:
        try:
            raw_x = s.ObjectPlacement.RelativePlacement.Location.Coordinates[0]
            x_coord_mm = raw_x * to_mm_factor
            stud_data.append((x_coord_mm, s))
        except Exception:
            continue
            
    stud_data.sort(key=lambda x: x[0])
    
    violating_elements = []
    spacing_details = [] 
    checked_count = len(stud_data)
    
    if checked_count < 2:
        return {"passed": True, "message": f"Warning: Only {checked_count} stud(s) found.", "violating_elements": [], "spacing_details": []}
    
    # --- 4. MULTI-TARGET EVALUATION ---
    for i in range(len(stud_data) - 1):
        x1 = stud_data[i][0]
        x2 = stud_data[i+1][0]
        actual_spacing = abs(x2 - x1)
        
        is_valid = False
        matched_target = None
        
        # Check against every allowed size in the list
        for target in allowed_spacings:
            if abs(actual_spacing - target) <= tolerance_mm:
                is_valid = True
                matched_target = target
                break
        
        if not is_valid:
            violating_elements.append(stud_data[i][1])
            violating_elements.append(stud_data[i+1][1])
            
        spacing_details.append({
            "Left Stud ID": stud_data[i][1].GlobalId,
            "Right Stud ID": stud_data[i+1][1].GlobalId,
            "Actual Gap (mm)": round(actual_spacing, 2),
            "Target Gap (mm)": matched_target if is_valid else str(allowed_spacings),
            "Status": "✅ Pass" if is_valid else "❌ Fail"
        })
            
    violators_unique = list(set(violating_elements))
    passed = len(violators_unique) == 0
    
    message = f"Passed: All {checked_count} studs match allowed spacing gaps." if passed else f"Failed: Irregular gaps found between {len(violators_unique)} studs!. Make sure you have entered the correct stud spacing and tolerance in the design paramaters section. Otherwise this panel has irregular spacing between studs, consider checking your panel in Revit or Equivalent Software. If you think this is a mistake, give the Stud tolerance any negative value to override this constraint."
        
    return {
        "passed": passed,
        "message": message,
        "violating_elements": violators_unique,
        "spacing_details": spacing_details
    }
def check_joist_uniformity(elements, tolerance_mm=5.0):
    """
    Rule 6 (DfM): Uniform Joist Depth
    Extracts the 3D bounding box of horizontal members and exports the depths to a table.
    """
    tracks = [e for e in elements if e.Name and any(word in e.Name.lower() for word in ["track", "joist", "plate"])]
    count = len(tracks)
    
    if count == 0:
        return {"passed": True, "message": "No horizontal tracks found to check.", "violating_elements": [], "joist_details": []}
        
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    track_depths = []
    
    for t in tracks:
        try:
            shape = ifcopenshell.geom.create_shape(settings, t)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            min_c = verts.min(axis=0)
            max_c = verts.max(axis=0)
            dims = (max_c - min_c) * 1000.0 
            
            dims_sorted = np.sort(dims) 
            depth_mm = dims_sorted[1] 
            
            track_depths.append((depth_mm, t))
        except Exception:
            pass
            
    if not track_depths:
        return {"passed": True, "message": f"Could not calculate geometry for the {count} tracks.", "violating_elements": [], "joist_details": []}
        
    depths_only = [d[0] for d in track_depths]
    baseline_depth = np.median(depths_only) 
    
    violating_elements = []
    joist_details = [] # NEW: Table Data
    
    for depth, t in track_depths:
        is_valid = abs(depth - baseline_depth) <= tolerance_mm
        if not is_valid:
            violating_elements.append(t)
            
        # RECORD RAW DATA FOR THE TABLE
        joist_details.append({
            "Element ID": t.GlobalId,
            "Type": "Track/Joist",
            "Actual Depth (mm)": round(depth, 2),
            "Median Panel Depth (mm)": round(baseline_depth, 2),
            "Variance (mm)": round(abs(depth - baseline_depth), 2),
            "Status": "✅ Pass" if is_valid else "❌ Fail"
        })
            
    passed = len(violating_elements) == 0
    message = f"Passed: All {count} horizontal tracks have a uniform depth of ~{baseline_depth:.1f}mm." if passed else f"Failed: {len(violating_elements)} out of {count} tracks do not match the standard depth of {baseline_depth:.1f}mm!. Your panel depth seems to be disaligned, you can increase the tolerance for joist depth in the design parameters. Otherwise, check your panel in Revit or Equivalent Software for misaligned beam depth."
        
    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "joist_details": joist_details
    }

def check_part_max_dimensions(elements, max_length_mm=1000.0, max_height_mm=1000.0, max_depth_mm=300.0):
    """
    Rule X (DfMA): Maximum Individual Part Size
    Checks every single element to ensure it does not exceed the robot's maximum 
    handling dimensions (Length, Height, or Depth).
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    violating_elements = []
    part_details = [] # NEW: List to hold our table data
    total_parts_checked = 0
    
    for element in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            # Find the local bounding box of this specific part
            min_c = verts.min(axis=0)
            max_c = verts.max(axis=0)
            
            # Calculate dimensions in mm
            dims = (max_c - min_c) * 1000.0 
            
            # Sort dimensions from smallest to largest to find depth, height, and length
            dims_sorted = np.sort(dims)
            actual_depth = dims_sorted[0]
            actual_height = dims_sorted[1]
            actual_length = dims_sorted[2]
            
            total_parts_checked += 1
            
            # Check against limits
            is_valid = True
            if (actual_length > max_length_mm or 
                actual_height > max_height_mm or 
                actual_depth > max_depth_mm):
                is_valid = False
                violating_elements.append(element)
                
            # --- RECORD THE RAW DATA FOR THE TABLE ---
            part_type = "Track" if element.Name and "track" in element.Name.lower() else "Stud"
            
            part_details.append({
                "Type": part_type,
                "Element ID": element.GlobalId,
                "Length (mm)": round(actual_length, 2),
                "Height (mm)": round(actual_height, 2),
                "Depth (mm)": round(actual_depth, 2),
                "Status": "✅ Pass" if is_valid else "❌ Fail"
            })
                
        except Exception:
            pass # Skip parts that don't have physical 3D geometry

    passed = len(violating_elements) == 0
    
    if passed:
        message = f"Passed: All {total_parts_checked} individual parts fit within robotic gripper limits."
    else:
        message = f"Failed: {len(violating_elements)} out of {total_parts_checked} parts exceed maximum handling dimensions! Your current robot configuration seems to be unable to handle the highlighted elements (red). Consider using smaller individual elements on your panel instead or increase the dimensional capacity in the Design Parameters page."
        
    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "part_details": part_details # We export the table here!
    }

def check_center_of_gravity(elements, tolerance_mm=250.0):
    """
    Rule X (DfMA): Center of Gravity Balance
    Estimates the CoG using a volume-weighted average of all parts.
    Fails if the CoG is too far from the geometric center of the panel.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    global_min = np.array([float('inf'), float('inf'), float('inf')])
    global_max = np.array([float('-inf'), float('-inf'), float('-inf')])
    
    total_volume = 0.0
    weighted_sum = np.zeros(3)
    
    # 1. SCAN PARTS FOR VOLUME AND LOCAL CENTERS
    for e in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, e)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))
            
            min_c = verts.min(axis=0)
            max_c = verts.max(axis=0)
            
            # Expand global panel boundaries
            global_min = np.minimum(global_min, min_c)
            global_max = np.maximum(global_max, max_c)
            
            # Calculate element volume (dx * dy * dz)
            dims = max_c - min_c
            vol = dims[0] * dims[1] * dims[2]
            
            # Local center of this specific part
            center = (max_c + min_c) / 2.0
            
            total_volume += vol
            weighted_sum += center * vol
            
        except Exception:
            pass

    if total_volume == 0:
        return {"passed": True, "message": "Could not extract geometry for CoG.", "violating_elements": [], "cog_details": []}

    # 2. CALCULATE OFFSETS
    cog_m = weighted_sum / total_volume
    geom_center_m = (global_max + global_min) / 2.0
    
    # Euclidean distance between true center and CoG (converted to mm)
    offset_m = np.linalg.norm(cog_m - geom_center_m)
    offset_mm = offset_m * 1000.0
    
    passed = offset_mm <= tolerance_mm
    
    if passed:
        message = f"Passed: Panel is balanced. CoG offset is only {offset_mm:.1f}mm."
    else:
        message = f"Failed: Unbalanced Panel! CoG is offset by {offset_mm:.1f}mm (Limit: {tolerance_mm}mm). Assembling this panel might result in tilting/tipping during the assembly process. Consider making this panel more simetrical in the x-y-z plane on Revit or Equivalent Software. If you think this is a mistake, you can increase the Center of Gravity tolerance spherical radius in the Design Parameters Page."
        
    # 3. RECORD TABLE DATA
    cog_details = [
        {"Metric": "Geometric Center (X,Y,Z)", "Value": f"{geom_center_m[0]:.2f}, {geom_center_m[1]:.2f}, {geom_center_m[2]:.2f}"},
        {"Metric": "Estimated CoG (X,Y,Z)", "Value": f"{cog_m[0]:.2f}, {cog_m[1]:.2f}, {cog_m[2]:.2f}"},
        {"Metric": "Offset Distance (mm)", "Value": str(round(offset_mm, 2))},
        {"Metric": "Tolerance Limit (mm)", "Value": str(tolerance_mm)},
        {"Metric": "Status", "Value": "✅ Pass" if passed else "❌ Fail"}
    ]

    return {
        "passed": passed,
        "message": message,
        # If it fails, the WHOLE panel is unsafe to lift, so we flag all elements
        "violating_elements": elements if not passed else [], 
        "cog_coords": cog_m.tolist(),       # We return these to draw a cool 3D widget!
        "geom_coords": geom_center_m.tolist(),
        "cog_details": cog_details
    }

def check_slanted_beam_angle(elements, max_angle_degrees=45.0, tolerance=2.0):
    """
    Rule X (DfM): Slanted Beam Angle (Roof Panels).
    Identifies slanted structural members and ensures their pitch/angle
    does not exceed the robotic assembly limit (default 45 degrees).
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    violating_elements = []
    angle_details = []
    slanted_beams_found = 0

    for element in elements:
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = np.array(shape.geometry.verts).reshape((-1, 3))

            if len(verts) < 2:
                continue

            # --- FAST VECTOR APPROXIMATION ---
            # Find the two furthest points in the mesh to get the longitudinal axis
            dist_from_0 = np.linalg.norm(verts - verts[0], axis=1)
            idx_A = np.argmax(dist_from_0)
            A = verts[idx_A]

            dist_from_A = np.linalg.norm(verts - A, axis=1)
            idx_B = np.argmax(dist_from_A)
            B = verts[idx_B]

            vector = B - A
            length = np.linalg.norm(vector)

            if length == 0:
                continue

            # --- CALCULATE THE ANGLE ---
            # Angle relative to the horizontal (XY plane)
            dz = abs(vector[2])
            angle_rad = np.arcsin(dz / length)
            angle_deg = np.degrees(angle_rad)

            # --- FILTER & EVALUATE ---
            # We only care about slanted members (ignoring flat tracks <5° and vertical studs >85°)
            if 5.0 < angle_deg < 85.0:
                slanted_beams_found += 1

                # Check if it exceeds our robot's maximum pitch capability
                is_valid = angle_deg <= (max_angle_degrees + tolerance)

                if not is_valid:
                    violating_elements.append(element)

                # Record data for the Numerical Data table
                angle_details.append({
                    "Element ID": element.GlobalId,
                    "Type": element.Name if element.Name else "Beam",
                    "Calculated Pitch (°)": round(angle_deg, 1),
                    "Maximum Allowed (°)": max_angle_degrees,
                    "Status": "✅ Pass" if is_valid else "❌ Fail"
                })

        except Exception:
            pass

    passed = len(violating_elements) == 0

    if slanted_beams_found == 0:
        return {
            "passed": True,
            "message": "No slanted beams detected (all parts are standard vertical/horizontal).",
            "violating_elements": [],
            "angle_details": []
        }

    if passed:
        message = f"Passed: All {slanted_beams_found} slanted beams are at or below {max_angle_degrees}°."
    else:
        message = f"Failed: {len(violating_elements)} out of {slanted_beams_found} slanted beams exceed the {max_angle_degrees}° limit!. The Panel's members are too slanted, this panel is not safe. Change the panel design on Revit or Equivalent Software."

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "angle_details": angle_details
    }

def check_total_assembly_payload(elements, max_payload_kg=100.0):
    """
    Rule X (DfMA): Total Assembly Payload
    Calculates the cumulative weight of the entire panel to ensure it does not 
    exceed the hoisting/crane limits.
    """
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    
    total_weight_kg = 0.0
    payload_details = []
    
    for e in elements:
        weight = 0.0
        found_weight = False
        
        # --- 1. SMART CHECK: Look for embedded IFC Properties ---
        try:
            psets = ifcopenshell.util.element.get_psets(e)
            for pset_name, pset_data in psets.items():
                if isinstance(pset_data, dict):
                    # Search for any property containing 'weight' or 'mass'
                    for key, val in pset_data.items():
                        if ('weight' in key.lower() or 'mass' in key.lower()) and isinstance(val, (int, float)):
                            weight = float(val)
                            found_weight = True
                            break
                if found_weight: break
        except Exception:
            pass
                
        # --- 2. FALLBACK: Linear Meter Estimation ---
        # If the architect didn't include weights, we estimate based on length
        if not found_weight:
            try:
                shape = ifcopenshell.geom.create_shape(settings, e)
                verts = np.array(shape.geometry.verts).reshape((-1, 3))
                
                min_c = verts.min(axis=0)
                max_c = verts.max(axis=0)
                
                # Find the longest dimension (the length of the stud/track) in meters
                length_m = np.max(max_c - min_c)
                
                # Standard LGS estimation: ~2.5 kg per linear meter of steel
                weight = length_m * 2.5 
            except Exception:
                weight = 0.0
                
        total_weight_kg += weight
        
        # Record the part for our data table
        payload_details.append({
            "Element ID": e.GlobalId,
            "Type": e.Name if e.Name else "Unknown",
            "Weight (kg)": round(weight, 2),
            "Calculation Method": "IFC Property" if found_weight else "Linear Estimate (2.5kg/m)"
        })
        
    passed = total_weight_kg <= max_payload_kg
    
    if passed:
        message = f"Passed: Total assembled panel weight is {total_weight_kg:.1f} kg. (Safe limit: {max_payload_kg} kg)."
    else:
        message = f"Failed: Panel is too heavy to hoist safely! Total weight is {total_weight_kg:.1f} kg. (Limit: {max_payload_kg} kg). Consider using less elements/parts to relieve the Panel's weight. Otherwise, make a smaller panel by divding your panel in smaller assembly sequences by using Revit or Equivalent Software."
        
    return {
        "passed": passed,
        "message": message,
        "violating_elements": elements if not passed else [], # If it fails, the WHOLE panel paints red
        "payload_details": payload_details,
        "total_weight": total_weight_kg
    }

def check_hole_border_clearance(elements, min_clearance_mm=20.0):
    """
    Rule X (DfRA): Hole Border Clearance
    Measures 2D radial clearance using purely LOCAL coordinates to avoid 
    rotation bounding-box bloat.
    """
    # 1. LOCAL settings for accurate physical dimensions (ignoring rotation)
    settings_local = ifcopenshell.geom.settings()
    settings_local.set(settings_local.USE_WORLD_COORDS, False)
    
    # 2. GLOBAL settings just so we can draw the red sphere in the right 3D spot
    settings_global = ifcopenshell.geom.settings()
    settings_global.set(settings_global.USE_WORLD_COORDS, True)

    violating_elements = []
    clearance_details = []
    violating_hole_coords = []
    
    total_holes_checked = 0
    failed_holes = 0

    # FORCE the multiplier to 1000 because ifcopenshell.geom ALWAYS outputs meters
    to_mm_factor = 1000.0 

    for element in elements:
        if not hasattr(element, 'HasOpenings') or not element.HasOpenings:
            continue

        try:
            # --- GET EXACT LOCAL DIMENSIONS ---
            el_shape_l = ifcopenshell.geom.create_shape(settings_local, element)
            el_verts_l = np.array(el_shape_l.geometry.verts).reshape((-1, 3))
            
            dims_l = (el_verts_l.max(axis=0) - el_verts_l.min(axis=0)) * to_mm_factor
            
            # Sorted: [0]=Flange Depth, [1]=Web Width, [2]=Total Length
            dims_sorted = np.sort(dims_l)
            web_width_mm = dims_sorted[1] 

            # --- ANALYZE HOLES ---
            for rel in element.HasOpenings:
                if rel.is_a("IfcRelVoidsElement"):
                    opening = rel.RelatedOpeningElement

                    # Local Geometry for the exact radius
                    o_shape_l = ifcopenshell.geom.create_shape(settings_local, opening)
                    o_verts_l = np.array(o_shape_l.geometry.verts).reshape((-1, 3))
                    o_dims_l = (o_verts_l.max(axis=0) - o_verts_l.min(axis=0)) * to_mm_factor
                    
                    # A cylinder's sorted dims: [thickness, diameter, diameter]
                    # We grab index 1 to ensure we get the diameter, not the web thickness
                    hole_diameter_mm = np.sort(o_dims_l)[1]
                    hole_radius_mm = hole_diameter_mm / 2.0 
                    
                    # --- THE FILTER: Ignore giant slicing voids & hollow cores ---
                    if hole_radius_mm > 100.0 or hole_radius_mm < 1.0:
                        continue
                        
                    total_holes_checked += 1

                    # The math: assuming the hole is punched in the center of the web
                    actual_clearance_mm = (web_width_mm / 2.0) - hole_radius_mm
                    is_valid = actual_clearance_mm >= min_clearance_mm

                    if not is_valid:
                        failed_holes += 1
                        if element not in violating_elements:
                            violating_elements.append(element)
                        
                        # Grab global coordinates so the 3D viewer knows where to paint the sphere
                        o_shape_g = ifcopenshell.geom.create_shape(settings_global, opening)
                        o_verts_g = np.array(o_shape_g.geometry.verts).reshape((-1, 3))
                        center_point = (o_verts_g.max(axis=0) + o_verts_g.min(axis=0)) / 2.0
                        violating_hole_coords.append(center_point.tolist())

                    clearance_details.append({
                        "Element ID": element.GlobalId,
                        "Host Type": "Track" if element.Name and "track" in element.Name.lower() else "Stud",
                        "Web Width (mm)": round(web_width_mm, 1),
                        "Hole Radius (mm)": round(hole_radius_mm, 1),
                        "Actual Edge Clearance (mm)": round(actual_clearance_mm, 1),
                        "Required Clearance (mm)": min_clearance_mm,
                        "Status": "✅ Pass" if is_valid else "❌ Fail"
                    })

        except Exception:
            pass

    if total_holes_checked == 0:
        return {"passed": True, "message": "No standard service holes found.", "violating_elements": [], "clearance_details": []}

    passed = failed_holes == 0
    if passed:
        message = f"Passed: All {total_holes_checked} holes have safe edge clearance (≥ {min_clearance_mm}mm)."
    else:
        message = f"Failed: {failed_holes} out of {total_holes_checked} holes are drilled too close to the steel edge!"

    return {
        "passed": passed,
        "message": message,
        "violating_elements": violating_elements,
        "violating_hole_coords": violating_hole_coords,
        "clearance_details": clearance_details
    }