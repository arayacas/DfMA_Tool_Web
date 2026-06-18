import ifcopenshell
import json
from datetime import datetime
from pathlib import Path

# 🔧 Set these before running:
# IFC_FILE: absolute or relative path to the IFC model you want to inspect.
# ENTITY_ID: the STEP line id to inspect. This can be:
#   - an IfcShapeRepresentation (we'll automatically descend into .Items)
#   - a BRep solid (IfcFacetedBrep / IfcAdvancedBrep)
#   - an IfcClosedShell (outer shell) or a single IfcFace
# OUT_DIR: a directory path where the script will write the text and (optional) JSON reports.
# WRITE_JSON: if True, an additional JSON file is written with structured output.
IFC_FILE   = r"C:/Users/devan/OneDrive/Desktop/Devansh Artwani/2025 Summer Term (Co-op)/LGS files/LGS_wall.ifc"
ENTITY_ID  = 6726   # Can be IfcShapeRepresentation, IfcFacetedBrep, IfcAdvancedBrep, IfcClosedShell, or IfcFace
OUT_DIR    = r"C:/Users/devan/OneDrive/Desktop/Devansh Artwani/2025 Summer Term (Co-op)/LGS files"  # directory only
WRITE_JSON = True

# Optional verbosity
# INCLUDE_POINTS: if True, lists the coordinates of polygon vertices for IfcPolyLoop.
# MAX_POINTS_TO_SHOW: cap the number of points printed per loop, to keep files readable on huge meshes.
INCLUDE_POINTS = True
MAX_POINTS_TO_SHOW = 200

def safe(obj, attr, default=None):
    """
    Safely access an IFC attribute by name.
    Many IFC entities across different schema versions may or may not implement a given attribute;
    this helper prevents AttributeError exceptions and returns a default instead.

    Example:
      safe(face_bound, "Orientation")  -> True/False or default
      safe(face, "Bounds")             -> list of IfcFaceBound / IfcFaceOuterBound or []
    """
    try:
        return getattr(obj, attr)
    except Exception:
        return default

def vec(obj):
    """
    Normalize an IFC geometric primitive into a simple Python list of floats.

    IFC often stores:
      - IfcCartesianPoint with .Coordinates (e.g., [x, y, z])
      - IfcDirection with .DirectionRatios (e.g., [dx, dy, dz])

    This function returns either .Coordinates or .DirectionRatios as a list,
    whichever exists on 'obj'. Returns None if neither exists.

    Used to extract readable coordinates/directions for reports.
    """
    if not obj: return None
    return list(getattr(obj, "Coordinates", None) or getattr(obj, "DirectionRatios", None) or [])

def pt(obj):
    """
    Convert the vector list from vec(obj) into a tuple (x, y, z) for stable, compact printing.
    Returns None if obj has neither Coordinates nor DirectionRatios.
    """
    v = vec(obj)
    return tuple(v) if v is not None else None

def is_brep_like(ent):
    """
    Heuristic: Determine if 'ent' looks like a BRep solid by checking for an Outermost shell attribute.
    IFC BRep solids (IfcFacetedBrep / IfcAdvancedBrep) expose:
      - .Outer   (IFC2x3 / IFC4)
      - or .OuterShell (variant naming in some contexts/tools)
    """
    return hasattr(ent, "Outer") or hasattr(ent, "OuterShell")

def get_shells(brep):
    """
    Extract outer and inner shells from a BRep solid.

    - 'Outer' / 'OuterShell' : the closed shell bounding the solid.
    - 'Inner' / 'InnerShells': optional list of internal void shells (holes/cavities).
    Returns a pair: (outer_shell, [inner_shell_1, inner_shell_2, ...])
    """
    outer = safe(brep, "Outer") or safe(brep, "OuterShell")
    inner = safe(brep, "Inner") or safe(brep, "InnerShells") or []
    return outer, list(inner) if inner else []

def face_bounds(face):
    """
    Split a face's bounds into 'outer' and 'inner' lists.

    IFC Face topology:
      - face.Bounds -> list of IfcFaceBound
        * The outer boundary is specifically typed as IfcFaceOuterBound
        * Any holes are typed as IfcFaceBound (non-outer)
    """
    bounds = safe(face, "Bounds") or []
    outers, inners = [], []
    for b in bounds:
        if b.is_a("IfcFaceOuterBound"):
            outers.append(b)
        else:
            inners.append(b)
    return outers, inners

def describe_loop(loop):
    """
    Provide a dictionary description for a loop attached to a face bound.

    Two common loop classes:
      - IfcPolyLoop: a simple polygon given by a list of IfcCartesianPoint in .Polygon
      - IfcEdgeLoop: a topological loop expressed as a sequence of IfcOrientedEdge in .EdgeList

    For IfcPolyLoop, we record point count and (optionally) actual coordinates.
    For IfcEdgeLoop, we record edge count, each oriented edge's start/end vertex coordinates,
    and the edge class (e.g., IfcEdge / IfcEdgeCurve).
    """
    t = loop.is_a()
    info = {"LoopType": t}

    if t == "IfcPolyLoop":
        # Polygon := [IfcCartesianPoint, ...]
        pts = safe(loop, "Polygon") or []
        info["PointCount"] = len(pts)

        if INCLUDE_POINTS:
            # Convert each IfcCartesianPoint to (x,y,z) tuple
            pts_list = [pt(p) for p in pts]
            # Optional truncation for readability on very large polygons
            if MAX_POINTS_TO_SHOW and len(pts_list) > MAX_POINTS_TO_SHOW:
                info["Points"] = pts_list[:MAX_POINTS_TO_SHOW] + [("…", f"{len(pts_list)-MAX_POINTS_TO_SHOW} more")]
            else:
                info["Points"] = pts_list

    elif t == "IfcEdgeLoop":
        # EdgeLoop := [IfcOrientedEdge, ...]
        edges = safe(loop, "EdgeList") or []
        info["EdgeCount"] = len(edges)
        seq = []

        for oe in edges:
            # IfcOrientedEdge fields we use:
            #   - Orientation (bool): whether the underlying edge direction is used as-is or reversed
            #   - EdgeElement       : the underlying IfcEdge/IfcEdgeCurve carrying endpoints (and sometimes curve data)
            edge = safe(oe, "EdgeElement")
            start = safe(edge, "EdgeStart")
            end = safe(edge, "EdgeEnd")

            seq.append({
                "Oriented": bool(safe(oe, "Orientation", True)),
                "EdgeClass": edge.is_a() if edge else None,
                # VertexPoint -> VertexGeometry (IfcCartesianPoint) -> Coordinates
                "Start": pt(safe(start, "VertexGeometry")),
                "End": pt(safe(end, "VertexGeometry")),
            })

        info["Edges"] = seq

    # Other loop classes exist but are rare; this function focuses on the most encountered ones.
    return info

def dump_shell(shell, label="Shell"):
    """
    Render both a human-readable text block and a structured dict for a given shell.

    Shell topology (IfcClosedShell):
      - CfsFaces: ordered collection of IfcFace / IfcAdvancedFace
        * each face has Bounds, which hold outer and inner loops (IfcFaceOuterBound / IfcFaceBound)
        * each bound has a 'Bound' attribute pointing to a loop (IfcPolyLoop / IfcEdgeLoop)
    """
    faces = safe(shell, "CfsFaces") or []
    data = {"label": label, "face_count": len(faces), "faces": []}
    lines = []
    lines.append(f"\n== {label}: {len(faces)} face(s) ==")

    for i, f in enumerate(faces, 1):
        # Record face id and class (IfcFace or IfcAdvancedFace)
        face_entry = {"id": f.id(), "class": f.is_a(), "outer_bounds": [], "inner_bounds": []}
        lines.append(f"\nFace {i}  #{f.id()}  ({f.is_a()})")

        # Split face bounds into outer vs inner, based on IFC class
        outers, inners = face_bounds(f)

        # --- Outer loops (IfcFaceOuterBound) ---
        for j, ob in enumerate(outers, 1):
            # Every bound references a Loop entity via .Bound
            loop = safe(ob, "Bound")
            # Build a descriptive dict for the loop content (poly points or edges)
            li = describe_loop(loop) if loop else {"LoopType": None}

            # Capture orientation flag at the bound level and the loop structure
            face_entry["outer_bounds"].append({"orientation": safe(ob, "Orientation"), "loop": li})

            # Pretty-print outer loop summary
            lines.append(f"  OuterBound {j}: Orientation={safe(ob, 'Orientation')}  Loop={li['LoopType']}")

            # Optional polygon vertices
            if li.get("PointCount") is not None:
                lines.append(f"    Points ({li['PointCount']}): {li.get('Points', '(hidden)')}")

            # Edge loop sequence (oriented edges with start/end vertices)
            if li.get("EdgeCount") is not None:
                lines.append(f"    EdgeLoop ({li['EdgeCount']} edges):")
                for k, e in enumerate(li.get("Edges", []), 1):
                    lines.append(f"      {k}. Oriented={e['Oriented']}, Edge={e['EdgeClass']}, Start={e['Start']}, End={e['End']}")

        # --- Inner loops (IfcFaceBound) ---
        for j, ib in enumerate(inners, 1):
            loop = safe(ib, "Bound")
            li = describe_loop(loop) if loop else {"LoopType": None}

            face_entry["inner_bounds"].append({"orientation": safe(ib, "Orientation"), "loop": li})

            lines.append(f"  InnerBound {j}: Orientation={safe(ib, 'Orientation')}  Loop={li['LoopType']}")

            if li.get("PointCount") is not None:
                lines.append(f"    Points ({li['PointCount']}): {li.get('Points', '(hidden)')}")
            if li.get("EdgeCount") is not None:
                lines.append(f"    EdgeLoop ({li['EdgeCount']} edges):")
                for k, e in enumerate(li.get("Edges", []), 1):
                    lines.append(f"      {k}. Oriented={e['Oriented']}, Edge={e['EdgeClass']}, Start={e['Start']}, End={e['End']}")

        # Append this face's structured data for JSON output
        data["faces"].append(face_entry)

    # Return the text block and the structured dict for this shell
    return "\n".join(lines), data

def main():
    # Open the IFC model file using IfcOpenShell
    model = ifcopenshell.open(IFC_FILE)

    # Fetch the IFC entity by its STEP id (e.g., #6726)
    ent = model.by_id(ENTITY_ID)
    if not ent:
        print(f"Entity #{ENTITY_ID} not found.")
        return

    # Build output file paths from OUT_DIR; files are auto-named by ENTITY_ID
    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_file = out_dir / f"brep_report_{ENTITY_ID}.txt"
    json_file = out_dir / f"brep_report_{ENTITY_ID}.json"

    # 'header_lines' collects context lines for the text report header.
    # 'json_payload' collects high-level metadata for the JSON report.
    header_lines = []
    json_payload = {"ifc_file": IFC_FILE, "entity_requested": ENTITY_ID, "generated": datetime.utcnow().isoformat()+"Z"}

    # If the user passed an IfcShapeRepresentation id, descend into its .Items to find a BRep.
    # ShapeRepresentation is a container whose .Items are the actual geometry items (e.g., IfcFacetedBrep).
    if ent.is_a("IfcShapeRepresentation"):
        items = ent.Items or []
        header_lines.append(f"Given IfcShapeRepresentation #{ent.id()} has {len(items)} item(s).")
        header_lines += [f"  -> Item #{it.id()} ({it.is_a()})" for it in items]

        # Prefer the first BRep geometry found under Items (IfcFacetedBrep / IfcAdvancedBrep).
        for it in items:
            if it and it.is_a() in ("IfcFacetedBrep", "IfcAdvancedBrep"):
                ent = it
                break
        else:
            # No BReps found beneath this ShapeRepresentation; write a short header and exit.
            header_lines.append("No BRep item found under this ShapeRepresentation.")
            txt_file.write_text("\n".join(header_lines), encoding="utf-8")
            print(f"Saved report: {txt_file}")
            return

    # From here on, 'ent' should be a BRep solid, a ClosedShell, or a Face (depending on what was passed/resolved).
    report_lines = []
    report_lines.append(f"BRep Inspect: #{ent.id()} ({ent.is_a()})")
    json_payload["entity_resolved"] = {"id": ent.id(), "class": ent.is_a()}

    # If the resolved entity is an IfcClosedShell, dump it directly (it already contains faces).
    if ent.is_a("IfcClosedShell"):
        text, data = dump_shell(ent, "Closed shell")
        report = "\n".join(header_lines + [report_lines[0], text])
        txt_file.write_text(report, encoding="utf-8")
        if WRITE_JSON:
            json_payload["shells"] = [data]
            json_file.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
        print(f"Saved report: {txt_file}")
        if WRITE_JSON: print(f"Saved JSON  : {json_file}")
        return

    # If it's a single IfcFace, wrap it in a tiny shim object exposing .CfsFaces=[face] so we can reuse dump_shell().
    if ent.is_a("IfcFace"):
        class P: pass
        p = P(); p.CfsFaces = [ent]
        text, data = dump_shell(p, "Single face (no shell)")
        report = "\n".join(header_lines + [report_lines[0], text])
        txt_file.write_text(report, encoding="utf-8")
        if WRITE_JSON:
            json_payload["shells"] = [data]
            json_file.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
        print(f"Saved report: {txt_file}")
        if WRITE_JSON: print(f"Saved JSON  : {json_file}")
        return

    # For proper BRep solids (IfcFacetedBrep / IfcAdvancedBrep), ensure they expose an outer shell.
    if not is_brep_like(ent):
        header_lines.append("The resolved entity is not a BRep-like solid (no Outer/OuterShell).")
        report = "\n".join(header_lines + report_lines)
        txt_file.write_text(report, encoding="utf-8")
        print(f"Saved report: {txt_file}")
        return

    # Extract outer and inner shells from the BRep and dump each to text and JSON structures.
    outer, inners = get_shells(ent)
    all_shells = []

    # Outer shell: the main bounding shell of the solid.
    if outer:
        text, data = dump_shell(outer, "Outer shell")
        all_shells.append(data)
        report_lines.append(text)
    else:
        report_lines.append("No outer shell found.")

    # Inner shells (voids): each represents a cavity within the solid.
    for idx, sh in enumerate(inners, 1):
        text, data = dump_shell(sh, f"Inner shell {idx} (void)")
        all_shells.append(data)
        report_lines.append(text)

    # Persist the final reports to disk.
    report = "\n".join(header_lines + report_lines)
    txt_file.write_text(report, encoding="utf-8")
    if WRITE_JSON:
        json_payload["shells"] = all_shells
        json_file.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    print(f"Saved report: {txt_file}")
    if WRITE_JSON:
        print(f"Saved JSON  : {json_file}")

if __name__ == "__main__":
    main()
